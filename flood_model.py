"""Pramaana Sentinel-1 flood model (v0.3) with measurable accuracy.

The earlier rule (VV < -18 dB on the flood date and baseline VV > -14 dB) used a
fixed, project-chosen threshold and had never been checked against any reference.
This module replaces it with a model whose parameters can be calibrated and whose
accuracy can be measured on held-out data (see scripts/validate_flood_model.py):

1. Scene-adaptive threshold: Otsu's method on the post-event VV histogram of the
   surrounding area, accepted only when the histogram is clearly bimodal and the
   value lies within physically plausible bounds; otherwise the default/calibrated
   fixed threshold is used. The method used is always reported.
2. Change detection: a pixel is new flood only if it is dark now, was NOT dark in
   the same-orbit baseline, and dropped by at least `change_db`.
3. Exclusions: permanent water (JRC Global Surface Water occurrence), and terrain
   where flooding is hydrologically implausible or radar shadow is likely
   (MERIT Hydro height-above-nearest-drainage, SRTM slope).
4. Abstention: pixels near the threshold, or dark but with too little change, are
   'uncertain' and never counted as flood.

Everything that decides a class is implemented twice: in pure Python
(`classify_pixel`, used for calibration and tests) and as an Earth Engine image
(`ee_classify`). Both must stay in step.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

FLOOD_MODEL_VERSION = "pramaana-flood-0.3.0"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CALIBRATION_PATH = os.path.join(BASE_DIR, "data", "flood_model_calibration.json")

# Class codes used by the Earth Engine classification image.
CLASS_CODES = {
    "not_flood": 0,
    "flood": 1,
    "uncertain": 2,
    "permanent_water": 3,
    "excluded": 4,
}

ANCILLARY_DATASETS = {
    "permanent_water": "JRC/GSW1_4/GlobalSurfaceWater (occurrence)",
    "hand": "MERIT/Hydro/v1_0_1 (hnd)",
    "slope": "USGS/SRTMGL1_003 (ee.Terrain.slope)",
}


@dataclass(frozen=True)
class FloodModelParams:
    threshold_mode: str = "otsu"          # "otsu" (adaptive, falls back) or "fixed"
    default_threshold_db: float = -18.0   # fixed threshold / Otsu fallback
    margin_db: float = 1.5                # +/- band around threshold -> uncertain
    change_db: float = 3.0                # minimum drop vs baseline for new flood
    otsu_min_db: float = -23.0            # plausible bounds for an Otsu threshold
    otsu_max_db: float = -14.0
    otsu_min_separation_db: float = 3.0   # class means must differ by this much
    otsu_min_class_fraction: float = 0.02  # each side must hold >= 2 % of pixels
    threshold_region_m: int = 5000        # radius used to build the VV histogram
    permanent_water_occurrence: int = 80  # JRC occurrence (%) treated as permanent
    max_hand_m: float = 15.0
    max_slope_deg: float = 5.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


DEFAULT_PARAMS = FloodModelParams()


# ---------------------------------------------------------------------------
# Pixel rule (reference implementation)
# ---------------------------------------------------------------------------

def classify_pixel(
    post_db: float,
    base_db: float,
    threshold_db: float,
    margin_db: float,
    change_db: float,
    permanent_water: bool = False,
    terrain_excluded: bool = False,
) -> str:
    """Return one of: flood, not_flood, uncertain, permanent_water, excluded."""
    if terrain_excluded:
        return "excluded"
    if permanent_water:
        return "permanent_water"
    if abs(post_db - threshold_db) <= margin_db:
        return "uncertain"
    if post_db > threshold_db:
        return "not_flood"
    # Dark now (clearly below the threshold).
    if base_db <= threshold_db:
        return "not_flood"  # already dark before the event: not new water
    if post_db - base_db <= -change_db:
        return "flood"
    return "uncertain"  # dark now, was brighter, but the drop is too small to be sure


# ---------------------------------------------------------------------------
# Threshold selection
# ---------------------------------------------------------------------------

def otsu_threshold(bucket_means: Sequence[float], counts: Sequence[float]) -> Optional[Dict[str, float]]:
    """Otsu's threshold on a histogram. Returns threshold and class statistics."""
    pairs = [(float(m), float(c)) for m, c in zip(bucket_means, counts) if c and c > 0]
    if len(pairs) < 3:
        return None
    total = sum(c for _, c in pairs)
    total_sum = sum(m * c for m, c in pairs)
    best: Optional[Dict[str, float]] = None
    w0 = s0 = 0.0
    for i in range(len(pairs) - 1):
        m, c = pairs[i]
        w0 += c
        s0 += m * c
        w1 = total - w0
        if w0 <= 0 or w1 <= 0:
            continue
        mu0 = s0 / w0
        mu1 = (total_sum - s0) / w1
        between = w0 * w1 * (mu0 - mu1) ** 2
        if best is None or between > best["between"]:
            best = {
                "between": between,
                "threshold_db": (pairs[i][0] + pairs[i + 1][0]) / 2.0,
                "low_mean_db": mu0,
                "high_mean_db": mu1,
                "low_fraction": w0 / total,
            }
    return best


def choose_threshold(histogram: Optional[Dict[str, Any]], params: FloodModelParams) -> Dict[str, Any]:
    """Pick the scene threshold. `histogram` is an ee.Reducer.histogram() result."""
    fallback = {"threshold_db": params.default_threshold_db, "method": "fixed"}
    if params.threshold_mode != "otsu":
        return dict(fallback, reason="Fixed threshold configured.")
    if not histogram or not histogram.get("histogram"):
        return dict(fallback, reason="No histogram available; used fixed threshold.")
    res = otsu_threshold(histogram.get("bucketMeans") or [], histogram["histogram"])
    if res is None:
        return dict(fallback, reason="Histogram too small for Otsu; used fixed threshold.")
    thr = res["threshold_db"]
    sep = res["high_mean_db"] - res["low_mean_db"]
    frac = res["low_fraction"]
    if not params.otsu_min_db <= thr <= params.otsu_max_db:
        reason = f"Otsu value {thr:.1f} dB outside plausible range; used fixed threshold."
    elif sep < params.otsu_min_separation_db:
        reason = f"Histogram not bimodal (class separation {sep:.1f} dB); used fixed threshold."
    elif not params.otsu_min_class_fraction <= frac <= 1 - params.otsu_min_class_fraction:
        reason = f"Too little dark area ({frac:.1%}) for Otsu; used fixed threshold."
    else:
        return {"threshold_db": round(thr, 2), "method": "otsu",
                "reason": f"Otsu on local VV histogram (class separation {sep:.1f} dB, "
                          f"{frac:.1%} dark)."}
    return dict(fallback, reason=reason)


# ---------------------------------------------------------------------------
# Accuracy metrics
# ---------------------------------------------------------------------------

def binary_metrics(tp: int, fp: int, fn: int, tn: int) -> Dict[str, Optional[float]]:
    n = tp + fp + fn + tn

    def ratio(a: float, b: float) -> Optional[float]:
        return round(a / b, 4) if b else None

    oa = ratio(tp + tn, n)
    expected = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (n * n) if n else None
    kappa = None
    if n and expected is not None and expected < 1:
        kappa = round(((tp + tn) / n - expected) / (1 - expected), 4)
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    f1 = ratio(2 * tp, 2 * tp + fp + fn)
    return {
        "n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "overall_accuracy": oa,
        "precision_flood": precision,
        "recall_flood": recall,
        "f1_flood": f1,
        "iou_flood": ratio(tp, tp + fp + fn),
        "specificity": ratio(tn, tn + fp),
        "kappa": kappa,
    }


def evaluate(samples: Iterable[Dict[str, Any]], predict) -> Dict[str, Any]:
    """Score `predict(sample) -> class name` against sample['ref'] (1 water, 0 dry).

    flood -> positive; not_flood / permanent_water -> negative; uncertain and
    excluded -> abstain. Reports metrics on decided pixels plus coverage, and the
    worst case where every abstention is counted as an error.
    """
    tp = fp = fn = tn = abst_pos = abst_neg = 0
    for s in samples:
        cls = predict(s)
        ref = int(s["ref"])
        if cls in ("uncertain", "excluded"):
            if ref:
                abst_pos += 1
            else:
                abst_neg += 1
        elif cls == "flood":
            tp += ref
            fp += 1 - ref
        else:
            fn += ref
            tn += 1 - ref
    decided = binary_metrics(tp, fp, fn, tn)
    total = decided["n"] + abst_pos + abst_neg
    worst = binary_metrics(tp, fp + abst_neg, fn + abst_pos, tn)
    return {
        "samples": total,
        "reference_water": tp + fn + abst_pos,
        "reference_dry": fp + tn + abst_neg,
        "coverage": round(decided["n"] / total, 4) if total else None,
        "decided": decided,
        "abstentions_as_errors": worst,
    }


def legacy_predict(s: Dict[str, Any]) -> str:
    """The pre-v0.3 rule (gee_fetcher.classify_backscatter) for comparison."""
    if abs(s["post"] - (-18.0)) <= 1.5:
        return "uncertain"
    if s["post"] < -19.5 and s["base"] > -14.0:
        return "flood"
    return "not_flood"


def make_predictor(params: FloodModelParams):
    """Predictor for samples carrying post, base, jrc, hand, slope and an Otsu threshold."""

    def predict(s: Dict[str, Any]) -> str:
        if params.threshold_mode == "otsu" and s.get("otsu_threshold_db") is not None:
            thr = s["otsu_threshold_db"]
        else:
            thr = params.default_threshold_db
        return classify_pixel(
            s["post"], s["base"], thr, params.margin_db, params.change_db,
            permanent_water=(s.get("jrc") or 0) >= params.permanent_water_occurrence,
            terrain_excluded=is_terrain_excluded(s, params),
        )

    return predict


def is_terrain_excluded(s: Dict[str, Any], params: FloodModelParams) -> bool:
    hand = s.get("hand")
    slope = s.get("slope")
    return bool((hand is not None and hand > params.max_hand_m)
                or (slope is not None and slope > params.max_slope_deg))


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def _frange(start: float, stop: float, step: float) -> List[float]:
    n = int(round((stop - start) / step))
    return [round(start + i * step, 3) for i in range(n + 1)]


CALIBRATION_GRID = {
    "threshold_mode": ["otsu", "fixed"],
    "default_threshold_db": _frange(-24.0, -10.0, 0.5),
    "margin_db": [0.0, 0.5, 1.0, 1.5],
    "change_db": _frange(0.0, 6.0, 0.5),
}


def calibrate(
    samples: Sequence[Dict[str, Any]],
    base: FloodModelParams = DEFAULT_PARAMS,
    min_coverage: float = 0.85,
    grid: Optional[Dict[str, List[Any]]] = None,
) -> Tuple[FloodModelParams, Dict[str, Any]]:
    """Grid-search parameters that maximise flood F1 on `samples`, keeping coverage.

    Only pass CALIBRATION samples here; report accuracy on a separate test split.
    In "otsu" mode default_threshold_db only matters as the fallback.
    """
    g = grid or CALIBRATION_GRID
    best: Optional[Tuple[Tuple[float, float], FloodModelParams, Dict[str, Any]]] = None
    for mode in g["threshold_mode"]:
        thresholds = g["default_threshold_db"]
        if mode == "otsu" and all(s.get("otsu_threshold_db") is not None for s in samples):
            thresholds = [base.default_threshold_db]  # fallback never used; skip the sweep
        for thr in thresholds:
            for margin in g["margin_db"]:
                for change in g["change_db"]:
                    p = replace(base, threshold_mode=mode, default_threshold_db=thr,
                                margin_db=margin, change_db=change)
                    res = evaluate(samples, make_predictor(p))
                    if res["coverage"] is None or res["coverage"] < min_coverage:
                        continue
                    f1 = res["decided"]["f1_flood"] or 0.0
                    # tie-break: prefer higher coverage
                    key = (round(f1, 4), res["coverage"])
                    if best is None or key > best[0]:
                        best = (key, p, res)
    if best is None:
        raise ValueError(f"No parameter set reached coverage {min_coverage:.0%} on the calibration data.")
    return best[1], best[2]


def spatial_block_split(samples: Sequence[Dict[str, Any]], block_deg: float = 0.02,
                        seed: int = 42) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split samples into calibration/test by ~2 km map blocks.

    Neighbouring pixels are strongly correlated, so a random pixel split would
    overstate accuracy. Whole blocks go to one side, across all dates.
    """
    calib: List[Dict[str, Any]] = []
    test: List[Dict[str, Any]] = []
    for s in samples:
        key = f"{seed}:{math.floor(s['lon'] / block_deg)}:{math.floor(s['lat'] / block_deg)}"
        (test if hashlib.sha256(key.encode()).digest()[0] % 2 else calib).append(s)
    return calib, test


# ---------------------------------------------------------------------------
# Calibration file
# ---------------------------------------------------------------------------

def load_calibration(path: str = CALIBRATION_PATH) -> Tuple[FloodModelParams, Optional[Dict[str, Any]]]:
    """Return calibrated params if a calibration file exists, else defaults."""
    if not os.path.exists(path):
        return DEFAULT_PARAMS, None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("model_version") != FLOOD_MODEL_VERSION:
            return DEFAULT_PARAMS, None  # calibrated for a different rule; do not reuse
        known = set(FloodModelParams.__dataclass_fields__)
        params = replace(DEFAULT_PARAMS, **{k: v for k, v in data["params"].items() if k in known})
        return params, {k: v for k, v in data.items() if k != "params"}
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_PARAMS, None


# ---------------------------------------------------------------------------
# Earth Engine implementation
# ---------------------------------------------------------------------------

def ee_ancillary(ee: Any) -> Dict[str, Any]:
    """Permanent-water occurrence, HAND and slope images (unmasked where missing)."""
    jrc = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").unmask(0).rename("jrc")
    hand = ee.Image("MERIT/Hydro/v1_0_1").select("hnd").unmask(0).rename("hand")
    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003")).unmask(0).rename("slope")
    return {"jrc": jrc, "hand": hand, "slope": slope}


def ee_histogram(ee: Any, post_vv: Any, region: Any) -> Any:
    """Server-side histogram of post-event VV (dB) for choose_threshold()."""
    return post_vv.rename("post").reduceRegion(
        reducer=ee.Reducer.histogram(255, 0.1),
        geometry=region, scale=30, maxPixels=1e9, bestEffort=True,
    ).get("post")


def ee_classify(ee: Any, post_vv: Any, base_vv: Any, threshold_db: float,
                params: FloodModelParams, anc: Optional[Dict[str, Any]] = None) -> Any:
    """Classification image (band 'class', codes in CLASS_CODES). Mirrors classify_pixel."""
    anc = anc or ee_ancillary(ee)
    thr, m = threshold_db, params.margin_db
    dark = post_vv.lt(thr - m)
    near = post_vv.subtract(thr).abs().lte(m)
    was_bright = base_vv.gt(thr)
    big_drop = post_vv.subtract(base_vv).lte(-params.change_db)
    terrain = anc["hand"].gt(params.max_hand_m).Or(anc["slope"].gt(params.max_slope_deg))
    permanent = anc["jrc"].gte(params.permanent_water_occurrence)
    cls = (ee.Image.constant(CLASS_CODES["not_flood"])
           .where(dark.And(was_bright).And(big_drop), CLASS_CODES["flood"])
           .where(dark.And(was_bright).And(big_drop.Not()), CLASS_CODES["uncertain"])
           .where(near, CLASS_CODES["uncertain"])
           .where(permanent, CLASS_CODES["permanent_water"])
           .where(terrain, CLASS_CODES["excluded"]))
    return cls.updateMask(post_vv.mask().And(base_vv.mask())).rename("class").toByte()


def ee_class_fractions(ee: Any, cls_img: Any) -> Any:
    """Image whose per-band means over a region are the class fractions."""
    return ee.Image.cat([cls_img.eq(code).rename(name) for name, code in CLASS_CODES.items()])


def model_summary(params: FloodModelParams, calibration: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What to store alongside every result so it can be audited later."""
    return {
        "version": FLOOD_MODEL_VERSION,
        "params": params.to_dict(),
        "ancillary_datasets": dict(ANCILLARY_DATASETS),
        "calibration": calibration,  # None => uncalibrated defaults
    }


# ---------------------------------------------------------------------------
# Random-forest model (VV + VH), trained by scripts/train_flood_rf.py
#
# Trees are trained in Earth Engine (ee.Classifier.smileRandomForest) and stored
# as the text that classifier.explain() returns. A rebuilt ee ensemble only votes,
# so the trees are parsed here and evaluated as averaged leaf probabilities, both
# in Python (scoring, tests) and as an Earth Engine image (the app).
# ---------------------------------------------------------------------------

RF_MODEL_VERSION = "pramaana-flood-rf-0.1.0"
RF_MODEL_PATH = os.path.join(BASE_DIR, "data", "flood_rf_model.json")
RF_FEATURES = ["vv_post", "vv_base", "vh_post", "vh_base", "vv_change", "vh_change",
               "hand", "slope", "jrc"]

_TREE_LINE = re.compile(
    r"^\s*(\d+)\)\s+(?:root|(\w+)(<=|>)(\S+))\s+\d+\s+\S+\s+\d+\s+\(([^)]*)\)(\s+\*)?\s*$")


def checkerboard_test_block(lon: float, lat: float, block_deg: float = 0.02) -> bool:
    """Spatial split used for the RF model; mirrored server-side in train_flood_rf.py."""
    return (math.floor(lon / block_deg) + math.floor(lat / block_deg)) % 2 == 1


def parse_tree(text: str) -> Dict[int, Dict[str, Any]]:
    """Parse one smile/rpart-style tree from classifier.explain()['trees']."""
    nodes: Dict[int, Dict[str, Any]] = {}
    for line in text.splitlines():
        m = _TREE_LINE.match(line)
        if not m:
            continue
        nid, feat, op, val, probs, leaf = m.groups()
        p = [float(x) for x in probs.split()]
        nodes[int(nid)] = {"feature": feat, "op": op, "value": float(val) if val else None,
                           "p_flood": p[1] if len(p) > 1 else 0.0, "leaf": bool(leaf)}
    if 1 not in nodes:
        raise ValueError("Tree text has no root node.")
    return nodes


def _goes_left(node: Dict[str, Any], x: float) -> bool:
    return x <= node["value"] if node["op"] == "<=" else x > node["value"]


def tree_proba(nodes: Dict[int, Dict[str, Any]], features: Dict[str, float]) -> float:
    nid = 1
    while not nodes[nid]["leaf"]:
        left = nodes[2 * nid]
        nid = 2 * nid if _goes_left(left, features[left["feature"]]) else 2 * nid + 1
    return nodes[nid]["p_flood"]


def forest_proba(trees: Sequence[Dict[int, Dict[str, Any]]], features: Dict[str, float]) -> float:
    return sum(tree_proba(t, features) for t in trees) / len(trees)


def rf_features(s: Dict[str, Any]) -> Dict[str, float]:
    """Feature dict from a sample/pixel carrying post/base VV and VH (dB)."""
    return {
        "vv_post": s["post"], "vv_base": s["base"],
        "vh_post": s["vh_post"], "vh_base": s["vh_base"],
        "vv_change": s["post"] - s["base"], "vh_change": s["vh_post"] - s["vh_base"],
        "hand": s.get("hand") or 0.0, "slope": s.get("slope") or 0.0, "jrc": s.get("jrc") or 0.0,
    }


def classify_probability(p_flood: float, margin: float, permanent_water: bool = False) -> str:
    if permanent_water:
        return "permanent_water"
    if abs(p_flood - 0.5) <= margin:
        return "uncertain"
    return "flood" if p_flood > 0.5 else "not_flood"


def make_rf_predictor(trees: Sequence[Dict[int, Dict[str, Any]]], margin: float,
                      permanent_occurrence: int = DEFAULT_PARAMS.permanent_water_occurrence):
    def predict(s: Dict[str, Any]) -> str:
        return classify_probability(forest_proba(trees, rf_features(s)), margin,
                                    permanent_water=(s.get("jrc") or 0) >= permanent_occurrence)
    return predict


def load_rf_model(path: str = RF_MODEL_PATH) -> Optional[Dict[str, Any]]:
    """Return {'trees': parsed, 'meta': ...} or None if absent/invalid/stale."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("model_version") != RF_MODEL_VERSION or data.get("features") != RF_FEATURES:
            return None
        trees = [parse_tree(t) for t in data["trees"]]
        return {"trees": trees, "meta": {k: v for k, v in data.items() if k != "trees"}}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def ee_rf_features(ee: Any, vv_post: Any, vv_base: Any, vh_post: Any, vh_base: Any,
                   anc: Optional[Dict[str, Any]] = None) -> Any:
    anc = anc or ee_ancillary(ee)
    return ee.Image.cat([
        vv_post.rename("vv_post"), vv_base.rename("vv_base"),
        vh_post.rename("vh_post"), vh_base.rename("vh_base"),
        vv_post.subtract(vv_base).rename("vv_change"), vh_post.subtract(vh_base).rename("vh_change"),
        anc["hand"], anc["slope"], anc["jrc"],
    ])


def ee_tree_image(ee: Any, nodes: Dict[int, Dict[str, Any]], feats: Any, nid: int = 1) -> Any:
    node = nodes[nid]
    if node["leaf"]:
        return ee.Image.constant(node["p_flood"])
    left = nodes[2 * nid]
    band = feats.select(left["feature"])
    cond = band.lte(left["value"]) if left["op"] == "<=" else band.gt(left["value"])
    return ee_tree_image(ee, nodes, feats, 2 * nid + 1).where(cond, ee_tree_image(ee, nodes, feats, 2 * nid))


def ee_rf_classify(ee: Any, feats: Any, trees: Sequence[Dict[int, Dict[str, Any]]], margin: float,
                   permanent_occurrence: int = DEFAULT_PARAMS.permanent_water_occurrence) -> Any:
    """Classification image (band 'class', CLASS_CODES). Mirrors make_rf_predictor."""
    prob = ee.Image.cat([ee_tree_image(ee, t, feats) for t in trees]).reduce(ee.Reducer.mean())
    cls = (ee.Image.constant(CLASS_CODES["not_flood"])
           .where(prob.gt(0.5 + margin), CLASS_CODES["flood"])
           .where(prob.subtract(0.5).abs().lte(margin), CLASS_CODES["uncertain"])
           .where(feats.select("jrc").gte(permanent_occurrence), CLASS_CODES["permanent_water"]))
    return cls.updateMask(feats.select("vv_post").mask().And(feats.select("vh_post").mask())
                          .And(feats.select("vv_base").mask())).rename("class").toByte()
