"""Step 3 (read-only): check selected documented-flood rows against Sentinel-2.

Rule, fixed before running (same thresholds as scripts/monitor_flood.py):
  - Optical scene: clear Sentinel-2 pixels (SCL 4/5/6, cloud prob < 20) within
    +/- WINDOW_DAYS of the radar pass, mosaicked; 250 m radius around the point.
  - Water: MNDWI >= 0.1. Dry: MNDWI <= -0.15.
  - Part A, the 6 dry-year false alarms: among pixels the model classed as flood
    and that have a clear optical view, verdict =
      'real water'   if >= 50 % optical water,
      'false alarm'  if >= 50 % optical dry,
      'mixed'        otherwise,
      'no clear view' if fewer than MIN_PIXELS such pixels.
  - Part B, the 2023-10-07 and 2024-09-19 flood-zone rows (the weak detections):
    share of the clear area that is optical water, and the model's flood % on those
    same clear pixels. 'missed water' if optical water >= 20 % of the clear area
    while the model flags < 20 %; otherwise 'agrees'; 'no clear view' if fewer than
    MIN_PIXELS clear pixels.
The model is run exactly as the app runs it (gee_fetcher internals, frozen files).
"""
import datetime
import hashlib
import json
import os
import sys

ROOT = r"C:\Users\KANINIKA\OneDrive\Desktop\pramaan-sfic"
sys.path.insert(0, ROOT)
os.environ.setdefault("GEE_PROJECT_ID", "premium-cipher-513114-e0")
import flood_model as fm  # noqa: E402
import gee_fetcher as gf  # noqa: E402
from gee_fetcher import ee  # noqa: E402

WINDOW_DAYS = 3
MIN_PIXELS = 100
VAL = os.path.join(ROOT, "artifacts", "validation")
proto = json.load(open(os.path.join(VAL, "documented_floods_protocol.json"), encoding="utf-8"))
for rel, digest in proto["frozen_model_files"].items():
    if hashlib.sha256(open(os.path.join(ROOT, rel), "rb").read()).hexdigest() != digest:
        sys.exit(f"ABORT: {rel} changed since the protocol was written.")
results_file = sorted(f for f in os.listdir(VAL) if f.startswith("documented_floods_results_") and f.endswith(".json"))[-1]
rows = json.load(open(os.path.join(VAL, results_file), encoding="utf-8"))["rows"]
points = {p["id"]: p for p in proto["points"]}

part_a = [r for r in rows if r["kind"] == "dry" and (r.get("flood_pct") or 0) >= 20]
part_b = [r for r in rows if r["group"] == "flood_zone" and r["date"] in ("2023-10-07", "2024-09-19")]

ok, err = gf.initialize_gee_with_project()
if not ok:
    sys.exit(err)


def model_class_image(aoi, date):
    """Rebuild the app's classification image for this AOI/date (same steps as _analyze_sentinel1)."""
    incident = datetime.date.fromisoformat(date)
    p = gf.ANALYSIS_DEFAULTS
    col = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(aoi)
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV")).select("VV"))
    post_end = incident + datetime.timedelta(days=p["s1_post_window_days"])
    first = ee.Image(col.filterDate(incident.isoformat(), post_end.isoformat()).sort("system:time_start").first())
    props = ee.Dictionary({"id": first.get("system:index"), "pass": first.get("orbitProperties_pass"),
                           "orbit": first.get("relativeOrbitNumber_start")}).getInfo()
    b_end = incident - datetime.timedelta(days=p["s1_baseline_gap_days"])
    b_start = b_end - datetime.timedelta(days=p["s1_baseline_days"])
    baseline = (col.filterDate(b_start.isoformat(), b_end.isoformat())
                .filter(ee.Filter.eq("orbitProperties_pass", props["pass"]))
                .filter(ee.Filter.eq("relativeOrbitNumber_start", props["orbit"])))
    post_vv = first.focalMedian(30, "circle", "meters")
    base_vv = baseline.median().focalMedian(30, "circle", "meters")
    vh = gf._dual_pol_inputs(aoi, f"COPERNICUS/S1_GRD/{props['id']}", props, b_start, b_end)
    feats = fm.ee_rf_features(ee, post_vv, base_vv, vh[0], vh[1])
    return fm.ee_rf_classify(ee, feats, gf.FLOOD_RF["trees"], gf.FLOOD_RF["meta"]["margin"])


def s2_mndwi(aoi, date):
    d = datetime.date.fromisoformat(date)
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(aoi)
           .filterDate((d - datetime.timedelta(days=WINDOW_DAYS)).isoformat(),
                       (d + datetime.timedelta(days=WINDOW_DAYS + 1)).isoformat()))
    days = sorted({gf._ms_to_utc(t)[:10] for t in col.aggregate_array("system:time_start").getInfo()})

    def clear(img):
        scl = img.select("SCL")
        m = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).And(img.select("MSK_CLDPRB").lt(20))
        return img.normalizedDifference(["B3", "B11"]).rename("mndwi").updateMask(m)
    return col.map(clear).mosaic(), days


out = []
for part, items in (("A_dry_false_alarm", part_a), ("B_weak_detection", part_b)):
    for r in items:
        pt = points[r["point"]]
        aoi = ee.Geometry.Point([pt["lon"], pt["lat"]]).buffer(gf.ANALYSIS_DEFAULTS["aoi_radius_m"])
        rec = {"part": part, "point": r["point"], "date": r["date"], "model_flood_pct": r["flood_pct"]}
        try:
            mndwi, days = s2_mndwi(aoi, r["date"])
            rec["s2_dates"] = days
            if not days:
                rec["verdict"] = "no clear view"
                rec["reason"] = f"No Sentinel-2 image within {WINDOW_DAYS} days."
                out.append(rec)
                print(rec)
                continue
            cls = model_class_image(aoi, r["date"])
            flood = cls.eq(fm.CLASS_CODES["flood"])
            seen = mndwi.mask()
            c = ee.Image.cat([
                seen.rename("clear"),
                mndwi.gte(0.1).rename("water"),
                flood.And(seen).rename("flood_clear"),
                flood.And(mndwi.gte(0.1)).rename("flood_water"),
                flood.And(mndwi.lte(-0.15)).rename("flood_dry"),
            ]).unmask(0).reduceRegion(ee.Reducer.sum(), aoi, 10, maxPixels=1e8).getInfo()
            rec["counts"] = {k: int(v or 0) for k, v in c.items()}
            n = rec["counts"]
            if part == "A_dry_false_alarm":
                if n["flood_clear"] < MIN_PIXELS:
                    rec["verdict"] = "no clear view"
                else:
                    w, d_ = n["flood_water"] / n["flood_clear"], n["flood_dry"] / n["flood_clear"]
                    rec.update(optical_water_share=round(w, 3), optical_dry_share=round(d_, 3))
                    rec["verdict"] = "real water" if w >= 0.5 else ("false alarm" if d_ >= 0.5 else "mixed")
            else:
                if n["clear"] < MIN_PIXELS:
                    rec["verdict"] = "no clear view"
                else:
                    ow = n["water"] / n["clear"]
                    mf = n["flood_clear"] / n["clear"]
                    rec.update(optical_water_pct=round(ow * 100, 1), model_flood_pct_on_clear=round(mf * 100, 1))
                    rec["verdict"] = "missed water" if ow >= 0.2 and mf < 0.2 else "agrees"
        except Exception as exc:
            rec["verdict"] = "error"
            rec["reason"] = f"{type(exc).__name__}: {exc}"
        out.append(rec)
        print(rec, flush=True)

stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
path = os.path.join(VAL, f"documented_floods_optical_{stamp}.json")
json.dump({"rule": __doc__, "source_results": results_file, "rows": out}, open(path, "w", encoding="utf-8"), indent=2)
print("saved", path)
