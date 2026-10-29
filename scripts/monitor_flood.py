"""Area flood monitor: check the newest Sentinel-1 pass over a block and flag new flooding.

Runs without any claim. Each run:
  1. Finds the newest Sentinel-1 IW pass over the area (last --lookback-days).
  2. Skips it if it was already processed (state file), unless --force.
  3. Builds a same-orbit baseline (60 days ending 5 days before the pass).
  4. Classifies with the same model the app uses (random forest if a validated
     model and VH exist, otherwise the calibrated rule).
  5. Cross-checks the radar flood pixels against any clear Sentinel-2 image within
     --optical-gap-days: radar alone mistakes harvested paddy for water, so an alert
     is marked confirmed / contradicted / unconfirmed (no clear optical view).
  6. Appends a record to artifacts/monitor/log.jsonl, saves a PNG map, and
     prints ALERT when the flooded share reaches --alert-pct.

Usage
    $env:GEE_PROJECT_ID = "your-gcp-project-id"
    python scripts/monitor_flood.py                     # Ghatal, 10 km radius
    python scripts/monitor_flood.py --lat 22.70 --lon 87.65 --radius-m 5000 --force

Exit code: 0 = checked (no alert / nothing new), 3 = ALERT, 1/2 = error.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.request
from typing import Any, Dict, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import flood_model as fm  # noqa: E402
import gee_fetcher as gf  # noqa: E402
from gee_fetcher import ee  # noqa: E402

OUT_DIR = os.path.join(ROOT, "artifacts", "monitor")
CLASS_COLOURS = ["d9d9d9", "1f6feb", "f2c94c", "0b2e59", "8c8c8c"]  # by CLASS_CODES value


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, default=gf.GHATAL_LAT)
    ap.add_argument("--lon", type=float, default=gf.GHATAL_LON)
    ap.add_argument("--radius-m", type=int, default=10000)
    ap.add_argument("--name", default="ghatal")
    ap.add_argument("--lookback-days", type=int, default=14)
    ap.add_argument("--alert-pct", type=float, default=5.0)
    ap.add_argument("--optical-gap-days", type=int, default=2)
    ap.add_argument("--min-optical-pixels", type=int, default=500,
                    help="radar-flood pixels with a clear optical view needed to judge an alert")
    ap.add_argument("--as-of", help="replay: treat this date (YYYY-MM-DD) as today")
    ap.add_argument("--force", action="store_true", help="re-process even if already seen")
    return ap.parse_args(argv)


def latest_pass(region: Any, lookback_days: int, as_of: Optional[str] = None) -> Optional[Dict[str, Any]]:
    today = (datetime.date.fromisoformat(as_of) if as_of
             else datetime.datetime.now(datetime.timezone.utc).date())
    col = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(region)
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
           .filterDate((today - datetime.timedelta(days=lookback_days)).isoformat(),
                       (today + datetime.timedelta(days=1)).isoformat())
           .sort("system:time_start", False))
    if col.size().getInfo() == 0:
        return None
    first = ee.Image(col.first())
    info = ee.Dictionary({"id": first.get("system:index"), "t": first.get("system:time_start"),
                          "pass": first.get("orbitProperties_pass"),
                          "orbit": first.get("relativeOrbitNumber_start")}).getInfo()
    info["day"] = gf._ms_to_utc(info["t"])[:10]
    return info


def s2_clear(img: Any) -> Any:
    scl = img.select("SCL")
    clear = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).And(img.select("MSK_CLDPRB").lt(20))
    return ee.Image.cat([img.normalizedDifference(["B3", "B11"]).rename("mndwi"),
                         img.normalizedDifference(["B8", "B4"]).rename("ndvi")]).updateMask(clear)


def optical_check(region: Any, cls: Any, day: datetime.date, gap_days: int,
                  min_pixels: int) -> Dict[str, Any]:
    """Compare radar flood pixels with Sentinel-2 water (MNDWI) near the pass date."""
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region)
           .filterDate((day - datetime.timedelta(days=gap_days)).isoformat(),
                       (day + datetime.timedelta(days=gap_days + 1)).isoformat()))
    days = sorted({gf._ms_to_utc(t)[:10] for t in col.aggregate_array("system:time_start").getInfo()})
    if not days:
        return {"status": "unconfirmed", "reason": f"No Sentinel-2 image within {gap_days} days."}
    s2 = col.map(s2_clear).mosaic()
    mndwi = s2.select("mndwi")
    flood = cls.eq(fm.CLASS_CODES["flood"])
    counts = ee.Image.cat([
        flood.And(mndwi.mask()).rename("checked"),
        flood.And(mndwi.gte(0.1)).rename("water"),
        flood.And(mndwi.lte(-0.15)).rename("dry"),
    ]).reduceRegion(ee.Reducer.sum(), region, 30, maxPixels=1e9, bestEffort=True).getInfo()
    checked = int(counts.get("checked") or 0)
    out = {"s2_dates": days, "flood_pixels_with_clear_view": checked}
    if checked < min_pixels:
        return dict(out, status="unconfirmed",
                    reason=f"Only {checked} radar-flood pixels had a cloud-free optical view.")
    water, dry = counts["water"] / checked, counts["dry"] / checked
    out.update(optical_water_share=round(water, 3), optical_dry_share=round(dry, 3))
    if water >= 0.5:
        return dict(out, status="confirmed", reason=f"{water:.0%} of checked flood pixels look like water optically.")
    if dry >= 0.5:
        return dict(out, status="contradicted",
                    reason=f"{dry:.0%} of checked flood pixels look dry optically (e.g. harvested "
                           f"paddy or ploughed soil can mimic water on radar).")
    return dict(out, status="unconfirmed", reason="Optical evidence is mixed.")


def classify_pass(region: Any, info: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    day = datetime.date.fromisoformat(info["day"])
    same = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(region)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.eq("orbitProperties_pass", info["pass"]))
            .filter(ee.Filter.eq("relativeOrbitNumber_start", info["orbit"])))
    post_all = same.filterDate(day.isoformat(), (day + datetime.timedelta(days=1)).isoformat())
    b_end = day - datetime.timedelta(days=5)
    b_start = b_end - datetime.timedelta(days=60)
    base_all = same.filterDate(b_start.isoformat(), b_end.isoformat())
    n_base = base_all.size().getInfo()
    if n_base == 0:
        raise RuntimeError("No same-orbit baseline images; cannot detect change.")

    def prep(col: Any, band: str) -> Any:
        return col.filter(ee.Filter.listContains("transmitterReceiverPolarisation", band)).select(band)

    post_vv = prep(post_all, "VV").mosaic().focalMedian(30, "circle", "meters")
    base_vv = prep(base_all, "VV").median().focalMedian(30, "circle", "meters")
    use_rf = bool(gf.FLOOD_RF) and prep(base_all, "VH").size().getInfo() > 0 \
        and prep(post_all, "VH").size().getInfo() > 0
    if use_rf:
        post_vh = prep(post_all, "VH").mosaic().focalMedian(30, "circle", "meters")
        base_vh = prep(base_all, "VH").median().focalMedian(30, "circle", "meters")
        feats = fm.ee_rf_features(ee, post_vv, base_vv, post_vh, base_vh)
        meta = gf.FLOOD_RF["meta"]
        cls = fm.ee_rf_classify(ee, feats, gf.FLOOD_RF["trees"], meta["margin"])
        method = f"random forest VV+VH ({meta['model_version']}), margin {meta['margin']}"
        accuracy = meta
    else:
        params = gf.FLOOD_PARAMS
        hist = fm.ee_histogram(ee, post_vv, region).getInfo() if params.threshold_mode == "otsu" else None
        choice = fm.choose_threshold(hist, params)
        cls = fm.ee_classify(ee, post_vv, base_vv, choice["threshold_db"], params)
        method = f"rule {fm.FLOOD_MODEL_VERSION}, threshold {choice['threshold_db']} dB ({choice['method']})"
        accuracy = gf.FLOOD_CALIBRATION
    cls = cls.clip(region)
    optical = optical_check(region, cls, day, args.optical_gap_days, args.min_optical_pixels)
    fr = fm.ee_class_fractions(ee, cls).reduceRegion(
        reducer=ee.Reducer.mean(), geometry=region, scale=30, maxPixels=1e9, bestEffort=True).getInfo()
    area_km2 = region.area(1).getInfo() / 1e6
    thumb = cls.getThumbURL({"region": region, "dimensions": 768, "format": "png",
                             "min": 0, "max": 4, "palette": CLASS_COLOURS})
    return {
        "method": method, "baseline_images": n_base,
        "fractions_pct": {k: round(float(fr.get(k) or 0) * 100, 2) for k in fm.CLASS_CODES},
        "area_km2": round(area_km2, 1),
        "accuracy": {k: accuracy.get(k) for k in ("test_f1_flood", "test_overall_accuracy",
                                                  "test_coverage", "reference")} if accuracy else None,
        "thumb_url": thumb,
        "optical_check": optical,
    }


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    ok, err = gf.initialize_gee_with_project()
    if not ok:
        print(f"ERROR: {err}")
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    state_path = os.path.join(OUT_DIR, f"state_{args.name}.json")
    state: Dict[str, Any] = {}
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)

    region = ee.Geometry.Point([args.lon, args.lat]).buffer(args.radius_m)
    info = latest_pass(region, args.lookback_days, args.as_of)
    if info is None:
        print(f"No Sentinel-1 pass in the last {args.lookback_days} days.")
        return 0
    scene = f"COPERNICUS/S1_GRD/{info['id']}"
    if scene == state.get("last_scene") and not args.force:
        print(f"No new pass. Latest is still {scene} ({info['day']}).")
        return 0

    try:
        res = classify_pass(region, info, args)
    except Exception as exc:  # Earth Engine raises its own exception types
        print(f"ERROR classifying {scene}: {type(exc).__name__}: {exc}")
        return 2
    flood_pct = res["fractions_pct"]["flood"]
    record = {
        "checked_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "area": {"name": args.name, "lat": args.lat, "lon": args.lon, "radius_m": args.radius_m},
        "scene": scene, "acquired_utc": gf._ms_to_utc(info["t"]),
        "orbit": f"{info['orbit']} {info['pass']}",
        "flood_km2": round(res["area_km2"] * flood_pct / 100, 2),
        # An alert stands unless same-period optical data contradicts it.
        "alert": flood_pct >= args.alert_pct and res["optical_check"]["status"] != "contradicted",
        "radar_alert": flood_pct >= args.alert_pct,
        **{k: v for k, v in res.items() if k != "thumb_url"},
    }
    png = os.path.join(OUT_DIR, f"{args.name}_{info['day']}_{info['orbit']}.png")
    try:
        urllib.request.urlretrieve(res["thumb_url"], png)
        record["map_png"] = os.path.relpath(png, ROOT).replace(os.sep, "/")
        record["map_sha256"] = gf.compute_file_sha256(png)
    except OSError as exc:
        record["map_error"] = str(exc)
    with open(os.path.join(OUT_DIR, "log.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump({"last_scene": scene, "last_checked_utc": record["checked_utc"]}, fh)

    fr = res["fractions_pct"]
    oc = res["optical_check"]
    label = "ALERT" if record["alert"] else ("NOT CONFIRMED" if record["radar_alert"] else "OK")
    if record["alert"]:
        label += f" ({oc['status']})"
    print(f"{label}: {args.name} pass {record['acquired_utc']} "
          f"(orbit {record['orbit']}): {fr['flood']}% flood (~{record['flood_km2']} km2 of "
          f"{res['area_km2']} km2), {fr['uncertain']}% uncertain, {fr['permanent_water']}% permanent water")
    print(f"Method: {res['method']}")
    print(f"Optical check: {oc['status']} - {oc['reason']}")
    if record.get("map_png"):
        print(f"Map: {record['map_png']} (blue = flood, yellow = uncertain, navy = permanent water, "
              f"dark grey = excluded terrain)")
    return 3 if record["alert"] else 0


if __name__ == "__main__":
    sys.exit(main())
