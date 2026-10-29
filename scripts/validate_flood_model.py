"""Measure the accuracy of the Pramaana Sentinel-1 flood model.

Reference ("ground truth" proxy)
    Cloud-free Sentinel-2 surface water (MNDWI = (B3 - B11) / (B3 + B11)) acquired
    within --max-gap-days of a Sentinel-1 pass. Confident water (MNDWI >= 0.1) on
    land that is rarely water (JRC occurrence < 25 %) is "new water"; confident dry
    (MNDWI <= -0.15) is "dry". Ambiguous MNDWI values are not used. This is an
    independent optical sensor, NOT a field survey: turbid water, flooded paddy
    under a crop canopy and timing differences between the passes all add noise.

Procedure
    1. Find Sentinel-1 / Sentinel-2 pairs over the region in each --period.
    2. Draw a class-balanced sample of reference pixels for every pair.
    3. Split samples into calibration and test halves by ~2 km map blocks.
    4. Calibrate the model on the calibration half only.
    5. Report accuracy of the legacy rule, the default model and the calibrated
       model on the held-out test half.

Usage
    $env:GEE_PROJECT_ID = "your-gcp-project-id"
    python scripts/validate_flood_model.py
    python scripts/validate_flood_model.py --write-calibration   # adopt the result in the app

Outputs go to artifacts/validation/ (JSON report + Markdown summary).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flood_model as fm  # noqa: E402

try:
    import ee
except ImportError:
    print("ERROR: earthengine-api is not installed. Run: pip install earthengine-api")
    sys.exit(1)

GHATAL_LAT = 22.6654
GHATAL_LON = 87.7218
DEFAULT_PERIODS = [f"{y}-06-01:{y}-11-30" for y in range(2019, 2025)]
S2_CLEAR_SCL = [4, 5, 6]  # vegetation, bare soil, water
DAY_MS = 86_400_000


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=os.environ.get("GEE_PROJECT_ID", "").strip())
    ap.add_argument("--lat", type=float, default=GHATAL_LAT)
    ap.add_argument("--lon", type=float, default=GHATAL_LON)
    ap.add_argument("--radius-m", type=int, default=15000, help="study region radius")
    ap.add_argument("--period", action="append", help="START:END (repeatable)")
    ap.add_argument("--max-gap-days", type=float, default=1.0)
    ap.add_argument("--min-clear-frac", type=float, default=0.3,
                    help="minimum cloud-free fraction of the region in the Sentinel-2 scene")
    ap.add_argument("--max-pairs", type=int, default=24)
    ap.add_argument("--points-per-class", type=int, default=1000)
    ap.add_argument("--water-mndwi", type=float, default=0.1)
    ap.add_argument("--dry-mndwi", type=float, default=-0.15)
    ap.add_argument("--open-water-max-ndvi", type=float, default=0.2,
                    help="reference water with NDVI above this is vegetated (flooded crop)")
    ap.add_argument("--min-coverage", type=float, default=0.85)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", default=os.path.join("artifacts", "validation"))
    ap.add_argument("--write-calibration", action="store_true",
                    help=f"save calibrated parameters to {os.path.relpath(fm.CALIBRATION_PATH)}")
    return ap.parse_args(argv)


def init_ee(project: str) -> None:
    sa = os.environ.get("GEE_SERVICE_ACCOUNT", "").strip()
    key = os.environ.get("GEE_PRIVATE_KEY_JSON", "").strip()
    if sa and key and os.path.exists(key):
        ee.Initialize(credentials=ee.ServiceAccountCredentials(sa, key), project=project)
    else:
        ee.Initialize(project=project)


def utc(ms: float) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def s1_collection(region: Any) -> Any:
    return (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(region)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            .select("VV"))


def s2_clear_mndwi(img: Any) -> Any:
    scl = img.select("SCL")
    clear = scl.eq(S2_CLEAR_SCL[0])
    for c in S2_CLEAR_SCL[1:]:
        clear = clear.Or(scl.eq(c))
    clear = clear.And(img.select("MSK_CLDPRB").lt(20))
    return ee.Image.cat([img.normalizedDifference(["B3", "B11"]).rename("mndwi"),
                         img.normalizedDifference(["B8", "B4"]).rename("ndvi")]).updateMask(clear)


def find_pairs(region: Any, start: str, end: str, args: argparse.Namespace) -> List[Dict[str, Any]]:
    s1 = s1_collection(region).filterDate(start, end)
    s1_info = ee.Dictionary({
        "t": s1.aggregate_array("system:time_start"),
        "orbit": s1.aggregate_array("relativeOrbitNumber_start"),
        "pass": s1.aggregate_array("orbitProperties_pass"),
    }).getInfo()
    passes: Dict[tuple, float] = {}
    for t, orbit, direction in zip(s1_info["t"], s1_info["orbit"], s1_info["pass"]):
        key = (utc(t)[:10], orbit, direction)
        passes.setdefault(key, t)

    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region)
          .filterDate(start, end).filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 70)))
    s2_days = sorted({utc(t)[:10] for t in s2.aggregate_array("system:time_start").getInfo()})
    print(f"  {start}..{end}: {len(passes)} Sentinel-1 passes, {len(s2_days)} Sentinel-2 days (<70% cloud)")

    candidates = []
    for (day, orbit, direction), t in passes.items():
        for s2_day in s2_days:
            gap = abs((datetime.date.fromisoformat(s2_day) - datetime.date.fromisoformat(day)).days)
            if gap <= args.max_gap_days:
                candidates.append({"s1_day": day, "s1_time_ms": t, "orbit": orbit, "pass": direction,
                                   "s2_day": s2_day, "gap_days": gap})
    pairs = []
    for c in sorted(candidates, key=lambda c: c["gap_days"]):
        next_day = (datetime.date.fromisoformat(c["s2_day"]) + datetime.timedelta(days=1)).isoformat()
        mndwi = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region)
                 .filterDate(c["s2_day"], next_day).map(s2_clear_mndwi).mosaic())
        frac = mndwi.mask().reduceRegion(ee.Reducer.mean(), region, 100, maxPixels=1e9,
                                         bestEffort=True).get("mndwi").getInfo()
        c["s2_clear_frac"] = round(float(frac or 0), 3)
        if c["s2_clear_frac"] >= args.min_clear_frac:
            pairs.append(c)
    return pairs


def sample_pair(pair: Dict[str, Any], region: Any, anc: Dict[str, Any],
                args: argparse.Namespace, idx: int) -> List[Dict[str, Any]]:
    day = pair["s1_day"]
    next_day = (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat()
    same_geom = (s1_collection(region)
                 .filter(ee.Filter.eq("relativeOrbitNumber_start", pair["orbit"]))
                 .filter(ee.Filter.eq("orbitProperties_pass", pair["pass"])))
    post = same_geom.filterDate(day, next_day).mosaic().focalMedian(30, "circle", "meters").rename("post")
    b_end = datetime.date.fromisoformat(day) - datetime.timedelta(days=5)
    b_start = b_end - datetime.timedelta(days=60)
    base_col = same_geom.filterDate(b_start.isoformat(), b_end.isoformat())
    n_base = base_col.size().getInfo()
    if n_base == 0:
        print(f"    skip {day}: no same-orbit baseline")
        return []
    base = base_col.median().focalMedian(30, "circle", "meters").rename("base")

    hist = ee.Dictionary(fm.ee_histogram(ee, post, region)).getInfo()
    choice = fm.choose_threshold(hist, fm.DEFAULT_PARAMS)
    pair["otsu"] = choice
    otsu_thr = choice["threshold_db"] if choice["method"] == "otsu" else None

    s2_next = (datetime.date.fromisoformat(pair["s2_day"]) + datetime.timedelta(days=1)).isoformat()
    s2_now = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region)
              .filterDate(pair["s2_day"], s2_next).map(s2_clear_mndwi).mosaic())
    mndwi, ndvi = s2_now.select("mndwi"), s2_now.select("ndvi")
    # Optical state over the same window as the radar baseline, so the reference
    # asks the model's question: was this land dry before and water now?
    pre_mndwi = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region)
                 .filterDate(b_start.isoformat(), b_end.isoformat()).map(s2_clear_mndwi).median().select("mndwi"))
    new_water = mndwi.gte(args.water_mndwi).And(pre_mndwi.lte(args.dry_mndwi)).And(anc["jrc"].lt(25))
    ref = (ee.Image.constant(-1)
           .where(mndwi.lte(args.dry_mndwi), 0)
           .where(new_water.unmask(0), 1))
    ref = ref.updateMask(mndwi.mask().And(ref.gte(0))).rename("ref").toInt()

    stack = ee.Image.cat([post, base, anc["jrc"], anc["hand"], anc["slope"],
                          mndwi.rename("s2_mndwi"), ndvi.rename("s2_ndvi"), ref])
    fc = stack.stratifiedSample(numPoints=args.points_per_class, classBand="ref", region=region,
                                scale=10, seed=args.seed + idx, geometries=True, tileScale=4)
    feats = fc.getInfo()["features"]
    out = []
    for f in feats:
        p = f["properties"]
        if p.get("post") is None or p.get("base") is None:
            continue
        lon, lat = f["geometry"]["coordinates"]
        out.append({"pair": idx, "lon": lon, "lat": lat, "post": p["post"], "base": p["base"],
                    "jrc": p.get("jrc"), "hand": p.get("hand"), "slope": p.get("slope"),
                    "s2_mndwi": p.get("s2_mndwi"), "s2_ndvi": p.get("s2_ndvi"),
                    "ref": p["ref"], "otsu_threshold_db": otsu_thr})
    pair["baseline_images"] = n_base
    pair["samples_water"] = sum(s["ref"] for s in out)
    pair["samples_dry"] = len(out) - pair["samples_water"]
    print(f"    pair {idx}: S1 {day} / S2 {pair['s2_day']} clear {pair['s2_clear_frac']:.0%} "
          f"-> {pair['samples_water']} water, {pair['samples_dry']} dry; threshold "
          f"{choice['threshold_db']} dB ({choice['method']})")
    return out


def fmt(x: Optional[float], pct: bool = True) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:.1f}%" if pct else f"{x:.3f}"


def markdown_report(report: Dict[str, Any]) -> str:
    lines = [
        "# Pramaana flood model validation",
        "",
        f"Generated {report['generated_utc']} · model {report['model_version']}",
        "",
        f"Region: {report['region']['lat']}, {report['region']['lon']} (radius {report['region']['radius_m']} m)  ",
        f"Pairs used: {len(report['pairs'])} · samples: {report['samples']['total']} "
        f"(calibration {report['samples']['calibration']}, held-out test {report['samples']['test']})",
        "",
        "Reference: cloud-free Sentinel-2 MNDWI (independent optical proxy, not field survey). "
        "Samples are class-balanced, so overall accuracy is not area-weighted.",
        "",
    ]
    for title, key in (("Held-out test accuracy: open (non-vegetated) new water vs dry", "test_results"),
                       ("Held-out test accuracy: all optical new water, incl. flooded crops",
                        "test_results_including_vegetated_water")):
        lines += ["", f"## {title}", "",
                  "| Model | Coverage | Overall acc. | Flood precision | Flood recall | Flood F1 | Kappa | F1 if abstentions = errors |",
                  "|---|---|---|---|---|---|---|---|"]
        for name, res in report[key].items():
            d, w = res["decided"], res["abstentions_as_errors"]
            lines.append(f"| {name} | {fmt(res['coverage'])} | {fmt(d['overall_accuracy'])} | "
                         f"{fmt(d['precision_flood'])} | {fmt(d['recall_flood'])} | {fmt(d['f1_flood'])} | "
                         f"{fmt(d['kappa'], pct=False)} | {fmt(w['f1_flood'])} |")
    lines += ["", "## Calibrated parameters", "", "```json",
              json.dumps(report["calibrated_params"], indent=2), "```", "", "## Pairs", "",
              "| S1 date | S2 date | Orbit | S2 clear | Threshold | Water / dry samples |",
              "|---|---|---|---|---|---|"]
    for p in report["pairs"]:
        o = p.get("otsu") or {}
        lines.append(f"| {p['s1_day']} | {p['s2_day']} | {p['orbit']} {p['pass']} | {fmt(p['s2_clear_frac'])} | "
                     f"{o.get('threshold_db')} dB ({o.get('method')}) | {p.get('samples_water')} / {p.get('samples_dry')} |")
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in report["limitations"]]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if not args.project:
        print("ERROR: set GEE_PROJECT_ID or pass --project <your-gcp-project-id>.")
        return 1
    init_ee(args.project)
    region = ee.Geometry.Point([args.lon, args.lat]).buffer(args.radius_m)
    anc = fm.ee_ancillary(ee)

    print("Finding Sentinel-1 / cloud-free Sentinel-2 pairs...")
    pairs: List[Dict[str, Any]] = []
    for period in args.period or DEFAULT_PERIODS:
        start, end = period.split(":")
        pairs += find_pairs(region, start, end, args)
    pairs = sorted(pairs, key=lambda p: (p["gap_days"], -p["s2_clear_frac"]))[: args.max_pairs]
    if not pairs:
        print("No usable pairs found. Try a wider --period, --max-gap-days 2 or --min-clear-frac 0.15.")
        return 2

    print(f"Sampling {len(pairs)} pair(s)...")
    samples: List[Dict[str, Any]] = []
    used_pairs = []
    for i, pair in enumerate(pairs):
        got = sample_pair(pair, region, anc, args, i)
        if got:
            samples += got
            used_pairs.append(pair)
    n_water = sum(s["ref"] for s in samples)
    if n_water < 50 or len(samples) - n_water < 50:
        print(f"Too few reference samples (water {n_water}, dry {len(samples) - n_water}); "
              "accuracy would not be meaningful. Widen the periods or region.")
        return 2

    calib_all, test_all = fm.spatial_block_split(samples, seed=args.seed)

    def open_water(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Radar cannot see water under a crop canopy; score it on open water and
        # report vegetated water separately instead of hiding it.
        return [s for s in rows if not s["ref"]
                or (s.get("s2_ndvi") is not None and s["s2_ndvi"] < args.open_water_max_ndvi)]

    calib, test = open_water(calib_all), open_water(test_all)
    print(f"Calibrating on {len(calib)} samples; testing on {len(test)} held-out samples "
          f"(open water vs dry)...")
    params, calib_res = fm.calibrate(calib, min_coverage=args.min_coverage)

    models = {
        "Legacy rule (-18 dB fixed)": fm.legacy_predict,
        "v0.3 default (uncalibrated)": fm.make_predictor(fm.DEFAULT_PARAMS),
        "v0.3 calibrated": fm.make_predictor(params),
    }
    test_results = {name: fm.evaluate(test, fn) for name, fn in models.items()}
    test_results_all_water = {name: fm.evaluate(test_all, fn) for name, fn in models.items()}
    report = {
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_version": fm.FLOOD_MODEL_VERSION,
        "region": {"lat": args.lat, "lon": args.lon, "radius_m": args.radius_m},
        "reference": {
            "source": "COPERNICUS/S2_SR_HARMONIZED MNDWI (B3, B11), SCL 4/5/6 and cloud prob < 20%",
            "water_mndwi_min": args.water_mndwi, "dry_mndwi_max": args.dry_mndwi,
            "new_water_requires_pre_event_mndwi_at_most": args.dry_mndwi,
            "new_water_requires_jrc_occurrence_below": 25, "max_gap_days": args.max_gap_days,
            "open_water_max_ndvi": args.open_water_max_ndvi,
        },
        "split": "spatial blocks of 0.02 degrees (~2 km); calibration and test never share a block",
        "pairs": used_pairs,
        "samples": {"total": len(samples), "calibration": len(calib), "test": len(test),
                    "water": n_water, "dry": len(samples) - n_water,
                    "open_water": sum(1 for s in open_water(samples) if s["ref"])},
        "calibrated_params": params.to_dict(),
        "calibration_results": calib_res,
        "test_results": test_results,
        "test_results_including_vegetated_water": test_results_all_water,
        "limitations": [
            "Reference is Sentinel-2 optical water, not field observation; it misses water under "
            "crop canopy and can mislabel turbid floodwater or wet soil.",
            "Sentinel-1 and Sentinel-2 passes can differ by up to the stated gap; water levels change.",
            "Samples are class-balanced; real-world flood prevalence differs, so precision on "
            "actual claims may be lower than shown.",
            "Pairs are limited to dates with cloud-free optical data, which are rare at flood peak.",
            "Accuracy is specific to this region and period; re-validate before use elsewhere.",
        ],
    }
    os.makedirs(args.out_dir, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = os.path.join(args.out_dir, f"flood_validation_{stamp}.json")
    md_path = os.path.join(args.out_dir, f"flood_validation_{stamp}.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    with open(os.path.join(args.out_dir, f"flood_validation_{stamp}_samples.json"), "w",
              encoding="utf-8") as fh:
        json.dump(samples, fh)
    md = markdown_report(report)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    print("\n" + md)
    print(f"Saved {json_path}\nSaved {md_path}")

    if args.write_calibration:
        cal_test = test_results["v0.3 calibrated"]
        calibration = {
            "params": params.to_dict(),
            "model_version": fm.FLOOD_MODEL_VERSION,
            "calibrated_utc": report["generated_utc"],
            "validation_report": os.path.relpath(json_path).replace(os.sep, "/"),
            "reference": "Sentinel-2 open-water MNDWI proxy (not field survey)",
            "region": report["region"],
            "pairs": len(used_pairs),
            "test_samples": cal_test["samples"],
            "test_coverage": cal_test["coverage"],
            "test_overall_accuracy": cal_test["decided"]["overall_accuracy"],
            "test_f1_flood": cal_test["decided"]["f1_flood"],
            "test_kappa": cal_test["decided"]["kappa"],
            "test_f1_flood_including_vegetated_water":
                test_results_all_water["v0.3 calibrated"]["decided"]["f1_flood"],
        }
        os.makedirs(os.path.dirname(fm.CALIBRATION_PATH), exist_ok=True)
        with open(fm.CALIBRATION_PATH, "w", encoding="utf-8") as fh:
            json.dump(calibration, fh, indent=2)
        print(f"Wrote calibration to {fm.CALIBRATION_PATH}; the app will use it on next start.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
