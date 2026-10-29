"""Standalone Google Earth Engine Sentinel-1 Flood Analysis Script for Ghatal.

Queries the official `COPERNICUS/S1_GRD` collection over Ghatal, Paschim Medinipur
(22.6654 N, 87.7218 E) to:
1. List all available Sentinel-1 IW VV scenes during the August 2024 pre-flood
   baseline and the September 2024 flood (targeting the Copernicus-catalogued
   pass S1A_IW_GRDH_1SDV_20240919T121250_20240919T121315_055734_06CEC2_FD14 on
   2024-09-19T12:12:50.332521Z, Ascending, Relative Orbit 12).
2. Compute before-and-after VV backscatter (dB) and the flood inundation mask.
3. Download a real PNG thumbnail of the flood mask directly from Earth Engine
   when `GEE_PROJECT_ID` is set and authenticated.

Usage:
    $env:GEE_PROJECT_ID="your-gcp-project-id"
    python scripts/run_ghatal_s1_flood_analysis.py
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
import urllib.request

try:
    import ee
except ImportError:
    print("ERROR: earthengine-api is not installed. Run: pip install earthengine-api")
    sys.exit(1)

GHATAL_LAT = 22.6654
GHATAL_LON = 87.7218


def main() -> int:
    project_id = os.environ.get("GEE_PROJECT_ID", "").strip()
    service_account = os.environ.get("GEE_SERVICE_ACCOUNT", "").strip()
    key_json_path = os.environ.get("GEE_PRIVATE_KEY_JSON", "").strip()

    if not project_id:
        print(
            "ERROR: GEE_PROJECT_ID environment variable is not set.\n"
            "To run live Sentinel-1 flood analysis for Ghatal:\n"
            "  1. Register a Cloud Project at https://code.earthengine.google.com/register\n"
            "  2. Run `earthengine authenticate` or set GEE_SERVICE_ACCOUNT & GEE_PRIVATE_KEY_JSON\n"
            "  3. Set $env:GEE_PROJECT_ID='your-project-id' and re-run this script."
        )
        return 1

    if service_account and key_json_path and os.path.exists(key_json_path):
        credentials = ee.ServiceAccountCredentials(service_account, key_json_path)
        ee.Initialize(credentials=credentials, project=project_id)
    else:
        ee.Initialize(project=project_id)

    point = ee.Geometry.Point([GHATAL_LON, GHATAL_LAT])
    aoi = point.buffer(5000).bounds()

    s1_col = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(point)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .select("VV")
    )

    baseline_col = s1_col.filterDate("2024-08-01", "2024-08-31")
    flood_col = s1_col.filterDate("2024-09-10", "2024-09-28").sort("system:time_start")

    flood_ids = flood_col.aggregate_array("system:index").getInfo()
    flood_times = flood_col.aggregate_array("system:time_start").getInfo()

    print("=== Sentinel-1 IW VV Passes over Ghatal (Sept 10–28, 2024) ===")
    scenes = []
    for sid, t_ms in zip(flood_ids, flood_times):
        dt_str = datetime.datetime.fromtimestamp(
            t_ms / 1000.0, tz=datetime.timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        scenes.append({"scene_id": f"COPERNICUS/S1_GRD/{sid}", "acquisition_utc": dt_str})
        print(f"  - {dt_str} | COPERNICUS/S1_GRD/{sid}")

    if not scenes:
        print("No Sentinel-1 scenes found in the specified window.")
        return 1

    # Select the 2024-09-19 flood image (Relative Orbit 12, Ascending) and same-orbit baseline
    same_orbit = s1_col.filter(
        ee.Filter.eq("orbitProperties_pass", "ASCENDING")
    ).filter(ee.Filter.eq("relativeOrbitNumber_start", 12))
    base_img = same_orbit.filterDate("2024-08-01", "2024-09-10").median().clip(aoi)
    flood_img = ee.Image(
        same_orbit.filterDate("2024-09-19", "2024-09-20").first()
    ).clip(aoi)

    # Water mask: VV < -18 dB during flood and VV > -14 dB during pre-flood baseline
    flood_water = flood_img.lt(-18.0).And(base_img.gt(-14.0))

    stats = flood_img.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=aoi,
        scale=10,
        maxPixels=1e8,
    ).getInfo()
    inund_stats = flood_water.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=aoi,
        scale=10,
        maxPixels=1e8,
    ).getInfo()

    os.makedirs("artifacts", exist_ok=True)
    rgb_vis = ee.Image.cat(
        [
            base_img.unitScale(-25, -5).multiply(255).toByte(),
            flood_img.unitScale(-25, -5).multiply(255).toByte(),
            flood_water.multiply(255).toByte(),
        ]
    )
    thumb_url = rgb_vis.getThumbURL(
        {"region": aoi, "dimensions": 640, "format": "png"}
    )
    out_png = os.path.join("artifacts", "live_s1_ghatal_202409.png")
    urllib.request.urlretrieve(thumb_url, out_png)

    with open(out_png, "rb") as f:
        sha256_hex = hashlib.sha256(f.read()).hexdigest()

    metadata = {
        "event": "September 2024 flood (Ghatal, Paschim Medinipur)",
        "coordinates": f"{GHATAL_LAT} N, {GHATAL_LON} E",
        "provenance": "live_sentinel",
        "scenes_found": scenes,
        "mean_vv_db": round(float(stats.get("VV", 0.0)), 2),
        "inundated_fraction_pct": round(float(inund_stats.get("VV", 0.0)) * 100.0, 2),
        "output_png": out_png,
        "output_integrity_seal_sha256": sha256_hex,
    }
    meta_path = os.path.join("artifacts", "live_s1_ghatal_202409_meta.json")
    with open(meta_path, "w", encoding="utf-8") as mf:
        json.dump(metadata, mf, indent=2)

    print(f"\nSaved live Sentinel-1 flood mask to: {out_png}")
    print(f"Saved scene metadata to: {meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
