"""Step 2: measure the app's flood model against the frozen protocol. Read-only."""
import concurrent.futures as cf
import datetime
import hashlib
import json
import os
import sys
import time

ROOT = r"C:\Users\KANINIKA\OneDrive\Desktop\pramaan-sfic"
sys.path.insert(0, ROOT)
os.environ.setdefault("GEE_PROJECT_ID", "premium-cipher-513114-e0")
import gee_fetcher as gf  # noqa: E402
from gee_fetcher import ee  # noqa: E402

VAL = os.path.join(ROOT, "artifacts", "validation")
proto = json.load(open(os.path.join(VAL, "documented_floods_protocol.json"), encoding="utf-8"))

for rel, digest in proto["frozen_model_files"].items():
    now = hashlib.sha256(open(os.path.join(ROOT, rel), "rb").read()).hexdigest()
    if now != digest:
        sys.exit(f"ABORT: {rel} changed since the protocol was written.")
print("Model files match the protocol fingerprints.")

ok, err = gf.initialize_gee_with_project()
if not ok:
    sys.exit(err)


def run(point, date):
    aoi = ee.Geometry.Point([point["lon"], point["lat"]]).buffer(gf.ANALYSIS_DEFAULTS["aoi_radius_m"])
    for attempt in range(4):
        try:
            s1 = gf._analyze_sentinel1(aoi, datetime.date.fromisoformat(date["date"]), dict(gf.ANALYSIS_DEFAULTS))
            break
        except Exception as exc:  # retry on EE rate limits
            if attempt == 3 or "Too many" not in str(exc):
                return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
            time.sleep(5 * (attempt + 1))
    fmod = s1.get("flood_model") or {}
    fr = fmod.get("fractions_pct") or {}
    return {
        "status": fmod.get("status") or s1.get("status"),
        "message": fmod.get("message") or s1.get("message"),
        "post_image": (s1.get("post_image") or {}).get("id"),
        "acquired_utc": (s1.get("post_image") or {}).get("acquired_utc"),
        "model": fmod.get("version"),
        "method_note": fmod.get("method_note"),
        "flood_pct": fr.get("flood"), "uncertain_pct": fr.get("uncertain"),
        "permanent_water_pct": fr.get("permanent_water"), "excluded_pct": fr.get("excluded"),
        "post_vv_db": s1.get("post_mean_vv_db"), "baseline_vv_db": s1.get("baseline_mean_vv_db"),
    }


jobs = [(p, d) for d in proto["dates"] for p in proto["points"]]
rows = []
t0 = time.time()
with cf.ThreadPoolExecutor(max_workers=5) as pool:
    futs = {pool.submit(run, p, d): (p, d) for p, d in jobs}
    for fut in cf.as_completed(futs):
        p, d = futs[fut]
        r = fut.result()
        rows.append({"point": p["id"], "group": p["group"], "date": d["date"], "kind": d["kind"], **r})
        print(f"{len(rows):3}/{len(jobs)} {d['date']} {p['id']}: {r['status']} flood {r.get('flood_pct')}%"
              f" unc {r.get('uncertain_pct')}%", flush=True)
print(f"done in {time.time() - t0:.0f} s")

thr = 20.0


def detected(r):
    return r.get("flood_pct") is not None and r["flood_pct"] >= thr


valid = [r for r in rows if r.get("flood_pct") is not None]
big_years = ("2017", "2021", "2023", "2024")
c1 = [r for r in valid if r["kind"] == "flood" and r["group"] == "flood_zone" and r["date"][:4] in big_years]
c2 = [r for r in valid if r["kind"] == "dry"]
c3 = [r for r in valid if r["kind"] == "flood" and r["group"] == "high_ground"]


def share(rs, fn):
    return round(sum(1 for r in rs if fn(r)) / len(rs), 3) if rs else None


summary = {
    "C1_detection": {"n": len(c1), "detected_share": share(c1, detected), "required": ">= 0.50"},
    "C2_dry_false_alarms": {"n": len(c2), "not_detected_share": share(c2, lambda r: not detected(r)),
                            "required": ">= 0.90"},
    "C3_high_ground": {"n": len(c3), "not_detected_share": share(c3, lambda r: not detected(r)),
                       "required": ">= 0.80"},
    "2016_flood_zone_detected_share": share([r for r in valid if r["date"].startswith("2016")
                                             and r["group"] == "flood_zone"], detected),
    "errors_or_no_data": [r for r in rows if r.get("flood_pct") is None],
}
for key, minimum in (("C1_detection", 0.5), ("C2_dry_false_alarms", 0.9), ("C3_high_ground", 0.8)):
    v = summary[key].get("detected_share", summary[key].get("not_detected_share"))
    summary[key]["result"] = "PASS" if v is not None and v >= minimum else "FAIL"

stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
out = os.path.join(VAL, f"documented_floods_results_{stamp}.json")
json.dump({"protocol": "documented_floods_protocol.json", "run_utc": stamp, "summary": summary,
           "rows": sorted(rows, key=lambda r: (r["date"], r["point"]))},
          open(out, "w", encoding="utf-8"), indent=2)
print(json.dumps({k: v for k, v in summary.items() if k != "errors_or_no_data"}, indent=1))
print("errors/no-data:", len(summary["errors_or_no_data"]))
print("saved", out)
