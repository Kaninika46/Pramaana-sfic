import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flood_model as fm  # noqa: E402


def synthetic_samples(n=400, seed=1, otsu=None):
    """Water: dark now, bright before. Dry: bright both times. Plus noise."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        ref = i % 2
        base = rng.gauss(-11.0, 1.5)
        post = rng.gauss(-22.0, 1.5) if ref else rng.gauss(-12.0, 2.0)
        out.append({"lon": 87.6 + rng.random() * 0.3, "lat": 22.5 + rng.random() * 0.3,
                    "post": post, "base": base, "jrc": 0, "hand": 2.0, "slope": 0.5,
                    "ref": ref, "otsu_threshold_db": otsu})
    return out


class ClassifyPixelTests(unittest.TestCase):
    def test_rules(self):
        c = lambda post, base, **kw: fm.classify_pixel(post, base, -18.0, 1.0, 3.0, **kw)  # noqa: E731
        self.assertEqual(c(-23, -11), "flood")
        self.assertEqual(c(-12, -11), "not_flood")
        self.assertEqual(c(-18.5, -11), "uncertain")          # within margin
        self.assertEqual(c(-23, -20), "not_flood")            # dark before: not new water
        self.assertEqual(c(-19.5, -17.5), "uncertain")        # dark, but only 2 dB drop
        self.assertEqual(c(-23, -11, permanent_water=True), "permanent_water")
        self.assertEqual(c(-23, -11, terrain_excluded=True), "excluded")


class ThresholdTests(unittest.TestCase):
    def bimodal(self, low_mu=-22.0, high_mu=-11.0, low_n=300, high_n=700):
        means = [x / 2 for x in range(-60, 0)]  # -30 .. -0.5 dB
        counts = [low_n * pow(2.718, -((m - low_mu) ** 2) / 2) + high_n * pow(2.718, -((m - high_mu) ** 2) / 2)
                  for m in means]
        return {"bucketMeans": means, "histogram": counts}

    def test_otsu_finds_valley(self):
        choice = fm.choose_threshold(self.bimodal(), fm.DEFAULT_PARAMS)
        self.assertEqual(choice["method"], "otsu")
        self.assertTrue(-19.5 < choice["threshold_db"] < -14.0, choice)

    def test_unimodal_falls_back(self):
        choice = fm.choose_threshold(self.bimodal(low_n=0), fm.DEFAULT_PARAMS)
        self.assertEqual(choice["method"], "fixed")
        self.assertEqual(choice["threshold_db"], -18.0)

    def test_missing_histogram_and_fixed_mode(self):
        self.assertEqual(fm.choose_threshold(None, fm.DEFAULT_PARAMS)["method"], "fixed")
        p = fm.FloodModelParams(threshold_mode="fixed", default_threshold_db=-19.0)
        self.assertEqual(fm.choose_threshold(self.bimodal(), p)["threshold_db"], -19.0)


class MetricsTests(unittest.TestCase):
    def test_binary_metrics(self):
        m = fm.binary_metrics(tp=40, fp=10, fn=10, tn=40)
        self.assertEqual(m["overall_accuracy"], 0.8)
        self.assertEqual(m["precision_flood"], 0.8)
        self.assertEqual(m["recall_flood"], 0.8)
        self.assertEqual(m["f1_flood"], 0.8)
        self.assertEqual(m["kappa"], 0.6)
        self.assertIsNone(fm.binary_metrics(0, 0, 0, 0)["overall_accuracy"])

    def test_abstentions_tracked(self):
        samples = [{"ref": 1}, {"ref": 0}, {"ref": 1}]
        preds = iter(["flood", "not_flood", "uncertain"])
        res = fm.evaluate(samples, lambda s: next(preds))
        self.assertAlmostEqual(res["coverage"], 0.6667, places=3)
        self.assertEqual(res["decided"]["f1_flood"], 1.0)
        self.assertLess(res["abstentions_as_errors"]["f1_flood"], 1.0)


class CalibrationTests(unittest.TestCase):
    GRID = {"threshold_mode": ["fixed"], "default_threshold_db": [-24.0, -20.0, -17.0, -15.0],
            "margin_db": [0.0, 1.0], "change_db": [0.0, 3.0]}

    def test_calibration_beats_bad_default(self):
        samples = synthetic_samples()
        bad = fm.FloodModelParams(threshold_mode="fixed", default_threshold_db=-24.0)
        params, _ = fm.calibrate(samples, base=bad, grid=self.GRID)
        f1_bad = fm.evaluate(samples, fm.make_predictor(bad))["decided"]["f1_flood"]
        f1_cal = fm.evaluate(samples, fm.make_predictor(params))["decided"]["f1_flood"]
        self.assertGreater(f1_cal, 0.95)
        self.assertGreater(f1_cal, f1_bad)

    def test_coverage_constraint(self):
        with self.assertRaises(ValueError):
            fm.calibrate(synthetic_samples(), min_coverage=1.01, grid=self.GRID)

    def test_spatial_split_is_disjoint_and_deterministic(self):
        samples = synthetic_samples()
        a1, b1 = fm.spatial_block_split(samples)
        a2, b2 = fm.spatial_block_split(samples)
        self.assertEqual(len(a1) + len(b1), len(samples))
        self.assertEqual([id(s) for s in a1], [id(s) for s in a2])
        block = lambda s: (int(s["lon"] // 0.02), int(s["lat"] // 0.02))  # noqa: E731
        self.assertFalse({block(s) for s in a1} & {block(s) for s in b1})


class CalibrationFileTests(unittest.TestCase):
    def test_missing_wrong_version_and_valid(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cal.json")
            self.assertEqual(fm.load_calibration(path), (fm.DEFAULT_PARAMS, None))
            with open(path, "w") as fh:
                json.dump({"model_version": "old", "params": {"margin_db": 0.5}}, fh)
            self.assertEqual(fm.load_calibration(path)[1], None)
            with open(path, "w") as fh:
                json.dump({"model_version": fm.FLOOD_MODEL_VERSION, "test_f1_flood": 0.9,
                           "params": {"margin_db": 0.5, "unknown_key": 1}}, fh)
            params, meta = fm.load_calibration(path)
            self.assertEqual(params.margin_db, 0.5)
            self.assertEqual(meta["test_f1_flood"], 0.9)


TREE = """n= 200
node), split, n, loss, yval, (yprob)
* denotes terminal node
1) root 200 100.00 0 (0.50000 0.50000)
 2) vv_change<=-2.5 90 10.000 1 (0.10000 0.90000)
   4) vh_post<=-24 60 0.0000 1 (0.02000 0.98000) *
   5) vh_post>-24 30 9.0000 1 (0.30000 0.70000) *
 3) vv_change>-2.5 110 5.0000 0 (0.95000 0.05000) *
"""


def rf_sample(post, base, vh_post=-20.0, vh_base=-15.0, jrc=0):
    return {"post": post, "base": base, "vh_post": vh_post, "vh_base": vh_base,
            "jrc": jrc, "hand": 1.0, "slope": 0.5}


class RandomForestTests(unittest.TestCase):
    def test_parse_and_predict(self):
        tree = fm.parse_tree(TREE)
        self.assertTrue(tree[4]["leaf"] and not tree[2]["leaf"])
        f = lambda s: fm.forest_proba([tree], fm.rf_features(s))  # noqa: E731
        self.assertAlmostEqual(f(rf_sample(-20, -12, vh_post=-26)), 0.98)
        self.assertAlmostEqual(f(rf_sample(-20, -12, vh_post=-20)), 0.70)
        self.assertAlmostEqual(f(rf_sample(-12, -12)), 0.05)
        self.assertAlmostEqual(fm.forest_proba([tree, tree], fm.rf_features(rf_sample(-12, -12))), 0.05)

    def test_probability_classes(self):
        pred = fm.make_rf_predictor([fm.parse_tree(TREE)], margin=0.25)
        self.assertEqual(pred(rf_sample(-20, -12, vh_post=-26)), "flood")
        self.assertEqual(pred(rf_sample(-20, -12, vh_post=-20)), "uncertain")  # 0.70 within 0.25
        self.assertEqual(pred(rf_sample(-12, -12)), "not_flood")
        self.assertEqual(pred(rf_sample(-20, -12, jrc=95)), "permanent_water")

    def test_checkerboard_split(self):
        self.assertNotEqual(fm.checkerboard_test_block(87.701, 22.601), fm.checkerboard_test_block(87.721, 22.601))
        self.assertEqual(fm.checkerboard_test_block(87.701, 22.601), fm.checkerboard_test_block(87.721, 22.621))

    def test_load_rf_model(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rf.json")
            self.assertIsNone(fm.load_rf_model(path))
            good = {"model_version": fm.RF_MODEL_VERSION, "features": fm.RF_FEATURES,
                    "margin": 0.1, "trees": [TREE]}
            with open(path, "w") as fh:
                json.dump(good, fh)
            model = fm.load_rf_model(path)
            self.assertEqual(len(model["trees"]), 1)
            self.assertEqual(model["meta"]["margin"], 0.1)
            with open(path, "w") as fh:
                json.dump(dict(good, features=["vv_post"]), fh)
            self.assertIsNone(fm.load_rf_model(path))


if __name__ == "__main__":
    unittest.main()
