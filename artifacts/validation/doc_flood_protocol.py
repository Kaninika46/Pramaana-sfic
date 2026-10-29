"""Step 1 of the documented-flood check: freeze settings, points, dates and criteria.

Uses only terrain / land-cover / archive metadata. No flood model is run here.
Writes artifacts/validation/documented_floods_protocol.json before any measurement.
"""
import datetime
import hashlib
import json
import os
import sys

ROOT = r"C:\Users\KANINIKA\OneDrive\Desktop\pramaan-sfic"
sys.path.insert(0, ROOT)
import ee  # noqa: E402

ee.Initialize(project="premium-cipher-513114-e0")


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


hand = ee.Image("MERIT/Hydro/v1_0_1").select("hnd")
jrc = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence").unmask(0)
slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003"))
cropland = ee.ImageCollection("ESA/WorldCover/v200").first().eq(40)  # WorldCover class 40 = cropland
base_ok = cropland.And(jrc.eq(0)).And(slope.lt(2))


def pick(mask, box, n, seed):
    fc = (mask.selfMask().rename("ok").addBands(hand.rename("hand"))
          .sample(region=ee.Geometry.Rectangle(box), scale=30, numPixels=5000, seed=seed, geometries=True)
          .limit(200).randomColumn("r", seed).sort("r"))
    feats = fc.getInfo()["features"]
    chosen = []
    for f in feats:  # keep points >= 1 km apart so they are not near-duplicates
        lon, lat = f["geometry"]["coordinates"]
        if all(((lon - c["lon"]) * 103) ** 2 + ((lat - c["lat"]) * 111) ** 2 >= 1 for c in chosen):
            chosen.append({"lon": round(lon, 5), "lat": round(lat, 5), "hand_m": round(f["properties"]["hand"], 1)})
        if len(chosen) == n:
            break
    return chosen


flood_zone = pick(base_ok.And(hand.lte(2)), [87.65, 22.55, 87.80, 22.72], 6, 101)
high_ground = pick(base_ok.And(hand.gte(10)), [87.45, 22.68, 87.60, 22.87], 4, 202)
points = ([dict(p, id=f"FZ{i+1}", group="flood_zone") for i, p in enumerate(flood_zone)]
          + [dict(p, id=f"HG{i+1}", group="high_ground") for i, p in enumerate(high_ground)])

# Dry-year dates: first Sentinel-1 IW pass over Ghatal on or after 1 September (rule fixed in advance).
pt = ee.Geometry.Point([87.7218, 22.6654])
s1 = ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(pt).filter(ee.Filter.eq("instrumentMode", "IW"))
dry = []
for year in (2018, 2019, 2020, 2022):
    first = ee.Image(s1.filterDate(f"{year}-09-01", f"{year}-10-01").sort("system:time_start").first())
    t = first.get("system:time_start").getInfo()
    dry.append({"date": datetime.datetime.fromtimestamp(t / 1000, tz=datetime.timezone.utc).date().isoformat(),
                "year": year, "kind": "dry", "source": "paper p.8: gauges below danger level; maps show negligible flooding"})

flood = [{"date": d, "kind": "flood", "source": "paper Table 1" + note} for d, note in (
    ("2016-08-23", ""), ("2017-07-25", ""), ("2021-07-28", ""), ("2021-08-06", ""), ("2023-10-07", ""),
    ("2024-09-19", " lists 18-09-2024; archive has no pass on 17-18 Sep, nearest is 19 Sep 12:12 UTC"))]

protocol = {
    "written_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "purpose": "Check the app's flood model against floods documented in Ahammad et al. 2026 "
               "(J. Indian Soc. Remote Sens. 54:2983-2998). Read-only: no app code or model change.",
    "frozen_model_files": {
        "data/flood_rf_model.json": sha(os.path.join(ROOT, "data", "flood_rf_model.json")),
        "data/flood_model_calibration.json": sha(os.path.join(ROOT, "data", "flood_model_calibration.json")),
        "flood_model.py": sha(os.path.join(ROOT, "flood_model.py")),
        "gee_fetcher.py": sha(os.path.join(ROOT, "gee_fetcher.py")),
    },
    "method": "For each point and date, run gee_fetcher._analyze_sentinel1 (the app's own Sentinel-1 path, "
              "250 m radius around the point, incident date = pass date). Read flood_model.fractions_pct.",
    "point_rule": {
        "flood_zone": "ESA WorldCover cropland, JRC occurrence 0, slope < 2 deg, MERIT HAND <= 2 m, "
                      "box 87.65-87.80 E, 22.55-22.72 N (central Ghatal / Daspur-I, named as repeatedly "
                      "flooded in the paper), seed 101, >= 1 km apart, first 6.",
        "high_ground": "Same, but HAND >= 10 m, box 87.45-87.60 E, 22.68-22.87 N (Chandrakona-II uplands), "
                       "seed 202, first 4.",
        "note": "Paper's named villages (Table 4) could not be geocoded reliably, so a terrain rule is used.",
    },
    "dry_date_rule": "First Sentinel-1 IW pass over Ghatal (87.7218 E, 22.6654 N) on or after 1 September.",
    "points": points,
    "dates": flood + dry,
    "decision_rule": "A point-date counts as 'flood detected' when flood >= 20 % of its 250 m area.",
    "pass_criteria": {
        "C1_detection": "Flood dates in 2017, 2021, 2023, 2024 (paper Table 7: >= 66 km2 flooded): "
                        "flood detected at >= 50 % of flood-zone point-dates.",
        "C2_dry_false_alarms": "Dry-year dates: flood NOT detected at >= 90 % of all point-dates.",
        "C3_high_ground": "Flood dates: flood NOT detected at >= 80 % of high-ground point-dates.",
        "reported_without_criterion": "2016 (paper: small event, 38-39 km2 of 962 km2); uncertain shares; "
                                      "errors / no-data counted and listed, never dropped.",
    },
    "fixed_in_advance": "Thresholds, model files, points, dates and criteria above are not changed after results.",
}
out = os.path.join(ROOT, "artifacts", "validation", "documented_floods_protocol.json")
with open(out, "w", encoding="utf-8") as fh:
    json.dump(protocol, fh, indent=2)
print(json.dumps({"points": points, "dates": [d["date"] for d in flood + dry]}, indent=1))
print("wrote", out)
