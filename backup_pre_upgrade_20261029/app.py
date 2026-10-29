"""Pramaana Web Application — Field Capture Terminal & DLSA Reviewer Dashboard.

Provides the Flask application for Ghatal, Paschim Medinipur (22.6654 N, 87.7218 E)
with:
1. Artifact Provenance Enforcement ("live_sentinel", "synthetic_demo", "farmer_capture").
2. Capture-Time Integrity Seals (WebCrypto + Pure-JS fallback for HTTP LAN phones)
   verified by Server Raw-Upload SHA-256 Re-Hashing.
3. Diagonal PDF Watermarking ("DEMO, SYNTHETIC DATA, NOT EVIDENCE") and VOID
   certificates whenever any artifact is "synthetic_demo".
4. Bilingual Bengali/English mobile-ready UI, collapsible legal basis panel,
   anchored SIMULATED countdown, append-only SQLite reviewer audit log, and
   DPDP Act consent + right-to-erasure deletion.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import secrets
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_file,
    session,
    url_for,
)

from gee_fetcher import (
    EVENT_GRANULE,
    GHATAL_LAT,
    GHATAL_LON,
    HISTORICAL_GHATAL_FLOOD_EVENT,
    GhatalGEEFetcher,
)
from pramaana_engine import (
    CITATION_BSA_63_4,
    CITATION_PMFBY_72H,
    CITATION_WBLRA_21B,
    WATERMARK_DEMO_TEXT,
    BargadarClaimProfile,
    PramaanaPDFGenerator,
    compute_chained_integrity_seals,
    load_legal_rules,
)

app = Flask(__name__)
app.secret_key = os.environ.get("PRAMAANA_SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
if os.environ.get("PRAMAANA_HTTPS_ONLY") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True

REVIEWER_USERNAME = os.environ.get("PRAMAANA_REVIEWER_USER", "dlsa_reviewer")
REVIEWER_PASSWORD = os.environ.get("PRAMAANA_REVIEWER_PASS", "ghatal_dlsa_2026")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTIFACT_DIR = os.path.join(BASE_DIR, "artifacts")
DOSSIER_DIR = os.path.join(BASE_DIR, "dossiers")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
AUDIT_DB_PATH = os.environ.get(
    "PRAMAANA_AUDIT_DB", os.path.join(BASE_DIR, "pramaana_audit.db")
)

os.makedirs(ARTIFACT_DIR, exist_ok=True)
os.makedirs(DOSSIER_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Fixed anchor timestamp for the SIMULATED 72-hour countdown so it never jumps up
SIMULATED_FLOOD_ONSET_EPOCH_MS = int(
    os.environ.get(
        "SIMULATED_FLOOD_EPOCH_MS",
        str(int((time.time() - 14.5 * 3600) * 1000)),
    )
)
SIMULATED_DEADLINE_EPOCH_MS = SIMULATED_FLOOD_ONSET_EPOCH_MS + (72 * 3600 * 1000)

gee_fetcher = GhatalGEEFetcher(artifact_dir=ARTIFACT_DIR)
pdf_generator = PramaanaPDFGenerator(output_dir=DOSSIER_DIR)

CLAIMS_LEDGER: List[Dict[str, Any]] = []


def _now_utc_str() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _init_audit_db() -> None:
    """Create append-only SQLite reviewer audit log table."""
    with sqlite3.connect(AUDIT_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviewer_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                action TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                note TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _append_audit_entry(
    claim_id: str, action: str, reviewer: str, note: str, timestamp_utc: str
) -> Dict[str, str]:
    """Insert an append-only reviewer action into SQLite and return the entry."""
    with sqlite3.connect(AUDIT_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO reviewer_audit_log (claim_id, action, reviewer, note, timestamp_utc)
            VALUES (?, ?, ?, ?, ?)
            """,
            (claim_id, action, reviewer, note, timestamp_utc),
        )
        conn.commit()
    return {
        "claim_id": claim_id,
        "action": action,
        "reviewer": reviewer,
        "note": note,
        "timestamp_utc": timestamp_utc,
    }


def _fetch_all_audit_entries() -> List[Dict[str, str]]:
    """Fetch all append-only reviewer audit log entries from SQLite."""
    with sqlite3.connect(AUDIT_DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT claim_id, action, reviewer, note, timestamp_utc "
            "FROM reviewer_audit_log ORDER BY id ASC"
        )
        return [
            {
                "claim_id": row[0],
                "action": row[1],
                "reviewer": row[2],
                "note": row[3],
                "timestamp_utc": row[4],
            }
            for row in cursor.fetchall()
        ]


_init_audit_db()


def _plain_status_message(review_state: str) -> str:
    """Return a plain-language English + Bengali status line for farmers."""
    mapping = {
        "PENDING_PLV_REVIEW": (
            "Your claim is waiting for review. "
            "(আপনার দাবিটি পর্যালোচনার অপেক্ষায় রয়েছে।)"
        ),
        "APPROVED": (
            "Your claim has been reviewed and approved for filing. "
            "(আপনার দাবিটি অনুমোদিত হয়েছে।)"
        ),
        "RETURNED": (
            "Your claim needs more information from the field. "
            "(আপনার দাবিতে আরও তথ্যের প্রয়োজন।)"
        ),
        "ESCALATED": (
            "Your claim has been escalated to the Legal Aid Clinic / Ombudsman. "
            "(আপনার দাবিটি আইনি সহায়তায় পাঠানো হয়েছে।)"
        ),
    }
    return mapping.get(review_state, mapping["PENDING_PLV_REVIEW"])


def _create_and_register_claim(
    profile: BargadarClaimProfile,
    latitude: float = GHATAL_LAT,
    longitude: float = GHATAL_LON,
    inundation_hours_ago: float = 16.0,
    custom_ground_photo_path: Optional[str] = None,
    client_photo_sha256: Optional[str] = None,
    server_raw_photo_sha256: Optional[str] = None,
    client_voice_sha256: Optional[str] = None,
    server_raw_voice_sha256: Optional[str] = None,
    initial_review_state: str = "PENDING_PLV_REVIEW",
) -> Dict[str, Any]:
    """Run fetcher, compute integrity seals on generated outputs, and build PDF."""
    if not profile.dpdp_consent_timestamp_utc:
        profile.dpdp_consent_timestamp_utc = _now_utc_str()

    telemetry = gee_fetcher.fetch_evidence_bundle(
        cultivator_name=profile.cultivator_name,
        mouza_name=profile.village_mouza,
        jl_number=profile.jl_number,
        khatian_no=profile.khatian_no,
        plot_dag_no=profile.plot_dag_no,
        latitude=latitude,
        longitude=longitude,
        inundation_hours_ago=inundation_hours_ago,
        custom_ground_photo_path=custom_ground_photo_path,
        client_photo_sha256=client_photo_sha256,
        server_raw_photo_sha256=server_raw_photo_sha256,
        client_voice_sha256=client_voice_sha256,
        server_raw_voice_sha256=server_raw_voice_sha256,
        allow_synthetic_demo=True,
    )
    hashes = compute_chained_integrity_seals(telemetry)
    pdf_path = pdf_generator.generate_dossier(profile=profile, telemetry=telemetry)

    is_demo = telemetry.contains_synthetic_demo
    dossier_status = (
        "DEMO OUTPUT (SYNTHETIC DATA — NOT EVIDENCE / CERT VOID)"
        if is_demo
        else "DRAFT DOSSIER — PENDING SIGNATURE (BSA 63(4))"
    )

    record: Dict[str, Any] = {
        "claim_id": profile.claim_id,
        "profile": profile,
        "telemetry": telemetry,
        "hashes": hashes,
        "pdf_path": pdf_path,
        "custom_ground_photo_path": custom_ground_photo_path,
        "dossier_status": dossier_status,
        "review_state": initial_review_state,
        "plain_status": _plain_status_message(initial_review_state),
    }
    CLAIMS_LEDGER.insert(0, record)
    return record


def _ensure_claim_files_exist(item: Dict[str, Any]) -> None:
    """Regenerate artifacts and PDF on demand if wiped on an ephemeral disk."""
    tel = item["telemetry"]
    prof = item["profile"]
    missing_artifacts = any(
        not os.path.exists(p)
        for p in (
            tel.sar_artifact.file_path,
            tel.ndvi_artifact.file_path,
            tel.ground_artifact.file_path,
        )
    )
    if missing_artifacts:
        new_tel = gee_fetcher.fetch_evidence_bundle(
            cultivator_name=prof.cultivator_name,
            mouza_name=prof.village_mouza,
            jl_number=prof.jl_number,
            khatian_no=prof.khatian_no,
            plot_dag_no=prof.plot_dag_no,
            latitude=tel.latitude,
            longitude=tel.longitude,
            inundation_hours_ago=tel.hours_since_inundation,
            custom_ground_photo_path=item.get("custom_ground_photo_path"),
            client_photo_sha256=tel.ground_artifact.client_capture_sha256,
            server_raw_photo_sha256=tel.ground_artifact.server_raw_upload_sha256,
            client_voice_sha256=tel.voice_note_sha256,
            server_raw_voice_sha256=tel.server_voice_upload_sha256,
            allow_synthetic_demo=True,
        )
        item["telemetry"] = new_tel
        item["hashes"] = compute_chained_integrity_seals(new_tel)

    if not os.path.exists(item["pdf_path"]):
        item["pdf_path"] = pdf_generator.generate_dossier(
            profile=prof,
            telemetry=item["telemetry"],
        )


def _seed_initial_ghatal_claims() -> None:
    """Seed fictionalized demo claims for Ghatal on startup."""
    if CLAIMS_LEDGER:
        return

    existing_logs = _fetch_all_audit_entries()

    prof_1 = BargadarClaimProfile(
        claim_id="PRM-GHT-2026-001",
        cultivator_name="[FICTIONAL DEMO] Cultivator A (Mansuka Sharecropper)",
        father_or_spouse_name="[FICTIONAL DEMO] Parentage A",
        village_mouza="Mansuka",
        gram_panchayat="Mansuka-I GP",
        jl_number="JL-38",
        khatian_no="KH-DEMO-942",
        plot_dag_no="412",
        cultivator_category="Unrecorded Bargadar (Sec. 21B Statutory Presumption)",
        landowner_raiyat_name="[FICTIONAL DEMO] Raiyat Owner A",
        crop_share_ratio="",
        area_acres=1.45,
        crop_variety="Kharif Aman Paddy (Swarna Sub-1)",
        bank_account_masked="XXXX-XXXX-DEMO",
        ifsc_code="PUNB0RRBBGB",
        dlsa_plv_name="PLV Volunteer #104 (Demo)",
        dlsa_plv_id="DLSA-PMD-PLV-104",
        panchanama_witness_1="Adjacent Cultivator #1 (Plot 413 - Demo)",
        panchanama_witness_2="GP Member Representative (Mansuka-I - Demo)",
        dpdp_consent_recorded=True,
        dpdp_consent_timestamp_utc="2026-10-25T10:00:00Z",
        is_fictional_demo_identity=True,
    )

    prof_2 = BargadarClaimProfile(
        claim_id="PRM-GHT-2026-002",
        cultivator_name="[FICTIONAL DEMO] Cultivator B (Kharar Barga Holder)",
        father_or_spouse_name="[FICTIONAL DEMO] Parentage B",
        village_mouza="Kharar",
        gram_panchayat="Kharar Rural GP",
        jl_number="JL-42",
        khatian_no="KH-DEMO-1205",
        plot_dag_no="289",
        cultivator_category="Recorded Bargadar (Barga Khatian Holder)",
        landowner_raiyat_name="[FICTIONAL DEMO] Raiyat Owner B",
        crop_share_ratio="",
        area_acres=2.10,
        crop_variety="Kharif Aman Paddy (Lalat)",
        bank_account_masked="XXXX-XXXX-DEMO",
        ifsc_code="SBIN0001408",
        dlsa_plv_name="PLV Volunteer #089 (Demo)",
        dlsa_plv_id="DLSA-PMD-PLV-089",
        panchanama_witness_1="Adjacent Cultivator #2 (Plot 290 - Demo)",
        panchanama_witness_2="Krishak Bandhu Representative (Demo)",
        dpdp_consent_recorded=True,
        dpdp_consent_timestamp_utc="2026-10-25T09:30:00Z",
        is_fictional_demo_identity=True,
    )

    if not existing_logs:
        seed_entry = _append_audit_entry(
            claim_id="PRM-GHT-2026-002",
            action="APPROVED",
            reviewer="dlsa_reviewer",
            note="Panchanama witnesses & Barga Khatian checked (Demo Audit Entry)",
            timestamp_utc="2026-10-25T10:15:00Z",
        )
        prof_2.reviewer_log.append(seed_entry)
    else:
        for log_item in existing_logs:
            if log_item["claim_id"] == "PRM-GHT-2026-001":
                prof_1.reviewer_log.append(log_item)
            elif log_item["claim_id"] == "PRM-GHT-2026-002":
                prof_2.reviewer_log.append(log_item)

    _create_and_register_claim(
        profile=prof_2,
        latitude=22.6712,
        longitude=87.7305,
        inundation_hours_ago=29.0,
        initial_review_state=prof_2.reviewer_log[-1]["action"] if prof_2.reviewer_log else "PENDING_PLV_REVIEW",
    )
    _create_and_register_claim(
        profile=prof_1,
        latitude=22.6654,
        longitude=87.7218,
        inundation_hours_ago=14.5,
        initial_review_state=prof_1.reviewer_log[-1]["action"] if prof_1.reviewer_log else "PENDING_PLV_REVIEW",
    )


_seed_initial_ghatal_claims()


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pramaana | Flood Claim Assistance — Ghatal (প্রমাণ)</title>
    <style>
        :root {
            --bg-dark: #0b1120;
            --bg-card: #111827;
            --bg-panel: #1e293b;
            --border: #334155;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-blue: #38bdf8;
            --accent-amber: #f59e0b;
            --accent-red: #ef4444;
            --accent-green: #10b981;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans Bengali", sans-serif;
            background-color: var(--bg-dark);
            color: var(--text-main);
            line-height: 1.5;
            padding-bottom: 3rem;
        }
        header {
            background: linear-gradient(90deg, #0f172a 0%, #1e3a8a 100%);
            border-bottom: 2px solid var(--accent-blue);
            padding: 0.9rem 1.25rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.85rem;
        }
        .brand-title { font-size: 1.25rem; font-weight: 800; color: #fff; }
        .brand-sub { font-size: 0.8rem; color: #bae6fd; }
        .header-right { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }
        .timer-badge {
            background: rgba(239, 68, 68, 0.18);
            border: 1px solid var(--accent-red);
            padding: 0.4rem 0.8rem;
            border-radius: 8px;
        }
        .timer-badge .timer-label {
            font-size: 0.68rem;
            text-transform: uppercase;
            color: #fca5a5;
            display: block;
        }
        .timer-badge .timer-clock {
            font-family: "Courier New", monospace;
            font-size: 1rem;
            font-weight: 700;
            color: #fef2f2;
        }
        .container { max-width: 1380px; margin: 1rem auto; padding: 0 1rem; }
        .short-demo-strip {
            background: #450a0a;
            border: 1px solid #ef4444;
            border-radius: 8px;
            padding: 0.65rem 1rem;
            margin-bottom: 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.5rem;
            font-size: 0.88rem;
            color: #fecaca;
        }
        details.legal-basis-drawer {
            background: #172554;
            border: 1px solid #3b82f6;
            border-radius: 8px;
            padding: 0.65rem 1rem;
            margin-bottom: 1rem;
            font-size: 0.82rem;
            color: #e2e8f0;
        }
        details.legal-basis-drawer summary {
            cursor: pointer;
            font-weight: 700;
            color: #fde047;
        }
        .drawer-body {
            margin-top: 0.65rem;
            padding-top: 0.65rem;
            border-top: 1px solid rgba(255,255,255,0.15);
            display: grid;
            gap: 0.45rem;
        }
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 0.85rem;
            margin-bottom: 1.15rem;
        }
        .kpi-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 0.85rem 1rem;
        }
        .kpi-card .kpi-title { font-size: 0.72rem; text-transform: uppercase; color: var(--text-muted); }
        .kpi-card .kpi-value { font-size: 1.1rem; font-weight: 700; margin-top: 0.2rem; color: var(--accent-blue); }
        .kpi-card .kpi-foot { font-size: 0.73rem; color: #cbd5e1; margin-top: 0.2rem; }
        .main-grid {
            display: grid;
            grid-template-columns: 460px 1fr;
            gap: 1.25rem;
            align-items: start;
        }
        @media (max-width: 1024px) { .main-grid { grid-template-columns: 1fr; } }
        .panel {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 1.15rem;
            margin-bottom: 1.15rem;
        }
        .panel-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 0.5rem;
            border-bottom: 1px solid var(--border);
            padding-bottom: 0.65rem;
            margin-bottom: 0.9rem;
        }
        .panel-title { font-size: 1rem; font-weight: 700; color: #f8fafc; line-height: 1.35; }
        .badge {
            display: inline-block;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            font-size: 0.7rem;
            font-weight: 700;
            white-space: nowrap;
        }
        .badge-red { background: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid #ef4444; }
        .badge-green { background: rgba(16, 185, 129, 0.2); color: #6ee7b7; border: 1px solid #10b981; }
        .badge-blue { background: rgba(56, 189, 248, 0.2); color: #7dd3fc; border: 1px solid #38bdf8; }
        .badge-amber { background: rgba(245, 158, 11, 0.2); color: #fcd34d; border: 1px solid #f59e0b; }
        .form-group { margin-bottom: 0.8rem; }
        .form-row-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.65rem;
        }
        @media (max-width: 560px) { .form-row-2 { grid-template-columns: 1fr; } }
        label {
            display: block;
            font-size: 0.78rem;
            font-weight: 600;
            color: #e2e8f0;
            margin-bottom: 0.25rem;
        }
        label .bn { color: #93c5fd; font-weight: 500; }
        input, select, textarea {
            width: 100%;
            padding: 0.55rem 0.7rem;
            background: #0f172a;
            border: 1px solid var(--border);
            border-radius: 6px;
            color: #fff;
            font-size: 0.86rem;
        }
        .btn {
            display: inline-block;
            padding: 0.55rem 0.9rem;
            border-radius: 6px;
            font-weight: 700;
            font-size: 0.83rem;
            text-decoration: none;
            cursor: pointer;
            border: none;
            text-align: center;
        }
        .btn-emergency {
            width: 100%;
            background: linear-gradient(90deg, #dc2626 0%, #b91c1c 100%);
            color: #fff;
            padding: 0.7rem;
            margin-top: 0.35rem;
        }
        .btn-batch {
            width: 100%;
            background: #1e293b;
            color: #fca5a5;
            border: 1px solid #ef4444;
            margin-top: 0.5rem;
            font-size: 0.78rem;
        }
        .btn-download { background: #0284c7; color: #fff; padding: 0.35rem 0.7rem; font-size: 0.76rem; }
        .btn-small { padding: 0.32rem 0.6rem; font-size: 0.74rem; border-radius: 4px; }
        .claim-card {
            background: var(--bg-panel);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 0.95rem;
            margin-bottom: 1rem;
        }
        .plain-status-bar {
            background: rgba(15, 23, 42, 0.85);
            border-left: 4px solid var(--accent-blue);
            padding: 0.5rem 0.75rem;
            border-radius: 4px;
            margin-bottom: 0.65rem;
            font-size: 0.84rem;
            font-weight: 600;
            color: #e0f2fe;
        }
        .claim-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-bottom: 0.6rem;
        }
        .claim-id { font-family: "Courier New", monospace; font-weight: 700; color: var(--accent-blue); }
        .claim-meta {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
            gap: 0.5rem;
            font-size: 0.79rem;
            background: rgba(15, 23, 42, 0.65);
            padding: 0.6rem;
            border-radius: 6px;
            margin-bottom: 0.6rem;
        }
        .hash-box {
            font-family: "Courier New", monospace;
            font-size: 0.7rem;
            background: #090d16;
            border: 1px solid #1e293b;
            padding: 0.5rem;
            border-radius: 6px;
            color: #94a3b8;
            overflow-x: auto;
            margin-bottom: 0.65rem;
        }
        .hash-box span { color: #38bdf8; }
        .thumb-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 0.55rem;
            margin-top: 0.45rem;
        }
        .thumb-item {
            background: #0f172a;
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 0.35rem;
            text-align: center;
        }
        .thumb-item img { width: 100%; height: 105px; object-fit: cover; border-radius: 4px; display: block; }
        .thumb-caption { font-size: 0.69rem; color: #cbd5e1; margin-top: 0.25rem; }
        .review-bar {
            margin-top: 0.65rem;
            padding-top: 0.65rem;
            border-top: 1px dashed var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.5rem;
            font-size: 0.76rem;
        }
    </style>
</head>
<body>

<header>
    <div>
        <div class="brand-title">PRAMAANA (প্রমাণ) // FLOOD CLAIM ENGINE</div>
        <div class="brand-sub">Ghatal, Paschim Medinipur (22.6654 N, 87.7218 E) • Field Capture &amp; DLSA Reviewer Terminal</div>
    </div>
    <div class="header-right">
        <div class="timer-badge">
            <span class="timer-label">SIMULATED 72-Hour Flood Intimation Window</span>
            <span class="timer-clock" id="countdown-clock">SIMULATED: --:--:--</span>
        </div>
        {% if reviewer_logged_in %}
            <span class="badge badge-green">Reviewer: {{ reviewer_user }}</span>
            <a href="{{ url_for('logout') }}" class="btn btn-small" style="background:#334155;color:#fff;">Logout</a>
        {% else %}
            <form action="{{ url_for('login') }}" method="POST" autocomplete="off" style="display:flex;gap:0.35rem;align-items:center;flex-wrap:wrap;">
                <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                <input type="text" name="username" value="" placeholder="Reviewer ID" autocomplete="off" style="width:120px;padding:0.32rem 0.5rem;">
                <input type="password" name="password" value="" placeholder="Password" autocomplete="new-password" style="width:110px;padding:0.32rem 0.5rem;">
                <button type="submit" class="btn btn-small" style="background:#0284c7;color:#fff;">Reviewer Login</button>
            </form>
        {% endif %}
    </div>
</header>

<div class="container">
    {% if not gee_live %}
    <div class="short-demo-strip">
        <strong>⚠️ Demo mode: synthetic data, not evidence. (ডেমো মোড: কৃত্রিম তথ্য, আইনি প্রমাণ নয়)</strong>
        <span style="font-size:0.78rem;color:#fca5a5;">Earth Engine not connected (`GEE_PROJECT_ID` unset) — PDFs are watermarked DEMO &amp; certificates are VOID.</span>
    </div>
    {% endif %}

    <details class="legal-basis-drawer">
        <summary>ℹ️ About this data, satellite uncertainty, and legal basis (তথ্য ও আইনি ভিত্তি — ক্লিক করুন)</summary>
        <div class="drawer-body">
            <div><strong>1. Electronic Records ({{ citation_bsa }}):</strong> Part A is completed by the DLSA PLV (as person in charge of the claim on the farmer's behalf); Part B is completed by a Geomatics expert / system administrator. <em>Footnote: The Supreme Court has kept the scope of 'expert' under Part B open; we conservatively designate a qualified geomatics professional.</em> All draft certificates are marked <code>PENDING SIGNATURE</code> (or <code>VOID</code> in demo mode).</div>
            <div><strong>2. Bargadar Presumption ({{ citation_wblra }} — inserted by the West Bengal Land Reforms (Amendment) Act, 1969, West Ben. Act XI of 1969):</strong> <em>“A person lawfully cultivating any land belonging to another person shall be presumed to be a bargadar in respect of such land if such person is not a member of the family of the other person whose land he cultivates and the burden of proving that such person is not a bargadar or that the land is in his personal cultivation shall, notwithstanding anything to the contrary contained in any other law for the time being in force, lie on the person who alleges that the person cultivating the land is not a bargadar in respect of such land.”</em></div>
            <div><strong>3. 72-Hour Intimation ({{ citation_pmfby }} — Clause 21.5.5.4, 21.5.6.1 &amp; 21.5.5.6):</strong> <em>“Intimation may be given within 72 hours by the farmer either directly through the ‘Crop Insurance App’ or on dedicated centralized toll-free number of Krishi Rakshak Portal &amp; Helpline (14447).”</em> Under <strong>Clause 21.5.6.1</strong>, the 72-hour step is only the initial intimation (partial information allowed initially, complete details within 7 days); under <strong>Clause 21.5.5.6</strong>, banks/government officials receiving intimation must forward it to the insurer within 48 hours.</div>
            <div><strong>4. Copernicus Sentinel-1 Granule &amp; Uncertainty:</strong> {{ uncertainty_note }} Certified Copernicus granule: <code>{{ event_granule.granule_name }}</code> (acquired <code>{{ event_granule.acquisition_start_utc }}</code>, Relative Orbit {{ event_granule.relative_orbit }}, {{ event_granule.orbit_direction }}).</div>
            <div><strong>5. Earth Engine Status Detail:</strong> {{ gee_auth_error or "Authenticated with Google Earth Engine." }}</div>
        </div>
    </details>

    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-title">Earth Engine Status</div>
            <div class="kpi-value" style="color:{% if gee_live %}var(--accent-green){% else %}var(--accent-amber){% endif %};">
                {% if gee_live %}LIVE_SENTINEL{% else %}SYNTHETIC_DEMO{% endif %}
            </div>
            <div class="kpi-foot">Granule: {{ event_granule.acquisition_start_utc[:19] }}Z (Orbit {{ event_granule.relative_orbit }})</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Active Claims (দাবির সংখ্যা)</div>
            <div class="kpi-value">{{ claims|length }}</div>
            <div class="kpi-foot">Capture-Time Seal + Server Upload Re-Hash</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Minimal Data + Consent (DPDP)</div>
            <div class="kpi-value" style="color: var(--accent-green);">CONSENT + DELETE</div>
            <div class="kpi-foot">Consent checkbox &amp; 1-click data deletion enabled</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Append-Only Reviewer Log</div>
            <div class="kpi-value" style="color: var(--accent-blue);">{{ audit_log|length }} Recorded</div>
            <div class="kpi-foot">Persisted in SQLite with Reviewer ID &amp; UTC time</div>
        </div>
    </div>

    <div class="main-grid">
        <!-- Left Column: Farmer & PLV Mobile-Ready Capture Terminal -->
        <div class="panel">
            <div class="panel-header">
                <div class="panel-title">📱 Field Capture Terminal<br><span style="font-size:0.82rem;color:#93c5fd;font-weight:500;">মাঠ পর্যায়ের তথ্য ও ছবি সংগ্রহ</span></div>
                <span class="badge badge-blue" id="hash-engine-badge">Capture-Time Seal</span>
            </div>

            <form id="capture-form" action="{{ url_for('trigger_claim') }}" method="POST" enctype="multipart/form-data">
                <input type="hidden" name="csrf_token" value="{{ csrf_token }}">

                <div class="form-group">
                    <label>Claimant Name <span class="bn">(চাষির নাম — ডেমোতে কাল্পনিক নাম ব্যবহার করুন)</span> *</label>
                    <input type="text" name="cultivator_name" value="[FICTIONAL DEMO] Cultivator C (Sultanpur)" required>
                </div>

                <div class="form-group">
                    <label>Father / Spouse Name <span class="bn">(পিতা বা স্বামীর নাম)</span> *</label>
                    <input type="text" name="father_or_spouse_name" value="[FICTIONAL DEMO] Parentage C" required>
                </div>

                <div class="form-group">
                    <label>Tenancy Category <span class="bn">(ভাগচাষি / রাইয়ত শ্রেণী — ধারা ২১বি)</span> *</label>
                    <select name="cultivator_category">
                        <option value="Unrecorded Bargadar (Sec. 21B Statutory Presumption)">Unrecorded Bargadar / অ-নথিভুক্ত ভাগচাষি (Sec. 21B)</option>
                        <option value="Recorded Bargadar (Barga Khatian Holder)">Recorded Bargadar / নথিভুক্ত বর্গাদার</option>
                        <option value="Small / Marginal Raiyat Cultivator">Small / Marginal Raiyat / ক্ষুদ্র চাষি</option>
                    </select>
                </div>

                <div class="form-group">
                    <label>Recorded Landowner (Raiyat) <span class="bn">(জমির মালিকের নাম)</span></label>
                    <input type="text" name="landowner_raiyat_name" value="[FICTIONAL DEMO] Raiyat Owner C" required>
                </div>

                <div class="form-group">
                    <label>Crop-Share Ratio <span class="bn">(ভাগচাষের অনুপাত — উপকরণ কে দিচ্ছে তার ওপর নির্ভরশীল, ঐচ্ছিক)</span></label>
                    <input type="text" name="crop_share_ratio" value="" placeholder="Leave blank unless verified (depends on input supply under WBLRA)">
                </div>

                <div class="form-row-2">
                    <div class="form-group">
                        <label>Mouza <span class="bn">(মৌজা)</span></label>
                        <input type="text" name="village_mouza" value="Sultanpur" required>
                    </div>
                    <div class="form-group">
                        <label>Plot / Dag No. <span class="bn">(দাগ নম্বর)</span></label>
                        <input type="text" name="plot_dag_no" value="518" required>
                    </div>
                </div>

                <div class="form-row-2">
                    <div class="form-group">
                        <label>GPS Latitude <span class="bn">(<a href="#" onclick="acquireGPS();return false;" style="color:#38bdf8;">লোকেশন নিন</a>)</span></label>
                        <input type="number" step="0.0001" id="lat-input" name="latitude" value="22.6654" required>
                    </div>
                    <div class="form-group">
                        <label>GPS Longitude <span class="bn">(দ্রাঘিমাংশ)</span></label>
                        <input type="number" step="0.0001" id="lon-input" name="longitude" value="87.7218" required>
                    </div>
                </div>

                <div class="form-row-2">
                    <div class="form-group">
                        <label>Hours Since Flood <span class="bn">(বন্যা শুরুর পর কত ঘণ্টা)</span></label>
                        <input type="number" step="0.5" name="inundation_hours_ago" value="11.5" required>
                    </div>
                    <div class="form-group">
                        <label>Cultivated Area (Acres) <span class="bn">(জমির পরিমাণ)</span></label>
                        <input type="number" step="0.05" name="area_acres" value="1.65" required>
                    </div>
                </div>

                <div class="form-row-2">
                    <div class="form-group">
                        <label>Assisting DLSA PLV <span class="bn">(সহায়তাকারী পিএলভি)</span></label>
                        <input type="text" name="dlsa_plv_name" value="PLV Volunteer #112 (Demo)" required>
                    </div>
                    <div class="form-group">
                        <label>DLSA PLV ID <span class="bn">(পিএলভি আইডি)</span></label>
                        <input type="text" name="dlsa_plv_id" value="DLSA-PMD-PLV-112" required>
                    </div>
                </div>

                <div class="form-row-2">
                    <div class="form-group">
                        <label>Witness 1 <span class="bn">(পাশের জমির সাক্ষী ১)</span></label>
                        <input type="text" name="panchanama_witness_1" value="Adjacent Cultivator Witness 1" required>
                    </div>
                    <div class="form-group">
                        <label>Witness 2 <span class="bn">(পঞ্চায়েত / সাক্ষী ২)</span></label>
                        <input type="text" name="panchanama_witness_2" value="GP Representative Witness 2" required>
                    </div>
                </div>

                <div class="form-group">
                    <label>1. Field Photo <span class="bn">(জমির ছবি তুলুন — ফোনেই SHA-256 সিল তৈরি হবে)</span></label>
                    <input type="file" id="ground-photo-input" name="ground_photo" accept="image/*" capture="environment">
                    <input type="hidden" id="client-photo-sha256" name="client_photo_sha256" value="">
                    <div id="photo-hash-preview" style="font-family:monospace;font-size:0.7rem;color:#6ee7b7;margin-top:0.25rem;word-break:break-all;">
                        Capture-time photo seal: (Select a photo to compute SHA-256 on device)
                    </div>
                </div>

                <div class="form-group">
                    <label>2. Cultivator Voice Note <span class="bn">(চাষির কণ্ঠস্বর / ভয়েস নোট)</span></label>
                    <input type="file" id="voice-note-input" name="voice_note" accept="audio/*">
                    <input type="hidden" id="client-voice-sha256" name="client_voice_sha256" value="">
                    <div id="voice-hash-preview" style="font-family:monospace;font-size:0.7rem;color:#6ee7b7;margin-top:0.25rem;word-break:break-all;">
                        Capture-time voice seal: (Select an audio file to compute SHA-256 on device)
                    </div>
                </div>

                <div class="form-group" style="background:#0f172a;padding:0.65rem;border-radius:6px;border:1px solid #38bdf8;">
                    <label style="display:flex;gap:0.55rem;align-items:flex-start;cursor:pointer;margin:0;">
                        <input type="checkbox" name="dpdp_consent" value="yes" checked required style="width:18px;height:18px;margin-top:0.15rem;flex-shrink:0;">
                        <span style="font-size:0.76rem;color:#e2e8f0;font-weight:400;">
                            <strong>DPDP Consent (সম্মতি):</strong> I consent to minimal collection of plot coordinates, tenancy status, and field photo/voice note solely for flood claim intimation (Clause 21.5.5.4 &amp; 21.5.6.1 — initial 72-hour intimation; complete details within 7 days). Your claim data will be deleted, subject to 48-hour notice and statutory retention of security logs for one year under the DPDP Rules, 2025.
                        </span>
                    </label>
                </div>

                <button type="submit" class="btn btn-emergency">
                    🚨 SUBMIT 72H INTIMATION (Cl. 21.5.5.4 / 21.5.6.1) &amp; GENERATE DOSSIER (জমা দিন)
                </button>
            </form>

            <form action="{{ url_for('emergency_batch_trigger') }}" method="POST">
                <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                <button type="submit" class="btn btn-batch">
                    ⚡ Load September 2024 Flood Reference Case (Pratappur Mouza)
                </button>
            </form>
        </div>

        <!-- Right Column: DLSA PLV Reviewer Dashboard -->
        <div>
            <div class="panel">
                <div class="panel-header">
                    <div class="panel-title">⚖️ DLSA PLV &amp; Legal Clinic Reviewer Dashboard<br><span style="font-size:0.8rem;color:#93c5fd;font-weight:500;">দাবি পর্যালোচনা ও অডিট লগ</span></div>
                    <span class="badge badge-amber">Append-Only SQLite Audit Log</span>
                </div>

                {% for item in claims %}
                <div class="claim-card">
                    <div class="plain-status-bar">
                        📢 {{ item.plain_status }}
                    </div>

                    <div class="claim-top">
                        <div>
                            <span class="claim-id">{{ item.claim_id }}</span>
                            &nbsp;•&nbsp;
                            <strong>{{ item.profile.cultivator_name }}</strong>
                            &nbsp;
                            <span class="badge {% if item.review_state == 'APPROVED' %}badge-green{% elif item.review_state == 'ESCALATED' %}badge-red{% elif item.review_state == 'RETURNED' %}badge-amber{% else %}badge-blue{% endif %}">
                                {{ item.review_state }}
                            </span>
                        </div>
                        <div style="display:flex; gap:0.4rem; align-items:center; flex-wrap:wrap;">
                            {% if item.telemetry.contains_synthetic_demo %}
                            <span class="badge badge-red">DEMO / SYNTHETIC (CERT VOID)</span>
                            {% else %}
                            <span class="badge badge-green">DRAFT (PENDING SIGNATURE)</span>
                            {% endif %}
                            <a href="{{ url_for('download_dossier', claim_id=item.claim_id) }}" class="btn btn-download">
                                ⬇ Download PDF Dossier
                            </a>
                            <form action="{{ url_for('delete_claim', claim_id=item.claim_id) }}" method="POST" style="display:inline;">
                                <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                                <button type="submit" class="btn btn-small" style="background:#334155;color:#fca5a5;border:1px solid #ef4444;" title="Your claim data will be deleted, subject to 48-hour notice and statutory retention of security logs for one year under the DPDP Rules, 2025.">
                                    🗑️ Delete Data: Your claim data will be deleted, subject to 48-hour notice and statutory retention of security logs for one year under the DPDP Rules, 2025.
                                </button>
                            </form>
                        </div>
                    </div>

                    <div class="claim-meta">
                        <div>
                            <strong>Tenancy (Sec. 21B WBLRA):</strong><br>
                            <span style="color:#6ee7b7;">{{ item.profile.cultivator_category }}</span>
                        </div>
                        <div>
                            <strong>Mouza &amp; Plot (মৌজা ও দাগ):</strong><br>
                            {{ item.profile.village_mouza }} ({{ item.profile.jl_number }}), Dag #{{ item.profile.plot_dag_no }}
                        </div>
                        <div>
                            <strong>Crop-Share Ratio:</strong><br>
                            {{ item.profile.crop_share_ratio or "Not specified (depends on input supply)" }}
                        </div>
                        <div>
                            <strong>Artifact Provenances:</strong><br>
                            SAR: <code>{{ item.telemetry.sar_artifact.provenance }}</code> |
                            NDVI: <code>{{ item.telemetry.ndvi_artifact.provenance }}</code> |
                            Photo: <code>{{ item.telemetry.ground_artifact.provenance }}</code>
                        </div>
                        <div>
                            <strong>SAR / NDVI Summary:</strong><br>
                            <span style="color:#fca5a5;">
                                {{ item.telemetry.sar_vv_db }} dB |
                                -{{ item.telemetry.estimated_crop_loss_pct }}% NDVI Change
                            </span>
                        </div>
                        <div>
                            <strong>Consent &amp; Upload Check:</strong><br>
                            Consent: {{ item.profile.dpdp_consent_timestamp_utc }}<br>
                            Upload Check: <code>{{ item.hashes.photo_upload_hash_status }}</code>
                        </div>
                    </div>

                    <div class="hash-box">
                        <div><span>[CAPTURE-TIME PHOTO SEAL]</span>  {{ item.hashes.client_photo_sha256 }}</div>
                        <div><span>[SERVER RAW UPLOAD RE-HASH]</span> {{ item.hashes.server_raw_photo_sha256 }} ({{ item.hashes.photo_upload_hash_status }})</div>
                        <div><span>[CAPTURE-TIME VOICE SEAL]</span>  {{ item.hashes.client_voice_sha256 }}</div>
                        <div><span>[OUTPUT SEAL: SAR MASK]</span>    {{ item.hashes.sar_sha256 }}</div>
                        <div><span>[OUTPUT SEAL: NDVI MAP]</span>    {{ item.hashes.ndvi_sha256 }}</div>
                        <div><span>[CHAINED BUNDLE SEAL]</span>       {{ item.hashes.composite_bundle_sha256 }}</div>
                    </div>

                    <div class="thumb-row">
                        <div class="thumb-item">
                            <img src="{{ url_for('serve_artifact', claim_id=item.claim_id, artifact_kind='sar') }}" alt="SAR Flood Mask">
                            <div class="thumb-caption">SAR Mask [<code>{{ item.telemetry.sar_artifact.provenance }}</code>]</div>
                        </div>
                        <div class="thumb-item">
                            <img src="{{ url_for('serve_artifact', claim_id=item.claim_id, artifact_kind='ndvi') }}" alt="NDVI Map">
                            <div class="thumb-caption">NDVI Map [<code>{{ item.telemetry.ndvi_artifact.provenance }}</code>]</div>
                        </div>
                        <div class="thumb-item">
                            <img src="{{ url_for('serve_artifact', claim_id=item.claim_id, artifact_kind='ground') }}" alt="Ground Photo">
                            <div class="thumb-caption">Field Photo [<code>{{ item.telemetry.ground_artifact.provenance }}</code>]</div>
                        </div>
                    </div>

                    <div class="review-bar">
                        <div>
                            <strong>Reviewer Audit Trail:</strong>
                            {% if item.profile.reviewer_log %}
                                Latest: <code>{{ item.profile.reviewer_log[-1].action }}</code> by
                                <strong>{{ item.profile.reviewer_log[-1].reviewer }}</strong> at
                                {{ item.profile.reviewer_log[-1].timestamp_utc }} —
                                <em>"{{ item.profile.reviewer_log[-1].note }}"</em>
                            {% else %}
                                No reviewer action logged yet.
                            {% endif %}
                        </div>
                        {% if reviewer_logged_in %}
                        <form action="{{ url_for('review_action', claim_id=item.claim_id) }}" method="POST" style="display:flex;gap:0.35rem;align-items:center;flex-wrap:wrap;">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                            <input type="text" name="note" placeholder="Reviewer note..." style="width:155px;padding:0.28rem 0.45rem;font-size:0.75rem;">
                            <button type="submit" name="action" value="APPROVED" class="btn btn-small" style="background:#059669;color:#fff;">Approve</button>
                            <button type="submit" name="action" value="RETURNED" class="btn btn-small" style="background:#d97706;color:#fff;">Return</button>
                            <button type="submit" name="action" value="ESCALATED" class="btn btn-small" style="background:#dc2626;color:#fff;">Escalate</button>
                        </form>
                        {% else %}
                        <span style="color:#94a3b8;">Reviewer login required in top bar to Approve / Return / Escalate.</span>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
</div>

<script>
    // Anchored SIMULATED 72-Hour Countdown (never jumps up on reload)
    (function () {
        const deadlineMs = {{ simulated_deadline_ms }};
        const clockEl = document.getElementById("countdown-clock");
        function updateClock() {
            const diffSec = Math.max(0, Math.floor((deadlineMs - Date.now()) / 1000));
            const hrs = String(Math.floor(diffSec / 3600)).padStart(2, "0");
            const mins = String(Math.floor((diffSec % 3600) / 60)).padStart(2, "0");
            const secs = String(diffSec % 60).padStart(2, "0");
            if (clockEl) {
                clockEl.textContent = "SIMULATED: " + hrs + ":" + mins + ":" + secs + " LEFT";
            }
        }
        updateClock();
        setInterval(updateClock, 1000);
    })();

    // Pure-JS SHA-256 fallback so on-device hashing works even on HTTP LAN phones
    // where window.crypto.subtle is unavailable without HTTPS
    function sha256PureJS(uint8Arr) {
        const K = [
            0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
            0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
            0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
            0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
            0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
            0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
            0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
            0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
        ];
        function rotr(n, x) { return (x >>> n) | (x << (32 - n)); }
        const l = uint8Arr.length;
        const bitLenHi = Math.floor((l * 8) / 0x100000000);
        const bitLenLo = (l * 8) >>> 0;
        const padLen = ((l + 9 + 63) & ~63);
        const buf = new Uint8Array(padLen);
        buf.set(uint8Arr);
        buf[l] = 0x80;
        const view = new DataView(buf.buffer);
        view.setUint32(padLen - 8, bitLenHi, false);
        view.setUint32(padLen - 4, bitLenLo, false);

        let H0 = 0x6a09e667, H1 = 0xbb67ae85, H2 = 0x3c6ef372, H3 = 0xa54ff53a;
        let H4 = 0x510e527f, H5 = 0x9b05688c, H6 = 0x1f83d9ab, H7 = 0x5be0cd19;
        const W = new Uint32Array(64);

        for (let i = 0; i < padLen; i += 64) {
            for (let t = 0; t < 16; t++) W[t] = view.getUint32(i + t * 4, false);
            for (let t = 16; t < 64; t++) {
                const s0 = rotr(7, W[t - 15]) ^ rotr(18, W[t - 15]) ^ (W[t - 15] >>> 3);
                const s1 = rotr(17, W[t - 2]) ^ rotr(19, W[t - 2]) ^ (W[t - 2] >>> 10);
                W[t] = (W[t - 16] + s0 + W[t - 7] + s1) >>> 0;
            }
            let a = H0, b = H1, c = H2, d = H3, e = H4, f = H5, g = H6, h = H7;
            for (let t = 0; t < 64; t++) {
                const S1 = rotr(6, e) ^ rotr(11, e) ^ rotr(25, e);
                const ch = (e & f) ^ (~e & g);
                const temp1 = (h + S1 + ch + K[t] + W[t]) >>> 0;
                const S0 = rotr(2, a) ^ rotr(13, a) ^ rotr(22, a);
                const maj = (a & b) ^ (a & c) ^ (b & c);
                const temp2 = (S0 + maj) >>> 0;
                h = g; g = f; f = e; e = (d + temp1) >>> 0;
                d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
            }
            H0 = (H0 + a) >>> 0; H1 = (H1 + b) >>> 0; H2 = (H2 + c) >>> 0; H3 = (H3 + d) >>> 0;
            H4 = (H4 + e) >>> 0; H5 = (H5 + f) >>> 0; H6 = (H6 + g) >>> 0; H7 = (H7 + h) >>> 0;
        }
        return [H0, H1, H2, H3, H4, H5, H6, H7].map(v => v.toString(16).padStart(8, "0")).join("");
    }

    async function computeFileSHA256(file) {
        const buffer = await file.arrayBuffer();
        if (window.crypto && window.crypto.subtle) {
            const hashBuffer = await window.crypto.subtle.digest("SHA-256", buffer);
            const hashArray = Array.from(new Uint8Array(hashBuffer));
            return {
                hex: hashArray.map(b => b.toString(16).padStart(2, "0")).join(""),
                engine: "WebCrypto (Secure Origin)"
            };
        }
        return {
            hex: sha256PureJS(new Uint8Array(buffer)),
            engine: "Pure-JS SHA-256 Fallback (HTTP LAN)"
        };
    }

    const photoInput = document.getElementById("ground-photo-input");
    if (photoInput) {
        photoInput.addEventListener("change", async function (evt) {
            const file = evt.target.files[0];
            if (!file) return;
            const res = await computeFileSHA256(file);
            document.getElementById("client-photo-sha256").value = res.hex;
            document.getElementById("photo-hash-preview").textContent =
                "Capture-time photo SHA-256 [" + res.engine + "]: " + res.hex;
        });
    }

    const voiceInput = document.getElementById("voice-note-input");
    if (voiceInput) {
        voiceInput.addEventListener("change", async function (evt) {
            const file = evt.target.files[0];
            if (!file) return;
            const res = await computeFileSHA256(file);
            document.getElementById("client-voice-sha256").value = res.hex;
            document.getElementById("voice-hash-preview").textContent =
                "Capture-time voice SHA-256 [" + res.engine + "]: " + res.hex;
        });
    }

    function acquireGPS() {
        if (!navigator.geolocation) return;
        navigator.geolocation.getCurrentPosition(function (pos) {
            document.getElementById("lat-input").value = pos.coords.latitude.toFixed(4);
            document.getElementById("lon-input").value = pos.coords.longitude.toFixed(4);
        });
    }
</script>

</body>
</html>
"""


def _get_or_create_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


@app.route("/login", methods=["POST"])
def login():
    """Authenticate a DLSA / Legal Clinic Reviewer."""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    if username == REVIEWER_USERNAME and password == REVIEWER_PASSWORD:
        session["reviewer_logged_in"] = True
        session["reviewer_user"] = username
    return redirect(url_for("index"))


@app.route("/logout", methods=["GET"])
def logout():
    """Clear Reviewer session."""
    session.clear()
    return redirect(url_for("index"))


@app.route("/", methods=["GET"])
def index() -> str:
    """Render the Pramaana Capture Terminal & DLSA Reviewer Dashboard."""
    return render_template_string(
        DASHBOARD_HTML,
        claims=CLAIMS_LEDGER,
        gee_live=gee_fetcher.gee_live,
        gee_auth_error=gee_fetcher.gee_auth_error,
        watermark_text=WATERMARK_DEMO_TEXT,
        uncertainty_note=HISTORICAL_GHATAL_FLOOD_EVENT["uncertainty_note"],
        citation_bsa=CITATION_BSA_63_4,
        citation_wblra=CITATION_WBLRA_21B,
        citation_pmfby=CITATION_PMFBY_72H,
        reviewer_logged_in=bool(session.get("reviewer_logged_in")),
        reviewer_user=session.get("reviewer_user", ""),
        audit_log=_fetch_all_audit_entries(),
        simulated_deadline_ms=SIMULATED_DEADLINE_EPOCH_MS,
        csrf_token=_get_or_create_csrf_token(),
        event_granule=EVENT_GRANULE,
    )


@app.route("/api/trigger-claim", methods=["POST"])
def trigger_claim():
    """Handle claim submission, recompute upload hashes on server, and build PDF."""
    claim_num = len(CLAIMS_LEDGER) + 1
    claim_id = f"PRM-GHT-2026-{claim_num:03d}"

    cultivator_name = request.form.get(
        "cultivator_name", "[FICTIONAL DEMO] Bargadar Claimant"
    ).strip()
    father_name = request.form.get(
        "father_or_spouse_name", "[FICTIONAL DEMO] Parentage"
    ).strip()
    category = request.form.get(
        "cultivator_category",
        "Unrecorded Bargadar (Sec. 21B Statutory Presumption)",
    ).strip()
    raiyat_name = request.form.get(
        "landowner_raiyat_name", "[FICTIONAL DEMO] Recorded Raiyat"
    ).strip()
    share_ratio = request.form.get("crop_share_ratio", "").strip()
    mouza = request.form.get("village_mouza", "Sultanpur").strip()
    plot_dag_no = request.form.get("plot_dag_no", "518").strip()

    try:
        latitude = float(request.form.get("latitude", GHATAL_LAT))
    except ValueError:
        latitude = GHATAL_LAT

    try:
        longitude = float(request.form.get("longitude", GHATAL_LON))
    except ValueError:
        longitude = GHATAL_LON

    try:
        inundation_hours_ago = float(request.form.get("inundation_hours_ago", 12.0))
    except ValueError:
        inundation_hours_ago = 12.0

    try:
        area_acres = float(request.form.get("area_acres", 1.5))
    except ValueError:
        area_acres = 1.5

    dlsa_plv_name = request.form.get("dlsa_plv_name", "PLV Volunteer #112").strip()
    dlsa_plv_id = request.form.get("dlsa_plv_id", "DLSA-PMD-PLV-112").strip()
    witness_1 = request.form.get("panchanama_witness_1", "Local Neighbor Witness").strip()
    witness_2 = request.form.get("panchanama_witness_2", "GP Representative").strip()
    client_photo_sha256 = request.form.get("client_photo_sha256", "").strip() or None
    client_voice_sha256 = request.form.get("client_voice_sha256", "").strip() or None
    dpdp_consent = request.form.get("dpdp_consent", "yes") == "yes"

    custom_photo_path = None
    server_raw_photo_sha256 = None
    uploaded_file = request.files.get("ground_photo")
    if uploaded_file and uploaded_file.filename:
        raw_bytes = uploaded_file.read()
        server_raw_photo_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        ext = os.path.splitext(uploaded_file.filename)[1].lower() or ".png"
        safe_upload_name = f"upload_{uuid.uuid4().hex[:8]}{ext}"
        custom_photo_path = os.path.join(UPLOAD_DIR, safe_upload_name)
        with open(custom_photo_path, "wb") as out_f:
            out_f.write(raw_bytes)

    server_raw_voice_sha256 = None
    uploaded_voice = request.files.get("voice_note")
    if uploaded_voice and uploaded_voice.filename:
        voice_bytes = uploaded_voice.read()
        server_raw_voice_sha256 = hashlib.sha256(voice_bytes).hexdigest()

    profile = BargadarClaimProfile(
        claim_id=claim_id,
        cultivator_name=cultivator_name,
        father_or_spouse_name=father_name,
        village_mouza=mouza,
        gram_panchayat=f"{mouza} GP",
        jl_number="JL-45",
        khatian_no="KH-DEMO-1410",
        plot_dag_no=plot_dag_no,
        cultivator_category=category,
        landowner_raiyat_name=raiyat_name,
        crop_share_ratio=share_ratio,
        area_acres=area_acres,
        crop_variety="Kharif Aman Paddy (Swarna Sub-1)",
        bank_account_masked="XXXX-XXXX-DEMO",
        ifsc_code="PUNB0RRBBGB",
        dlsa_plv_name=dlsa_plv_name,
        dlsa_plv_id=dlsa_plv_id,
        panchanama_witness_1=witness_1,
        panchanama_witness_2=witness_2,
        dpdp_consent_recorded=dpdp_consent,
        dpdp_consent_timestamp_utc=_now_utc_str(),
    )

    _create_and_register_claim(
        profile=profile,
        latitude=latitude,
        longitude=longitude,
        inundation_hours_ago=inundation_hours_ago,
        custom_ground_photo_path=custom_photo_path,
        client_photo_sha256=client_photo_sha256,
        server_raw_photo_sha256=server_raw_photo_sha256,
        client_voice_sha256=client_voice_sha256,
        server_raw_voice_sha256=server_raw_voice_sha256,
    )

    return redirect(url_for("index"))


@app.route("/api/emergency-batch-trigger", methods=["POST"])
def emergency_batch_trigger():
    """Load the September 2024 flood reference case for Pratappur Mouza."""
    claim_num = len(CLAIMS_LEDGER) + 1
    claim_id = f"PRM-GHT-2026-{claim_num:03d}"

    profile = BargadarClaimProfile(
        claim_id=claim_id,
        cultivator_name="[FICTIONAL DEMO] Cultivator D (Pratappur Reference)",
        father_or_spouse_name="[FICTIONAL DEMO] Parentage D",
        village_mouza="Pratappur",
        gram_panchayat="Birsingha GP",
        jl_number="JL-19",
        khatian_no="KH-DEMO-615",
        plot_dag_no="104",
        cultivator_category="Unrecorded Bargadar (Sec. 21B Statutory Presumption)",
        landowner_raiyat_name="[FICTIONAL DEMO] Raiyat Owner D",
        crop_share_ratio="",
        area_acres=1.80,
        crop_variety="Kharif Aman Paddy",
        bank_account_masked="XXXX-XXXX-DEMO",
        ifsc_code="UCBA0000412",
        dlsa_plv_name="PLV Volunteer #104 (Demo)",
        dlsa_plv_id="DLSA-PMD-PLV-104",
        panchanama_witness_1="Adjacent Cultivator #4 (Plot 105 - Demo)",
        panchanama_witness_2="GP Representative (Birsingha GP - Demo)",
        dpdp_consent_recorded=True,
        dpdp_consent_timestamp_utc=_now_utc_str(),
    )
    _create_and_register_claim(
        profile=profile,
        latitude=GHATAL_LAT,
        longitude=GHATAL_LON,
        inundation_hours_ago=6.5,
    )
    return redirect(url_for("index"))


@app.route("/api/delete-claim/<claim_id>", methods=["POST"])
def delete_claim(claim_id: str):
    """Exercise DPDP Act Right to Erasure: delete claim data & log security retention."""
    for idx, item in enumerate(CLAIMS_LEDGER):
        if item["claim_id"] == claim_id:
            tel = item["telemetry"]
            for path in (
                item.get("pdf_path"),
                item.get("custom_ground_photo_path"),
                tel.sar_artifact.file_path,
                tel.ndvi_artifact.file_path,
                tel.ground_artifact.file_path,
            ):
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            CLAIMS_LEDGER.pop(idx)
            _append_audit_entry(
                claim_id=claim_id,
                action="DPDP_ERASURE",
                reviewer="data_principal",
                note=(
                    "Your claim data will be deleted, subject to 48-hour notice and "
                    "statutory retention of security logs for one year under the DPDP Rules, 2025."
                ),
                timestamp_utc=_now_utc_str(),
            )
            break
    return redirect(url_for("index"))


@app.route("/api/review-action/<claim_id>", methods=["POST"])
def review_action(claim_id: str):
    """Log an authenticated Reviewer action in append-only SQLite storage."""
    if not session.get("reviewer_logged_in"):
        abort(403, description="Reviewer authentication required.")

    action = request.form.get("action", "RETURNED").upper()
    if action not in ("APPROVED", "RETURNED", "ESCALATED"):
        abort(400, description="Invalid review action.")

    note = request.form.get("note", "").strip() or "Reviewed via DLSA Terminal."
    reviewer = session.get("reviewer_user", REVIEWER_USERNAME)
    timestamp = _now_utc_str()

    for item in CLAIMS_LEDGER:
        if item["claim_id"] == claim_id:
            entry = _append_audit_entry(
                claim_id=claim_id,
                action=action,
                reviewer=reviewer,
                note=note,
                timestamp_utc=timestamp,
            )
            item["review_state"] = action
            item["plain_status"] = _plain_status_message(action)
            item["profile"].reviewer_log.append(entry)
            break

    return redirect(url_for("index"))


@app.route("/dossier/<claim_id>", methods=["GET"])
def download_dossier(claim_id: str):
    """Download the PDF dossier (regenerating on-demand if disk was reset)."""
    for item in CLAIMS_LEDGER:
        if item["claim_id"] == claim_id:
            _ensure_claim_files_exist(item)
            pdf_path = item["pdf_path"]
            return send_file(
                pdf_path,
                mimetype="application/pdf",
                as_attachment=True,
                download_name=f"Pramaana_Dossier_{claim_id}.pdf",
            )
    abort(404, description="Dossier not found")


@app.route("/artifact/<claim_id>/<artifact_kind>", methods=["GET"])
def serve_artifact(claim_id: str, artifact_kind: str):
    """Serve SAR, NDVI, or ground PNG artifact (regenerating on demand if needed)."""
    for item in CLAIMS_LEDGER:
        if item["claim_id"] == claim_id:
            _ensure_claim_files_exist(item)
            telemetry = item["telemetry"]
            if artifact_kind == "sar":
                path = telemetry.sar_artifact.file_path
            elif artifact_kind == "ndvi":
                path = telemetry.ndvi_artifact.file_path
            elif artifact_kind == "ground":
                path = telemetry.ground_artifact.file_path
            else:
                abort(400, description="Unknown artifact type")

            if os.path.exists(path):
                return send_file(path, mimetype="image/png")
    abort(404, description="Artifact not found")


@app.route("/api/claims", methods=["GET"])
def api_claims():
    """Return JSON representation of all claims, provenances, and integrity seals."""
    payload = []
    for item in CLAIMS_LEDGER:
        prof = item["profile"]
        tel = item["telemetry"]
        payload.append(
            {
                "claim_id": item["claim_id"],
                "cultivator_name": prof.cultivator_name,
                "cultivator_category": prof.cultivator_category,
                "crop_share_ratio": prof.crop_share_ratio,
                "village_mouza": prof.village_mouza,
                "plot_dag_no": prof.plot_dag_no,
                "coordinates": tel.coordinates_label,
                "acquisition_mode": tel.acquisition_mode,
                "contains_synthetic_demo": tel.contains_synthetic_demo,
                "provenances": {
                    "sar": tel.sar_artifact.provenance,
                    "ndvi": tel.ndvi_artifact.provenance,
                    "ground": tel.ground_artifact.provenance,
                },
                "within_72h_window": tel.within_72h_window,
                "hours_since_inundation": tel.hours_since_inundation,
                "integrity_seals": item["hashes"],
                "review_state": item["review_state"],
                "plain_status": item["plain_status"],
                "reviewer_log": prof.reviewer_log,
                "statutory_citations": [
                    CITATION_BSA_63_4,
                    CITATION_WBLRA_21B,
                    CITATION_PMFBY_72H,
                ],
            }
        )
    return jsonify(
        {
            "status": "ok",
            "gee_authenticated": gee_fetcher.gee_live,
            "gee_auth_error": gee_fetcher.gee_auth_error,
            "count": len(payload),
            "claims": payload,
            "audit_log": _fetch_all_audit_entries(),
            "legal_rules": load_legal_rules(),
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
