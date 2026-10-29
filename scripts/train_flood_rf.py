"""Train and validate a random-forest flood model on Sentinel-1 VV + VH.

Uses the same reference as validate_flood_model.py (Sentinel-2 new water: dry
before, water now; confident dry otherwise) and the same date-pair search, but
adds VH backscatter so the model has a chance to see water under a rice canopy.

Split: a 0.02-degree (~2 km) checkerboard. The forest is trained in Earth Engine
on the calibration squares only; every model is scored on the test squares.

Usage
    $env:GEE_PROJECT_ID = "your-gcp-project-id"
    python scripts/train_flood_rf.py                 # report only
    python scripts/train_flood_rf.py --write-model   # adopt in the app if it beats v0.3
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flood_model as fm  # noqa: E402
import validate_flood_model as vfm  # noqa: E402
from validate_flood_model import ee  # noqa: E402

BLOCK_DEG = 0.02


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=os.environ.get("GEE_PROJECT_ID", "").strip())
    ap.add_argument("--lat", type=float, default=vfm.GHATAL_LAT)
    ap.add_argument("--lon", type=float, default=vfm.GHATAL_LON)
    ap.add_argument("--radius-m", type=int, default=15000)
    ap.add_argument("--period", action="append")
    ap.add_argument("--max-gap-days", type=float, default=1.0)
    ap.add_argument("--min-clear-frac", type=float, default=0.3)
    ap.add_argument("--max-pairs", type=int, default=24)
    ap.add_argument("--points-per-class", type=int, default=1000)
    ap.add_argument("--water-mndwi", type=float, default=0.1)
    ap.add_argument("--dry-mndwi", type=float, default=-0.15)
    ap.add_argument("--open-water-max-ndvi", type=float, default=0.2)
    ap.add_argument("--trees", type=int, default=40)
    ap.add_argument("--max-nodes", type=int, default=32)
    ap.add_argument("--margins", default="0.05,0.1,0.15,0.2",
                    help="probability margins around 0.5 tried for the uncertain class")
    ap.add_argument("--min-coverage", type=float, default=0.85)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", default=os.path.join("artifacts", "validation"))
    ap.add_argument("--write-model", action="store_true")
    ap.add_argument("--hold-out-dates", action="store_true",
                    help="stricter test: train on even-numbered date pairs, test on odd ones "
                         "(and still on separate map squares)")
    ap.add_argument("--rows", help="reuse samples saved by an earlier run (skips sampling)")
    ap.add_argument("--max-train", type=int, default=12000,
                    help="cap on calibration samples uploaded for training")
    return ap.parse_args(argv)


def s1_dual(region: Any) -> Any:
    return vfm.s1_collection(region).filter(
        ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))


def pair_samples(pair: Dict[str, Any], region: Any, anc: Dict[str, Any],
                 args: argparse.Namespace, idx: int) -> Optional[Any]:
    """Server-side FeatureCollection of labelled samples for one pair (or None)."""
    day = pair["s1_day"]
    next_day = (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat()
    col = (ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(region)
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
           .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
           .filter(ee.Filter.eq("relativeOrbitNumber_start", pair["orbit"]))
           .filter(ee.Filter.eq("orbitProperties_pass", pair["pass"]))
           .select(["VV", "VH"]))
    b_end = datetime.date.fromisoformat(day) - datetime.timedelta(days=5)
    b_start = b_end - datetime.timedelta(days=60)
    base_col = col.filterDate(b_start.isoformat(), b_end.isoformat())
    if col.filterDate(day, next_day).size().getInfo() == 0 or base_col.size().getInfo() == 0:
        print(f"    skip {day}: no dual-pol post image or baseline")
        return None
    post = col.filterDate(day, next_day).mosaic().focalMedian(30, "circle", "meters")
    base = base_col.median().focalMedian(30, "circle", "meters")
    feats = fm.ee_rf_features(ee, post.select("VV"), base.select("VV"),
                              post.select("VH"), base.select("VH"), anc)

    s2_next = (datetime.date.fromisoformat(pair["s2_day"]) + datetime.timedelta(days=1)).isoformat()
    s2_now = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region)
              .filterDate(pair["s2_day"], s2_next).map(vfm.s2_clear_mndwi).mosaic())
    mndwi, ndvi = s2_now.select("mndwi"), s2_now.select("ndvi")
    pre_mndwi = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(region)
                 .filterDate(b_start.isoformat(), b_end.isoformat())
                 .map(vfm.s2_clear_mndwi).median().select("mndwi"))
    new_water = mndwi.gte(args.water_mndwi).And(pre_mndwi.lte(args.dry_mndwi)).And(anc["jrc"].lt(25))
    ref = ee.Image.constant(-1).where(mndwi.lte(args.dry_mndwi), 0).where(new_water.unmask(0), 1)
    ref = ref.updateMask(mndwi.mask().And(ref.gte(0))).rename("ref").toInt()

    stack = feats.addBands([ndvi.rename("s2_ndvi"), ref])
    fc = stack.stratifiedSample(numPoints=args.points_per_class, classBand="ref", region=region,
                                scale=10, seed=args.seed + idx, geometries=True, tileScale=4)

    def tag(f: Any) -> Any:
        c = f.geometry().coordinates()
        lon, lat = ee.Number(c.get(0)), ee.Number(c.get(1))
        parity = lon.divide(BLOCK_DEG).floor().add(lat.divide(BLOCK_DEG).floor()).mod(2)
        return f.set({"lon": lon, "lat": lat, "pair": idx, "test": parity.eq(1)})

    return fc.map(tag).filter(ee.Filter.notNull(fm.RF_FEATURES))


def to_rows(fc: Any) -> List[Dict[str, Any]]:
    cols = fm.RF_FEATURES + ["s2_ndvi", "ref", "lon", "lat", "pair", "test"]
    data = fc.reduceColumns(ee.Reducer.toList(len(cols)), cols).get("list").getInfo()
    rows = []
    for vals in data:
        r = dict(zip(cols, vals))
        r.update(post=r["vv_post"], base=r["vv_base"])
        rows.append(r)
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if not args.project:
        print("ERROR: set GEE_PROJECT_ID or pass --project.")
        return 1
    vfm.init_ee(args.project)
    region = ee.Geometry.Point([args.lon, args.lat]).buffer(args.radius_m)
    anc = fm.ee_ancillary(ee)

    print("Finding Sentinel-1 / cloud-free Sentinel-2 pairs...")
    pairs: List[Dict[str, Any]] = []
    for period in args.period or vfm.DEFAULT_PERIODS:
        start, end = period.split(":")
        pairs += vfm.find_pairs(region, start, end, args)
    pairs = sorted(pairs, key=lambda p: (p["gap_days"], -p["s2_clear_frac"]))[: args.max_pairs]

    rows: List[Dict[str, Any]] = []
    fcs = []
    if args.rows:
        with open(args.rows, encoding="utf-8") as fh:
            saved = json.load(fh)
        rows, pairs = saved["rows"], saved["pairs"]
        fcs = [None] * len({r["pair"] for r in rows})
        print(f"Loaded {len(rows)} samples from {args.rows}")
        pairs_to_sample: List[Dict[str, Any]] = []
    else:
        pairs_to_sample = pairs
    for i, pair in enumerate(pairs_to_sample):
        fc = pair_samples(pair, region, anc, args, i)
        if fc is None:
            continue
        got = to_rows(fc)
        print(f"    pair {i}: S1 {pair['s1_day']} / S2 {pair['s2_day']}: "
              f"{sum(r['ref'] for r in got)} water, {sum(1 - r['ref'] for r in got)} dry")
        rows += got
        fcs.append(fc)
    if not fcs:
        print("No usable pairs.")
        return 2
    os.makedirs(args.out_dir, exist_ok=True)
    if not args.rows:
        rows_path = os.path.join(args.out_dir, "rf_samples_latest.json")
        with open(rows_path, "w", encoding="utf-8") as fh:
            json.dump({"pairs": pairs, "rows": rows}, fh)
        print(f"Saved samples to {rows_path} (reuse with --rows)")

    # Sanity check: server and client agree on the split.
    mismatch = sum(1 for r in rows if bool(r["test"]) != fm.checkerboard_test_block(r["lon"], r["lat"], BLOCK_DEG))
    print(f"Split check: {mismatch} of {len(rows)} samples disagree between server and client.")

    calib = [r for r in rows if not r["test"]]
    test = [r for r in rows if r["test"]]
    if args.hold_out_dates:
        calib = [r for r in calib if r["pair"] % 2 == 0]
        test = [r for r in test if r["pair"] % 2 == 1]
    print(f"Training random forest ({args.trees} trees) on {len(calib)} calibration samples...")
    # Upload the already-downloaded calibration rows; training on the server-side
    # sample collections would recompute all pairs at once and hit EE limits.
    import random
    train_rows = random.Random(args.seed).sample(calib, min(len(calib), args.max_train))
    train_fc = ee.FeatureCollection([
        ee.Feature(None, {**{k: round(float(r[k]), 3) for k in fm.RF_FEATURES}, "ref": int(r["ref"])})
        for r in train_rows
    ])
    rf = ee.Classifier.smileRandomForest(numberOfTrees=args.trees, maxNodes=args.max_nodes,
                                         seed=args.seed).setOutputMode("PROBABILITY")
    rf = rf.train(train_fc, "ref", fm.RF_FEATURES)
    tree_text = ee.List(rf.explain().get("trees")).getInfo()
    trees = [fm.parse_tree(t) for t in tree_text]
    importance = rf.explain().get("importance").getInfo()

    def open_water(rs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [r for r in rs if not r["ref"] or r["s2_ndvi"] < args.open_water_max_ndvi]

    # Pick the uncertainty margin on calibration data only: the widest that still
    # keeps the required coverage (same objective as the rule's calibration).
    margin = None
    for m in sorted(float(x) for x in args.margins.split(",")):
        res = fm.evaluate(calib, fm.make_rf_predictor(trees, m))
        if res["coverage"] >= args.min_coverage:
            margin = m
    margin = margin if margin is not None else 0.0
    # Recalibrate the v0.3 rule on the same calibration squares for a fair comparison.
    rule_params, _ = fm.calibrate(open_water(calib), min_coverage=args.min_coverage)

    models = {
        "Legacy rule (-18 dB fixed)": fm.legacy_predict,
        "v0.3 rule, calibrated (VV)": fm.make_predictor(rule_params),
        "Random forest (VV+VH)": fm.make_rf_predictor(trees, margin),
    }
    results = {
        "open_water": {n: fm.evaluate(open_water(test), f) for n, f in models.items()},
        "all_water_incl_vegetated": {n: fm.evaluate(test, f) for n, f in models.items()},
    }

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(args.out_dir, exist_ok=True)
    report = {
        "generated_utc": stamp, "rf_model_version": fm.RF_MODEL_VERSION,
        "region": {"lat": args.lat, "lon": args.lon, "radius_m": args.radius_m},
        "pairs": pairs, "samples": {"total": len(rows), "calibration": len(calib), "test": len(test)},
        "split": f"checkerboard of {BLOCK_DEG}-degree squares"
                 + ("; train on even date pairs, test on odd" if args.hold_out_dates else ""),
        "rf": {"trees": args.trees, "max_nodes": args.max_nodes, "margin": margin,
               "feature_importance": importance},
        "rule_params_same_split": rule_params.to_dict(),
        "test_results": results,
    }
    rpath = os.path.join(args.out_dir, f"flood_rf_{stamp}.json")
    with open(rpath, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    for title, key in (("OPEN WATER vs dry", "open_water"),
                       ("ALL NEW WATER (incl. flooded crops) vs dry", "all_water_incl_vegetated")):
        print(f"\n== Held-out test: {title} ==")
        print(f"{'Model':30} {'cover':>6} {'OA':>6} {'prec':>6} {'recall':>6} {'F1':>6} {'kappa':>6}")
        for name, res in results[key].items():
            d = res["decided"]
            print(f"{name:30} {res['coverage']:6.3f} {d['overall_accuracy']:6.3f} "
                  f"{d['precision_flood'] or 0:6.3f} {d['recall_flood'] or 0:6.3f} "
                  f"{d['f1_flood'] or 0:6.3f} {d['kappa'] or 0:6.3f}")
    print(f"\nRF margin {margin}; feature importance: {importance}")
    print(f"Saved {rpath}")

    if args.write_model:
        rf_ow = results["open_water"]["Random forest (VV+VH)"]["decided"]["f1_flood"] or 0
        rule_ow = results["open_water"]["v0.3 rule, calibrated (VV)"]["decided"]["f1_flood"] or 0
        if rf_ow <= rule_ow:
            print(f"Not writing model: RF open-water F1 {rf_ow} does not beat the rule ({rule_ow}).")
            return 0
        rf_res = results["open_water"]["Random forest (VV+VH)"]
        rf_all = results["all_water_incl_vegetated"]["Random forest (VV+VH)"]
        model = {
            "model_version": fm.RF_MODEL_VERSION, "features": fm.RF_FEATURES,
            "margin": margin, "trained_utc": stamp, "validation_report": rpath.replace(os.sep, "/"),
            "reference": "Sentinel-2 open-water MNDWI proxy (not field survey)",
            "region": report["region"], "pairs": len(fcs),
            "test_samples": rf_res["samples"], "test_coverage": rf_res["coverage"],
            "test_overall_accuracy": rf_res["decided"]["overall_accuracy"],
            "test_f1_flood": rf_res["decided"]["f1_flood"], "test_kappa": rf_res["decided"]["kappa"],
            "test_f1_flood_including_vegetated_water": rf_all["decided"]["f1_flood"],
            "trees": tree_text,
        }
        with open(fm.RF_MODEL_PATH, "w", encoding="utf-8") as fh:
            json.dump(model, fh, indent=2)
        print(f"Wrote {fm.RF_MODEL_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
