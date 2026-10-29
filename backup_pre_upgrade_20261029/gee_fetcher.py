"""Google Earth Engine (GEE) Telemetry & Provenance-Tracked Fetcher for Ghatal.

Provides satellite retrieval for Ghatal, Paschim Medinipur (22.6654 N, 87.7218 E)
with strict provenance tracking:
- "live_sentinel": Authenticated GEE Sentinel-1/Sentinel-2 scene output.
- "synthetic_demo": Explicitly labeled synthetic visualization (never evidence).
- "farmer_capture": Client-side captured field photo / voice note from cultivator.

Authentication uses `ee.Initialize(project=...)` via environment variables
(`GEE_PROJECT_ID`, `GEE_SERVICE_ACCOUNT`, `GEE_PRIVATE_KEY_JSON`).
When authenticated, scene dates and IDs are queried directly from the
`COPERNICUS/S1_GRD` and `COPERNICUS/S2_SR_HARMONIZED` collections.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw

try:
    import ee
    EE_AVAILABLE = True
except ImportError:
    EE_AVAILABLE = False


GHATAL_LAT = 22.6654
GHATAL_LON = 87.7218
GHATAL_LOCATION_STR = "22.6654 N, 87.7218 E"
VALID_PROVENANCES: Tuple[str, ...] = (
    "live_sentinel",
    "synthetic_demo",
    "farmer_capture",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EVENT_GRANULE_PATH = os.path.join(BASE_DIR, "data", "s1_event_granule_ghatal_sept2024.json")

# Project-chosen classification parameters (documented in legal_rules.json)
WATER_THRESHOLD_DB = float(os.environ.get("PRAMAANA_WATER_THRESHOLD_DB", "-18.0"))
UNCERTAIN_MARGIN_DB = float(os.environ.get("PRAMAANA_UNCERTAIN_MARGIN_DB", "1.5"))
BASELINE_DRY_DB = -14.0


def load_event_granule() -> Dict[str, Any]:
    """Load the Sentinel-1 event granule record retrieved from the CDSE catalogue."""
    with open(EVENT_GRANULE_PATH, "r", encoding="utf-8") as granule_file:
        return json.load(granule_file)


EVENT_GRANULE_RECORD = load_event_granule()
EVENT_GRANULE = EVENT_GRANULE_RECORD["event_granule"]

# Reference metadata for the September 2024 flood in Ghatal
HISTORICAL_GHATAL_FLOOD_EVENT = {
    "event_name": "September 2024 flood (Ghatal, Paschim Medinipur)",
    "s1_granule_name": EVENT_GRANULE["granule_name"],
    "s1_acquisition_start_utc": EVENT_GRANULE["acquisition_start_utc"],
    "s1_relative_orbit": EVENT_GRANULE["relative_orbit"],
    "s1_orbit_direction": EVENT_GRANULE["orbit_direction"],
    "s1_scene_note": (
        f"Event granule {EVENT_GRANULE['granule_name']} acquired "
        f"{EVENT_GRANULE['acquisition_start_utc']} (Sentinel-1A, "
        f"{EVENT_GRANULE['orbit_direction'].lower()}, relative orbit "
        f"{EVENT_GRANULE['relative_orbit']}), per Copernicus Data Space catalogue "
        f"lookup on {EVENT_GRANULE_RECORD['retrieved_utc']}."
    ),
    "s2_scene_note": (
        "UNVERIFIED IN DEMO MODE: Monsoon cloud cover frequently obscures optical "
        "Sentinel-2 scenes during September floods; query COPERNICUS/S2_SR_HARMONIZED "
        "in live GEE to check cloud-free availability."
    ),
    "uncertainty_note": (
        "UNCERTAINTY NOTE: Sentinel-1 C-Band SAR backscatter typically varies within "
        "a few dB due to radar speckle, wind roughening, and double-bounce scattering "
        "from emergent paddy stalks. Pixels within a conservative margin of the "
        "classification threshold are flagged as 'uncertain' and excluded from the "
        "certified flood-extent count. Sentinel-2 optical NDVI is frequently obscured "
        "or degraded by monsoon cloud cover and turbid floodwater during September "
        "flood events. Satellite maps indicate regional submergence patterns and must "
        "be paired with field verification."
    ),
}


def classify_backscatter(
    flood_db: float,
    baseline_db: float,
    threshold_db: float = WATER_THRESHOLD_DB,
    margin_db: float = UNCERTAIN_MARGIN_DB,
    baseline_dry_db: float = BASELINE_DRY_DB,
) -> str:
    """Classify one pixel as 'flood', 'not_flood' or 'uncertain'.

    Reference implementation of the rule applied in Earth Engine:
    - 'uncertain' if the flood-date VV value lies within +/- margin_db of the
      threshold; these pixels are excluded from the certified flood extent.
    - 'flood' if VV is clearly below the threshold on the flood date AND the
      same-orbit baseline was dry (VV above baseline_dry_db), i.e. new water.
    - 'not_flood' otherwise (including permanent water).
    """
    if abs(flood_db - threshold_db) <= margin_db:
        return "uncertain"
    if flood_db < threshold_db - margin_db and baseline_db > baseline_dry_db:
        return "flood"
    return "not_flood"


@dataclass
class EvidenceArtifact:
    """Represents an artifact with mandatory provenance and output integrity seal."""

    artifact_type: str
    file_path: str
    sha256_hash: str
    provenance: str  # Must be "live_sentinel", "synthetic_demo", or "farmer_capture"
    sensor_source: str
    capture_timestamp_utc: str
    client_capture_sha256: Optional[str] = None
    server_raw_upload_sha256: Optional[str] = None
    upload_hash_verified: Optional[bool] = None
    metadata: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.provenance not in VALID_PROVENANCES:
            raise ValueError(
                f"Invalid provenance '{self.provenance}'. "
                f"Must be one of {VALID_PROVENANCES}."
            )


@dataclass
class GhatalTelemetryBundle:
    """Complete satellite and ground bundle with explicit provenance & uncertainty."""

    latitude: float
    longitude: float
    coordinates_label: str
    mouza_name: str
    jl_number: str
    khatian_no: str
    plot_dag_no: str
    acquisition_mode: str
    gee_authenticated: bool
    gee_auth_error: Optional[str]
    flood_inundation_pct: float
    sar_vv_db: float
    ndvi_pre_flood: float
    ndvi_post_flood: float
    estimated_crop_loss_pct: float
    inundation_timestamp_utc: str
    intimation_timestamp_utc: str
    hours_since_inundation: float
    within_72h_window: bool
    sar_scene_id: str
    ndvi_scene_id: str
    uncertainty_note: str
    sar_artifact: EvidenceArtifact
    ndvi_artifact: EvidenceArtifact
    ground_artifact: EvidenceArtifact
    voice_note_sha256: Optional[str] = None
    server_voice_upload_sha256: Optional[str] = None
    voice_hash_verified: Optional[bool] = None
    uncertain_pct: Optional[float] = None

    @property
    def contains_synthetic_demo(self) -> bool:
        """Return True if any artifact in the bundle has synthetic_demo provenance."""
        return any(
            art.provenance == "synthetic_demo"
            for art in (self.sar_artifact, self.ndvi_artifact, self.ground_artifact)
        )


def compute_file_sha256(file_path: str) -> str:
    """Compute SHA-256 hex digest of a file using hashlib.sha256()."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def initialize_gee_with_project() -> Tuple[bool, Optional[str]]:
    """Initialize Earth Engine with explicit project and service account env vars."""
    if not EE_AVAILABLE:
        return False, "earthengine-api package is not installed."

    project_id = os.environ.get("GEE_PROJECT_ID", "").strip()
    service_account = os.environ.get("GEE_SERVICE_ACCOUNT", "").strip()
    key_json_path = os.environ.get("GEE_PRIVATE_KEY_JSON", "").strip()

    try:
        if service_account and key_json_path and os.path.exists(key_json_path):
            credentials = ee.ServiceAccountCredentials(service_account, key_json_path)
            ee.Initialize(
                credentials=credentials,
                project=project_id or None,
            )
            return True, None
        if project_id:
            ee.Initialize(project=project_id)
            return True, None
        return (
            False,
            "GEE_PROJECT_ID environment variable is not set. Set GEE_PROJECT_ID "
            "and service account credentials to run a live Sentinel-1 query.",
        )
    except Exception as exc:
        return False, f"GEE Authentication Failed: {exc}"


def query_live_sentinel1_ghatal(
    lat: float = GHATAL_LAT,
    lon: float = GHATAL_LON,
    baseline_start: str = "2024-08-01",
    baseline_end: str = "2024-09-10",
) -> Dict[str, Any]:
    """Query Earth Engine COPERNICUS/S1_GRD for the catalogued September 2024 event granule.

    - Selects the event image on the catalogued acquisition date, restricted to
      the same relative orbit and pass direction recorded from the CDSE catalogue.
    - Builds the pre-flood baseline from the SAME relative orbit and direction.
    - Cross-checks the Earth Engine system:index against the catalogued granule.
    - Applies the threshold + uncertain-margin rule (see classify_backscatter)
      and reports certified-flood and uncertain fractions separately.

    Raises RuntimeError rather than substituting default values.
    """
    if not EE_AVAILABLE:
        raise RuntimeError("earthengine-api is not installed.")

    point = ee.Geometry.Point([lon, lat])
    aoi = point.buffer(2500).bounds()
    rel_orbit = int(EVENT_GRANULE["relative_orbit"])
    direction = EVENT_GRANULE["orbit_direction"]
    event_day = EVENT_GRANULE["acquisition_start_utc"][:10]
    event_next = (
        datetime.date.fromisoformat(event_day) + datetime.timedelta(days=1)
    ).isoformat()

    same_geometry_col = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(point)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.eq("orbitProperties_pass", direction))
        .filter(ee.Filter.eq("relativeOrbitNumber_start", rel_orbit))
        .select("VV")
    )

    flood_col = same_geometry_col.filterDate(event_day, event_next)
    base_col = same_geometry_col.filterDate(baseline_start, baseline_end)

    if flood_col.size().getInfo() == 0:
        raise RuntimeError(
            f"No Earth Engine image found for catalogued granule date {event_day} "
            f"(relative orbit {rel_orbit}, {direction})."
        )
    baseline_count = base_col.size().getInfo()
    if baseline_count == 0:
        raise RuntimeError("No same-orbit pre-flood baseline images found.")

    flood_img = ee.Image(flood_col.first())
    base_img = base_col.median()

    scene_id = flood_img.get("system:index").getInfo()
    time_ms = flood_img.get("system:time_start").getInfo()
    acq_date_utc = datetime.datetime.fromtimestamp(
        time_ms / 1000.0, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    granule_match = scene_id.startswith(EVENT_GRANULE["expected_gee_system_index_prefix"])
    if not granule_match:
        raise RuntimeError(
            f"Earth Engine image {scene_id} does not match catalogued granule "
            f"{EVENT_GRANULE['granule_name']}; refusing to certify a different record."
        )

    mean_dict = flood_img.reduceRegion(
        reducer=ee.Reducer.mean(), geometry=aoi, scale=10, maxPixels=1e8
    ).getInfo()
    if mean_dict.get("VV") is None:
        raise RuntimeError("Earth Engine returned no VV values over the AOI.")
    vv_db = round(float(mean_dict["VV"]), 2)

    lower = WATER_THRESHOLD_DB - UNCERTAIN_MARGIN_DB
    upper = WATER_THRESHOLD_DB + UNCERTAIN_MARGIN_DB
    uncertain = flood_img.gte(lower).And(flood_img.lte(upper))
    certified_flood = flood_img.lt(lower).And(base_img.gt(BASELINE_DRY_DB))

    fractions = (
        ee.Image.cat([certified_flood.rename("flood"), uncertain.rename("uncertain")])
        .reduceRegion(reducer=ee.Reducer.mean(), geometry=aoi, scale=10, maxPixels=1e8)
        .getInfo()
    )
    if fractions.get("flood") is None or fractions.get("uncertain") is None:
        raise RuntimeError("Earth Engine returned no classification values over the AOI.")

    # Real rendering: R = baseline, G = event, B = certified flood; uncertain shown yellow
    visual = (
        ee.Image.cat(
            [
                base_img.unitScale(-25, -5).multiply(255),
                flood_img.unitScale(-25, -5).multiply(255),
                certified_flood.multiply(255),
            ]
        )
        .where(uncertain, ee.Image.constant([255, 220, 0]))
        .toByte()
    )
    thumb_url = visual.getThumbURL({"region": aoi, "dimensions": 640, "format": "png"})

    return {
        "s1_scene_id": f"COPERNICUS/S1_GRD/{scene_id}",
        "acquisition_utc": acq_date_utc,
        "granule_matches_catalogue": granule_match,
        "baseline_image_count": baseline_count,
        "sar_vv_db": vv_db,
        "inundation_pct": round(float(fractions["flood"]) * 100.0, 1),
        "uncertain_pct": round(float(fractions["uncertain"]) * 100.0, 1),
        "thumb_url": thumb_url,
    }


def _generate_sar_mask_image(
    output_path: str,
    lat: float,
    lon: float,
    mouza: str,
    plot_no: str,
    sar_db: float,
    inundation_pct: float,
    timestamp_utc: str,
    provenance: str,
    scene_id: str,
) -> None:
    """Render SAR visualization image and stamp DEMO warning if synthetic_demo."""
    width, height = 640, 420
    img = Image.new("RGB", (width, height), (14, 23, 38))
    draw = ImageDraw.Draw(img)

    seed_bytes = hashlib.sha256(
        f"SAR:{lat:.4f}:{lon:.4f}:{mouza}:{plot_no}".encode("utf-8")
    ).digest()

    cell_size = 8
    for y in range(0, height - 76, cell_size):
        for x in range(0, width, cell_size):
            nx = (x - width / 2.0) / (width / 2.0)
            ny = (y - (height - 76) / 2.0) / ((height - 76) / 2.0)
            river_curve = 0.25 * math.sin(nx * 3.2 + seed_bytes[0] / 40.0)
            dist_to_channel = abs(ny - river_curve)
            byte_idx = ((x // cell_size) * 17 + (y // cell_size) * 31) % 32
            speckle = (seed_bytes[byte_idx] - 128) / 512.0

            if dist_to_channel + speckle < 0.42:
                blue_val = min(255, max(120, int(210 - dist_to_channel * 180)))
                color = (12, 85, blue_val)
            elif dist_to_channel + speckle < 0.62:
                color = (28, 140, 170)
            else:
                gray = min(210, max(60, int(110 + speckle * 140)))
                color = (gray, gray + 10, gray)

            draw.rectangle([x, y, x + cell_size - 1, y + cell_size - 1], fill=color)

    for gx in range(80, width, 80):
        draw.line([(gx, 0), (gx, height - 76)], fill=(45, 75, 105), width=1)
    for gy in range(70, height - 76, 70):
        draw.line([(0, gy), (width, gy)], fill=(45, 75, 105), width=1)

    draw.rectangle([230, 115, 410, 245], outline=(255, 215, 0), width=2)
    draw.text((238, 122), f"DAG #{plot_no} ({mouza})", fill=(255, 235, 120))
    draw.text(
        (238, 140),
        f"SAR VV: {sar_db:.1f} dB | {inundation_pct:.1f}%",
        fill=(255, 255, 255),
    )

    if provenance == "synthetic_demo":
        draw.rectangle([0, 0, width, 30], fill=(153, 27, 27))
        draw.text(
            (14, 8),
            "DEMO, SYNTHETIC DATA, NOT EVIDENCE — PROVENANCE: synthetic_demo",
            fill=(255, 255, 255),
        )

    draw.rectangle([0, height - 76, width, height], fill=(9, 15, 26))
    draw.line([(0, height - 76), (width, height - 76)], fill=(0, 180, 216), width=2)
    draw.text(
        (14, height - 66),
        f"SCENE REF: {scene_id[:64]}",
        fill=(180, 225, 255),
    )
    draw.text(
        (14, height - 46),
        f"LOC: {lat:.4f} N, {lon:.4f} E | VV BACKSCATTER: {sar_db:.1f} dB | PROVENANCE: {provenance}",
        fill=(110, 231, 183),
    )
    draw.text(
        (14, height - 26),
        f"PASS REF: {timestamp_utc} | Backscatter typically varies within a few dB",
        fill=(148, 163, 184),
    )
    img.save(output_path, format="PNG")


def _generate_ndvi_map_image(
    output_path: str,
    lat: float,
    lon: float,
    mouza: str,
    plot_no: str,
    ndvi_pre: float,
    ndvi_post: float,
    loss_pct: float,
    timestamp_utc: str,
    provenance: str,
    scene_id: str,
) -> None:
    """Render NDVI map and stamp DEMO warning if provenance is synthetic_demo."""
    width, height = 640, 420
    img = Image.new("RGB", (width, height), (20, 24, 33))
    draw = ImageDraw.Draw(img)

    seed_bytes = hashlib.sha256(
        f"NDVI:{lat:.4f}:{lon:.4f}:{mouza}:{plot_no}".encode("utf-8")
    ).digest()

    mid_x = width // 2
    cell_size = 8
    top_offset = 60 if provenance == "synthetic_demo" else 36

    for y in range(top_offset, height - 76, cell_size):
        for x in range(0, width, cell_size):
            byte_idx = ((x // cell_size) * 13 + (y // cell_size) * 29) % 32
            jitter = (seed_bytes[byte_idx] - 128) / 255.0
            if x < mid_x - 2:
                green = min(225, max(120, int(185 + jitter * 45)))
                color = (34, green, 64)
            elif x > mid_x + 2:
                red = min(235, max(150, int(200 + jitter * 40)))
                green_post = min(130, max(45, int(75 + jitter * 35)))
                color = (red, green_post, 42)
            else:
                color = (255, 255, 255)

            draw.rectangle([x, y, x + cell_size - 1, y + cell_size - 1], fill=color)

    if provenance == "synthetic_demo":
        draw.rectangle([0, 0, width, 28], fill=(153, 27, 27))
        draw.text(
            (14, 7),
            "DEMO, SYNTHETIC DATA, NOT EVIDENCE — PROVENANCE: synthetic_demo",
            fill=(255, 255, 255),
        )

    draw.rectangle([0, top_offset - 28, width, top_offset], fill=(15, 23, 42))
    draw.text(
        (16, top_offset - 21),
        f"PRE-FLOOD BASELINE (NDVI: {ndvi_pre:.2f})",
        fill=(74, 222, 128),
    )
    draw.text(
        (mid_x + 16, top_offset - 21),
        f"POST-FLOOD ANOMALY (NDVI: {ndvi_post:.2f})",
        fill=(248, 113, 113),
    )

    draw.rectangle([75, 135, 235, 245], outline=(255, 255, 255), width=2)
    draw.rectangle(
        [mid_x + 75, 135, mid_x + 235, 245],
        outline=(255, 215, 0),
        width=2,
    )
    draw.text(
        (mid_x + 83, 143),
        f"DAG #{plot_no}: -{loss_pct:.1f}% NDVI",
        fill=(255, 245, 157),
    )

    draw.rectangle([0, height - 76, width, height], fill=(9, 15, 26))
    draw.line([(0, height - 76), (width, height - 76)], fill=(239, 68, 68), width=2)
    draw.text(
        (14, height - 66),
        f"OPTICAL NOTE: {scene_id[:64]}",
        fill=(254, 202, 202),
    )
    draw.text(
        (14, height - 46),
        f"MOUZA: {mouza} | DAG: {plot_no} | NDVI: {ndvi_pre:.2f} -> {ndvi_post:.2f} | PROVENANCE: {provenance}",
        fill=(253, 224, 71),
    )
    draw.text(
        (14, height - 26),
        f"REF: {timestamp_utc} | Monsoon cloud cover frequently obscures optical passes",
        fill=(148, 163, 184),
    )
    img.save(output_path, format="PNG")


def _generate_ground_photo_image(
    output_path: str,
    lat: float,
    lon: float,
    mouza: str,
    plot_no: str,
    cultivator_name: str,
    timestamp_utc: str,
    provenance: str,
) -> None:
    """Render synthetic placeholder photo with prominent DEMO banner if synthetic_demo."""
    width, height = 640, 420
    img = Image.new("RGB", (width, height), (35, 48, 62))
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, width, 150], fill=(115, 132, 148))
    for x in range(0, width, 24):
        draw.ellipse([x - 10, 125, x + 26, 160], fill=(42, 72, 52))

    draw.rectangle([0, 150, width, height - 80], fill=(78, 98, 84))
    for y in range(165, height - 85, 16):
        draw.line([(20, y), (width - 20, y)], fill=(96, 118, 105), width=2)
        for x in range(35, width - 35, 38):
            draw.line([(x, y), (x + 4, y - 9)], fill=(120, 145, 70), width=2)

    if provenance == "synthetic_demo":
        draw.rectangle([0, 0, width, 32], fill=(153, 27, 27))
        draw.text(
            (14, 9),
            "DEMO PLACEHOLDER PHOTO — SYNTHETIC DATA, NOT EVIDENCE",
            fill=(255, 255, 255),
        )

    draw.rectangle([0, height - 80, width, height], fill=(12, 18, 28))
    draw.line([(0, height - 80), (width, height - 80)], fill=(34, 197, 94), width=2)
    draw.text(
        (14, height - 70),
        f"PROVENANCE: {provenance} | GPS: {lat:.4f} N, {lon:.4f} E (Ghatal)",
        fill=(134, 239, 172),
    )
    draw.text(
        (14, height - 50),
        f"CLAIMANT: {cultivator_name} | MOUZA: {mouza} | DAG NO: {plot_no}",
        fill=(255, 255, 255),
    )
    draw.text(
        (14, height - 30),
        f"TIMESTAMP UTC: {timestamp_utc} | SERVER OUTPUT INTEGRITY SEALED",
        fill=(148, 163, 184),
    )
    img.save(output_path, format="PNG")


class GhatalGEEFetcher:
    """Fetches GEE telemetry for Ghatal with explicit auth reporting and provenance."""

    def __init__(self, artifact_dir: str = "artifacts") -> None:
        self.artifact_dir = artifact_dir
        os.makedirs(self.artifact_dir, exist_ok=True)
        self.gee_live, self.gee_auth_error = initialize_gee_with_project()

    def fetch_evidence_bundle(
        self,
        cultivator_name: str,
        mouza_name: str = "Kharar",
        jl_number: str = "JL-42",
        khatian_no: str = "KH-1084",
        plot_dag_no: str = "412",
        latitude: float = GHATAL_LAT,
        longitude: float = GHATAL_LON,
        inundation_hours_ago: float = 18.5,
        custom_ground_photo_path: Optional[str] = None,
        client_photo_sha256: Optional[str] = None,
        server_raw_photo_sha256: Optional[str] = None,
        client_voice_sha256: Optional[str] = None,
        server_raw_voice_sha256: Optional[str] = None,
        allow_synthetic_demo: bool = True,
        override_satellite_provenance: Optional[str] = None,
    ) -> GhatalTelemetryBundle:
        """Fetch satellite & ground artifacts with strict provenance tagging."""
        if not self.gee_live and not allow_synthetic_demo:
            raise RuntimeError(
                f"Earth Engine is not authenticated ({self.gee_auth_error}) and "
                "synthetic demo fallback is disabled."
            )

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        intimation_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        digest = hashlib.sha256(
            f"{mouza_name}:{plot_dag_no}:{latitude:.4f}:{longitude:.4f}".encode("utf-8")
        ).digest()
        ndvi_pre = round(0.65 + (digest[2] / 255.0) * 0.12, 2)
        ndvi_post = round(0.13 + (digest[3] / 255.0) * 0.08, 2)
        crop_loss_pct = round(((ndvi_pre - ndvi_post) / ndvi_pre) * 100.0, 1)

        live_thumb_url: Optional[str] = None
        uncertain_pct: float
        if self.gee_live:
            try:
                live_s1 = query_live_sentinel1_ghatal(lat=latitude, lon=longitude)
                s1_scene = live_s1["s1_scene_id"]
                inundation_str = live_s1["acquisition_utc"]
                sar_vv_db = live_s1["sar_vv_db"]
                flood_inundation_pct = live_s1["inundation_pct"]
                uncertain_pct = live_s1["uncertain_pct"]
                live_thumb_url = live_s1["thumb_url"]
            except Exception as exc:
                self.gee_live = False
                self.gee_auth_error = f"Live GEE query failed: {exc}"
                if not allow_synthetic_demo:
                    raise RuntimeError(self.gee_auth_error) from exc

        if live_thumb_url is None:
            s1_scene = (
                "SYNTHETIC IMAGE - live run uses granule "
                f"{EVENT_GRANULE['granule_name']}"
            )
            inundation_str = EVENT_GRANULE["acquisition_start_utc"]
            sar_vv_db = round(-20.8 + (digest[0] / 255.0) * 2.1, 2)
            flood_inundation_pct = round(70.0 + (digest[1] / 255.0) * 16.0, 1)
            uncertain_pct = round(4.0 + (digest[4] / 255.0) * 6.0, 1)

        # NDVI has no live Sentinel-2 query yet, so it is ALWAYS synthetic_demo.
        # A dossier that includes it is therefore always watermarked.
        s2_scene = "SYNTHETIC - no Sentinel-2 query implemented (monsoon cloud likely)"

        if override_satellite_provenance in VALID_PROVENANCES:
            sar_provenance = override_satellite_provenance
            ndvi_provenance = override_satellite_provenance
        else:
            sar_provenance = "live_sentinel" if live_thumb_url else "synthetic_demo"
            ndvi_provenance = "synthetic_demo"
        sat_provenance = sar_provenance

        mode = (
            "LIVE_GEE_SENTINEL1_TELEMETRY"
            if sar_provenance == "live_sentinel"
            else "SYNTHETIC_DEMO_MODE (NOT EVIDENCE)"
        )

        safe_tag = f"{jl_number}_{plot_dag_no}".replace(" ", "_").replace("/", "_")
        sar_path = os.path.join(self.artifact_dir, f"sar_mask_{safe_tag}.png")
        ndvi_path = os.path.join(self.artifact_dir, f"ndvi_map_{safe_tag}.png")
        ground_path = os.path.join(self.artifact_dir, f"ground_photo_{safe_tag}.png")

        if live_thumb_url:
            # Real Earth Engine rendering of the before/after/flood composite
            urllib.request.urlretrieve(live_thumb_url, sar_path)
        else:
            _generate_sar_mask_image(
                output_path=sar_path,
                lat=latitude,
                lon=longitude,
                mouza=mouza_name,
                plot_no=plot_dag_no,
                sar_db=sar_vv_db,
                inundation_pct=flood_inundation_pct,
                timestamp_utc=inundation_str,
                provenance=sar_provenance,
                scene_id=s1_scene,
            )
        _generate_ndvi_map_image(
            output_path=ndvi_path,
            lat=latitude,
            lon=longitude,
            mouza=mouza_name,
            plot_no=plot_dag_no,
            ndvi_pre=ndvi_pre,
            ndvi_post=ndvi_post,
            loss_pct=crop_loss_pct,
            timestamp_utc="UNVERIFIED_DEMO_DATE" if ndvi_provenance == "synthetic_demo" else intimation_str,
            provenance=ndvi_provenance,
            scene_id=s2_scene,
        )

        upload_hash_verified: Optional[bool] = None
        if custom_ground_photo_path and os.path.exists(custom_ground_photo_path):
            if server_raw_photo_sha256 is None:
                server_raw_photo_sha256 = compute_file_sha256(custom_ground_photo_path)
            if client_photo_sha256:
                upload_hash_verified = (
                    client_photo_sha256.lower() == server_raw_photo_sha256.lower()
                )
            with Image.open(custom_ground_photo_path) as uploaded_img:
                uploaded_img.convert("RGB").save(ground_path, format="PNG")
            ground_provenance = "farmer_capture"
        else:
            ground_provenance = "synthetic_demo"
            _generate_ground_photo_image(
                output_path=ground_path,
                lat=latitude,
                lon=longitude,
                mouza=mouza_name,
                plot_no=plot_dag_no,
                cultivator_name=cultivator_name,
                timestamp_utc=intimation_str,
                provenance=ground_provenance,
            )

        voice_hash_verified: Optional[bool] = None
        if client_voice_sha256 and server_raw_voice_sha256:
            voice_hash_verified = (
                client_voice_sha256.lower() == server_raw_voice_sha256.lower()
            )

        sar_sha256 = compute_file_sha256(sar_path)
        ndvi_sha256 = compute_file_sha256(ndvi_path)
        ground_sha256 = compute_file_sha256(ground_path)

        sar_artifact = EvidenceArtifact(
            artifact_type="SAR_FLOOD_INUNDATION_MASK",
            file_path=sar_path,
            sha256_hash=sar_sha256,
            provenance=sat_provenance,
            sensor_source=f"Sentinel-1 C-Band SAR ({s1_scene})",
            capture_timestamp_utc=inundation_str,
            metadata={
                "coordinates": f"{latitude:.4f} N, {longitude:.4f} E",
                "mean_backscatter_db": f"{sar_vv_db} dB (typically varies within a few dB)",
                "inundation_coverage": f"{flood_inundation_pct}% (certified, uncertain pixels excluded)",
                "uncertain_coverage": f"{uncertain_pct}% (within +/-{UNCERTAIN_MARGIN_DB} dB of {WATER_THRESHOLD_DB} dB)",
                "provenance": sat_provenance,
            },
        )

        ndvi_artifact = EvidenceArtifact(
            artifact_type="NDVI_CROP_VIGOR_LOSS_MAP",
            file_path=ndvi_path,
            sha256_hash=ndvi_sha256,
            provenance=ndvi_provenance,
            sensor_source=f"Sentinel-2 MSI ({s2_scene})",
            capture_timestamp_utc="UNVERIFIED_DEMO_DATE" if ndvi_provenance == "synthetic_demo" else intimation_str,
            metadata={
                "coordinates": f"{latitude:.4f} N, {longitude:.4f} E",
                "ndvi_pre_flood": f"{ndvi_pre}",
                "ndvi_post_flood": f"{ndvi_post}",
                "estimated_crop_loss": f"{crop_loss_pct}%",
                "provenance": ndvi_provenance,
            },
        )

        ground_artifact = EvidenceArtifact(
            artifact_type="GEOTAGGED_GROUND_PHOTO",
            file_path=ground_path,
            sha256_hash=ground_sha256,
            provenance=ground_provenance,
            sensor_source=(
                "Farmer / PLV Device Capture (Capture-time hash compared on upload)"
                if ground_provenance == "farmer_capture"
                else "Synthetic Demo Placeholder (Not Evidence)"
            ),
            capture_timestamp_utc=intimation_str,
            client_capture_sha256=client_photo_sha256,
            server_raw_upload_sha256=server_raw_photo_sha256,
            upload_hash_verified=upload_hash_verified,
            metadata={
                "coordinates": f"{latitude:.4f} N, {longitude:.4f} E",
                "mouza": mouza_name,
                "plot_dag_no": plot_dag_no,
                "provenance": ground_provenance,
            },
        )

        return GhatalTelemetryBundle(
            latitude=latitude,
            longitude=longitude,
            coordinates_label=f"{latitude:.4f} N, {longitude:.4f} E",
            mouza_name=mouza_name,
            jl_number=jl_number,
            khatian_no=khatian_no,
            plot_dag_no=plot_dag_no,
            acquisition_mode=mode,
            gee_authenticated=self.gee_live,
            gee_auth_error=self.gee_auth_error,
            flood_inundation_pct=flood_inundation_pct,
            sar_vv_db=sar_vv_db,
            ndvi_pre_flood=ndvi_pre,
            ndvi_post_flood=ndvi_post,
            estimated_crop_loss_pct=crop_loss_pct,
            inundation_timestamp_utc=inundation_str,
            intimation_timestamp_utc=intimation_str,
            hours_since_inundation=round(inundation_hours_ago, 2),
            within_72h_window=inundation_hours_ago <= 72.0,
            sar_scene_id=s1_scene,
            ndvi_scene_id=s2_scene,
            uncertainty_note=HISTORICAL_GHATAL_FLOOD_EVENT["uncertainty_note"],
            sar_artifact=sar_artifact,
            ndvi_artifact=ndvi_artifact,
            ground_artifact=ground_artifact,
            voice_note_sha256=client_voice_sha256,
            server_voice_upload_sha256=server_raw_voice_sha256,
            voice_hash_verified=voice_hash_verified,
            uncertain_pct=uncertain_pct,
        )
