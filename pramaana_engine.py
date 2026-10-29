"""Pramaana Legal-Forensic PDF Dossier Engine with Provenance & Watermark Guardrails.

Generates flood crop loss dossiers for Ghatal, Paschim Medinipur (22.6654 N, 87.7218 E)
integrating:
1. Section 63(4) of the Bharatiya Sakshya Adhiniyam (BSA), 2023 (Part A & Part B of The Schedule).
2. Section 21B of the West Bengal Land Reforms Act, 1955 (statutory presumption of bargadar cultivation).
3. Revamped PMFBY Operational Guidelines (72-hour intimation trigger).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from gee_fetcher import EVENT_GRANULE, GhatalTelemetryBundle

GRANULE_NAME = EVENT_GRANULE["granule_name"]

# Exact Statutory Citations (Guardrail: Never alter or summarize)
CITATION_BSA_63_4 = (
    "Section 63(4) of the Bharatiya Sakshya Adhiniyam (BSA), 2023 "
    "(Part A & Part B of The Schedule)."
)
CITATION_WBLRA_21B = (
    "Section 21B of the West Bengal Land Reforms Act, 1955 "
    "(statutory presumption of bargadar cultivation)."
)
CITATION_PMFBY_72H = (
    "Revamped PMFBY Operational Guidelines (72-hour intimation trigger)."
)

WATERMARK_DEMO_TEXT = "DEMO, SYNTHETIC DATA, NOT EVIDENCE"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEGAL_RULES_PATH = os.path.join(BASE_DIR, "legal_rules.json")


def load_legal_rules() -> Dict[str, Any]:
    """Load legal rules and verification status notes from legal_rules.json."""
    if os.path.exists(LEGAL_RULES_PATH):
        with open(LEGAL_RULES_PATH, "r", encoding="utf-8") as rules_file:
            return json.load(rules_file)
    return {}


@dataclass
class BargadarClaimProfile:
    """Cultivator & Bargadar legal standing profile for Ghatal flood claims."""

    claim_id: str
    cultivator_name: str
    father_or_spouse_name: str
    village_mouza: str
    gram_panchayat: str
    jl_number: str
    khatian_no: str
    plot_dag_no: str
    cultivator_category: str
    landowner_raiyat_name: str
    crop_share_ratio: str = ""
    area_acres: float = 1.0
    crop_variety: str = "Kharif Aman Paddy"
    bank_account_masked: str = "XXXX-XXXX-DEMO"
    ifsc_code: str = "PUNB0RRBBGB"
    dlsa_plv_name: str = "DLSA PLV (Demo)"
    dlsa_plv_id: str = "DLSA-PMD-PLV"
    panchanama_witness_1: str = "Witness 1"
    panchanama_witness_2: str = "Witness 2"
    dpdp_consent_recorded: bool = True
    dpdp_consent_timestamp_utc: str = ""
    is_fictional_demo_identity: bool = True
    voice_note_transcript_note: str = "Cultivator voice note logged on capture terminal."
    reviewer_log: List[Dict[str, str]] = field(default_factory=list)


def sha256_file_digest(file_path: str) -> str:
    """Compute SHA-256 integrity seal on a file using hashlib.sha256()."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as file_obj:
        for block in iter(lambda: file_obj.read(8192), b""):
            hasher.update(block)
    return hasher.hexdigest()


def compute_chained_integrity_seals(
    telemetry: GhatalTelemetryBundle,
) -> Dict[str, str]:
    """Compute output integrity seals and compare with client capture-time seals.

    All three evidence artifacts (SAR mask, NDVI map, and ground photo) are
    hashed using hashlib.sha256() before rendering the PDF.
    """
    sar_seal = sha256_file_digest(telemetry.sar_artifact.file_path)
    ndvi_seal = sha256_file_digest(telemetry.ndvi_artifact.file_path)
    ground_seal = sha256_file_digest(telemetry.ground_artifact.file_path)

    telemetry.sar_artifact.sha256_hash = sar_seal
    telemetry.ndvi_artifact.sha256_hash = ndvi_seal
    telemetry.ground_artifact.sha256_hash = ground_seal

    client_photo_hash = (
        telemetry.ground_artifact.client_capture_sha256 or "NOT_PROVIDED_BY_CLIENT"
    )
    server_raw_photo_hash = (
        telemetry.ground_artifact.server_raw_upload_sha256 or "NO_RAW_UPLOAD"
    )
    if telemetry.ground_artifact.upload_hash_verified is True:
        photo_verify_status = "MATCH_VERIFIED_ON_UPLOAD"
    elif telemetry.ground_artifact.upload_hash_verified is False:
        photo_verify_status = "MISMATCH_WARNING"
    else:
        photo_verify_status = "UNVERIFIED_NO_CLIENT_CAPTURE"

    client_voice_hash = telemetry.voice_note_sha256 or "NOT_PROVIDED_BY_CLIENT"

    chain_hasher = hashlib.sha256()
    chain_hasher.update(f"CLIENT_PHOTO:{client_photo_hash}|".encode("utf-8"))
    chain_hasher.update(f"SERVER_RAW_PHOTO:{server_raw_photo_hash}|".encode("utf-8"))
    chain_hasher.update(f"CLIENT_VOICE:{client_voice_hash}|".encode("utf-8"))
    chain_hasher.update(f"SAR_OUTPUT_SEAL:{sar_seal}|".encode("utf-8"))
    chain_hasher.update(f"NDVI_OUTPUT_SEAL:{ndvi_seal}|".encode("utf-8"))
    chain_hasher.update(f"GROUND_OUTPUT_SEAL:{ground_seal}|".encode("utf-8"))
    chain_hasher.update(
        f"PROVENANCES:{telemetry.sar_artifact.provenance},"
        f"{telemetry.ndvi_artifact.provenance},"
        f"{telemetry.ground_artifact.provenance}|".encode("utf-8")
    )
    chain_hasher.update(telemetry.inundation_timestamp_utc.encode("utf-8"))
    chain_hasher.update(telemetry.intimation_timestamp_utc.encode("utf-8"))

    return {
        "sar_sha256": sar_seal,
        "ndvi_sha256": ndvi_seal,
        "ground_sha256": ground_seal,
        "client_photo_sha256": client_photo_hash,
        "server_raw_photo_sha256": server_raw_photo_hash,
        "photo_upload_hash_status": photo_verify_status,
        "client_voice_sha256": client_voice_hash,
        "composite_bundle_sha256": chain_hasher.hexdigest(),
    }


verify_and_hash_evidence_artifacts = compute_chained_integrity_seals


def _draw_demo_watermark(pdf_canvas: canvas.Canvas, _doc: Any) -> None:
    """Draw a large diagonal 'DEMO, SYNTHETIC DATA, NOT EVIDENCE' watermark."""
    pdf_canvas.saveState()
    pdf_canvas.setFont("Helvetica-Bold", 28)
    pdf_canvas.setFillColor(colors.Color(0.85, 0.1, 0.1, alpha=0.22))
    pdf_canvas.translate(A4[0] / 2.0, A4[1] / 2.0)
    pdf_canvas.rotate(38)
    pdf_canvas.drawCentredString(0, 18, WATERMARK_DEMO_TEXT)
    pdf_canvas.drawCentredString(0, -22, "VOID FOR LEGAL / INSURER SUBMISSION")
    pdf_canvas.restoreState()


def _draw_standard_footer(pdf_canvas: canvas.Canvas, _doc: Any) -> None:
    """Draw standard page footer when no synthetic demo artifacts are present."""
    pdf_canvas.saveState()
    pdf_canvas.setFont("Helvetica", 7.5)
    pdf_canvas.setFillColor(colors.HexColor("#475569"))
    pdf_canvas.drawString(
        16 * mm,
        8 * mm,
        "Pramaana Flood Claim Dossier — Draft Pending Signature — "
        "Integrity Seals Computed on Generated Outputs",
    )
    pdf_canvas.restoreState()


class PramaanaPDFGenerator:
    """Generates the Flood Claim Dossier PDF with strict provenance watermarking."""

    def __init__(self, output_dir: str = "dossiers") -> None:
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_dossier(
        self,
        profile: BargadarClaimProfile,
        telemetry: GhatalTelemetryBundle,
        output_filename: Optional[str] = None,
    ) -> str:
        """Hash artifacts with hashlib.sha256() and render the PDF dossier."""
        hashes = compute_chained_integrity_seals(telemetry)
        rules = load_legal_rules()
        is_demo = telemetry.contains_synthetic_demo

        if not output_filename:
            output_filename = f"Pramaana_Dossier_{profile.claim_id}.pdf"
        pdf_path = os.path.join(self.output_dir, output_filename)

        doc_title = (
            f"DEMO SYNTHETIC OUTPUT (NOT EVIDENCE) - {profile.claim_id}"
            if is_demo
            else f"Pramaana Flood Claim Dossier (Pending Signature) - {profile.claim_id}"
        )

        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
            title=doc_title,
            author="Pramaana AI-Legal Flood Claim Engine (Ghatal Subdivision)",
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "PramaanaTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#0F172A"),
            spaceAfter=3,
        )
        subtitle_style = ParagraphStyle(
            "PramaanaSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12.5,
            textColor=colors.HexColor("#1E3A8A"),
            spaceAfter=6,
        )
        demo_banner_style = ParagraphStyle(
            "PramaanaDemoBanner",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13.5,
            textColor=colors.white,
            backColor=colors.HexColor("#991B1B"),
            borderPadding=6,
            spaceBefore=2,
            spaceAfter=8,
        )
        section_style = ParagraphStyle(
            "PramaanaSection",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13.5,
            textColor=colors.HexColor("#0F172A"),
            backColor=colors.HexColor("#E2E8F0"),
            borderPadding=4,
            spaceBefore=8,
            spaceAfter=5,
        )
        body_style = ParagraphStyle(
            "PramaanaBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#1E293B"),
            spaceAfter=4,
        )
        citation_style = ParagraphStyle(
            "PramaanaCitation",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.4,
            leading=12,
            textColor=colors.HexColor("#7C2D12"),
            backColor=colors.HexColor("#FEF3C7"),
            borderPadding=5,
            spaceBefore=3,
            spaceAfter=5,
        )
        mono_style = ParagraphStyle(
            "PramaanaMono",
            parent=styles["Normal"],
            fontName="Courier",
            fontSize=7.2,
            leading=9.6,
            textColor=colors.HexColor("#0F172A"),
        )

        story = []

        header_label = (
            "PRAMAANA: FLOOD CLAIM DOSSIER [SYNTHETIC DEMO OUTPUT — NOT EVIDENCE]"
            if is_demo
            else "PRAMAANA: FLOOD CLAIM DOSSIER [DRAFT — PENDING SIGNATURE]"
        )
        story.append(Paragraph(header_label, title_style))
        story.append(
            Paragraph(
                "SUB-DIVISIONAL LEGAL SERVICES &amp; PMFBY CLAIM ASSISTANCE CELL — "
                "GHATAL, PASCHIM MEDINIPUR (22.6654 N, 87.7218 E)",
                subtitle_style,
            )
        )
        story.append(
            HRFlowable(
                width="100%",
                thickness=1.5,
                color=colors.HexColor("#1E3A8A"),
                spaceAfter=6,
            )
        )

        if is_demo:
            story.append(
                Paragraph(
                    f"<b>{WATERMARK_DEMO_TEXT}:</b> One or more artifacts in this bundle "
                    "have provenance <b>synthetic_demo</b>. This document is for software "
                    "demonstration only, carries no evidentiary weight, and its BSA Section "
                    "63(4) certificate is <b>VOID</b>.",
                    demo_banner_style,
                )
            )

        # Legal source text comes only from legal_rules.json (no hard-coded fallback text)
        citations = rules["statutory_citations"]
        wblra = citations["wblra_section_21b"]
        pmfby = citations["pmfby_72h_trigger"]
        bsa = citations["bsa_section_63_4"]

        wblra_note = (
            f"<i>\"{wblra['verbatim_section_text']}\"</i><br/>"
            f"Insertion: {wblra['insertion_history']} "
            f"Source: {wblra['verified_against']}"
        )
        support_lines = "".join(
            f"<br/>• Cl. {c['clause']}: {c['summary']}"
            for c in pmfby["supporting_clauses"]
        )
        pmfby_note = (
            f"{pmfby['document_title']}, cl. {pmfby['primary_clause']['clause']}: "
            f"<i>\"{pmfby['primary_clause']['text']}\"</i>"
            f"{support_lines}"
        )

        story.append(
            Paragraph(
                "<b>STATUTORY CITATIONS &amp; LEGAL VERIFICATION NOTES:</b><br/>"
                f"1. {CITATION_BSA_63_4}<br/>"
                f"2. {CITATION_WBLRA_21B}<br/>"
                f"3. {CITATION_PMFBY_72H}",
                citation_style,
            )
        )

        # Section 1: 72-Hour Intimation Trigger & Claim Summary
        story.append(
            Paragraph(
                f"I. LOCALIZED CALAMITY INTIMATION LEDGER — {CITATION_PMFBY_72H}",
                section_style,
            )
        )
        window_status = (
            "WITHIN 72-HOUR INTIMATION WINDOW"
            if telemetry.within_72h_window
            else "BEYOND 72 HOURS (REQUIRES SUBMERGENCE DELAY EXPLANATION)"
        )
        share_display = (
            profile.crop_share_ratio.strip()
            if profile.crop_share_ratio and profile.crop_share_ratio.strip()
            else "Not specified (depends on input supply under WBLRA)"
        )

        deadlines = rules["deadlines"]
        summary_data = [
            ["Claim Dossier ID", profile.claim_id, "Subdivision", "Ghatal, Paschim Medinipur"],
            [
                "Coordinates (WGS84)",
                telemetry.coordinates_label,
                "S1 Acquisition (UTC)",
                telemetry.inundation_timestamp_utc,
            ],
            [
                "SAR Backscatter",
                f"{telemetry.sar_vv_db} dB | {telemetry.flood_inundation_pct:.1f}% flood "
                f"(+{telemetry.uncertain_pct or 0:.1f}% uncertain, excluded)",
                "NDVI Change",
                f"{telemetry.ndvi_pre_flood} to {telemetry.ndvi_post_flood} "
                f"(-{telemetry.estimated_crop_loss_pct:.1f}%)",
            ],
            [
                "Simulated Elapsed",
                f"{telemetry.hours_since_inundation:.2f} Hours",
                f"Intimation (cl. {pmfby['primary_clause']['clause']})",
                window_status,
            ],
            [
                "Complete Details",
                f"Within {deadlines['complete_details_days']} days (cl. 21.5.6.1)",
                "Bank/Official Forward",
                f"Within {deadlines['bank_or_official_forwarding_hours']} h (cl. 21.5.5.6)",
            ],
            [
                "Artifact Provenances",
                f"SAR: {telemetry.sar_artifact.provenance}",
                f"NDVI: {telemetry.ndvi_artifact.provenance}",
                f"Ground: {telemetry.ground_artifact.provenance}",
            ],
        ]
        summary_table = Table(
            summary_data,
            colWidths=[36 * mm, 52 * mm, 40 * mm, 50 * mm],
        )
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F5F9")),
                    ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F1F5F9")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0F172A")),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("PADDING", (0, 0), (-1, -1), 3.5),
                ]
            )
        )
        story.append(summary_table)
        story.append(Spacer(1, 4))
        sar_image_note = (
            "The SAR image in this dossier is a synthetic illustration; the granule "
            "below is the record a live run must use."
            if telemetry.sar_artifact.provenance == "synthetic_demo"
            else "The SAR image was rendered by Earth Engine from this granule."
        )
        story.append(
            Paragraph(
                f"<b>Sentinel-1 granule:</b> <font name='Courier' size='7.2'>"
                f"{GRANULE_NAME}</font> (Copernicus catalogue). {sar_image_note}<br/>"
                f"<b>PMFBY source:</b> {pmfby_note}<br/>"
                f"<b>{telemetry.uncertainty_note}</b>",
                body_style,
            )
        )

        # Section 2: Bargadar Inclusion Layer (Section 21B WBLRA 1955)
        story.append(
            Paragraph(
                f"II. BARGADAR INCLUSION &amp; TENANCY PRESUMPTION — {CITATION_WBLRA_21B}",
                section_style,
            )
        )
        bargadar_data = [
            ["Claimant Name", profile.cultivator_name, "Father / Spouse", profile.father_or_spouse_name],
            ["Tenancy Category", profile.cultivator_category, "Recorded Raiyat", profile.landowner_raiyat_name],
            ["Mouza & JL No.", f"{profile.village_mouza} ({profile.jl_number})", "Gram Panchayat", profile.gram_panchayat],
            ["Khatian & Dag No.", f"{profile.khatian_no} / Dag #{profile.plot_dag_no}", "Cultivated Area", f"{profile.area_acres:.2f} Acres ({profile.crop_variety})"],
            ["Crop-Share Ratio", share_display, "DPDP Act Consent", f"Recorded ({profile.dpdp_consent_timestamp_utc or 'Active'})"],
            ["DLSA Assisting PLV", f"{profile.dlsa_plv_name} ({profile.dlsa_plv_id})", "Panchanama Witnesses", f"{profile.panchanama_witness_1}, {profile.panchanama_witness_2}"],
        ]
        bargadar_table = Table(
            bargadar_data,
            colWidths=[36 * mm, 52 * mm, 40 * mm, 50 * mm],
        )
        bargadar_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#ECFEFF")),
                    ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#ECFEFF")),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#99F6E4")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("PADDING", (0, 0), (-1, -1), 3.5),
                ]
            )
        )
        story.append(bargadar_table)
        story.append(Spacer(1, 4))
        story.append(
            Paragraph(
                f"<b>Section 21B text ({CITATION_WBLRA_21B}):</b> {wblra_note}",
                body_style,
            )
        )

        # Section 3: Capture-Time Integrity Seals & Server Re-Hash Verification
        story.append(
            Paragraph(
                "III. CAPTURE-TIME SEALS &amp; SERVER OUTPUT INTEGRITY SEALS (hashlib.sha256)",
                section_style,
            )
        )
        story.append(
            Paragraph(
                "<b>Methodological Note:</b> Browser-computed hashes are <i>capture-time "
                "integrity seals</i>; upon upload, the server independently recomputes "
                "the SHA-256 hash of the raw uploaded file and compares it against the "
                "browser seal. Hashes on server-rendered PNGs are <i>integrity seals on "
                "generated outputs</i>.",
                body_style,
            )
        )
        hash_rows = [
            ["Record / Output Layer", "Verification / Provenance", "SHA-256 Digest (64-Char Hex)"],
            [
                "Client Capture Seal (Photo)",
                hashes["photo_upload_hash_status"],
                Paragraph(hashes["client_photo_sha256"], mono_style),
            ],
            [
                "Server Raw Upload Re-Hash",
                telemetry.ground_artifact.provenance,
                Paragraph(hashes["server_raw_photo_sha256"], mono_style),
            ],
            [
                "Client Capture Seal (Voice)",
                "farmer_capture" if telemetry.voice_note_sha256 else "none",
                Paragraph(hashes["client_voice_sha256"], mono_style),
            ],
            [
                "Output Seal: SAR Mask PNG",
                telemetry.sar_artifact.provenance,
                Paragraph(hashes["sar_sha256"], mono_style),
            ],
            [
                "Output Seal: NDVI Map PNG",
                telemetry.ndvi_artifact.provenance,
                Paragraph(hashes["ndvi_sha256"], mono_style),
            ],
            [
                "Output Seal: Ground Image PNG",
                telemetry.ground_artifact.provenance,
                Paragraph(hashes["ground_sha256"], mono_style),
            ],
            [
                "Chained Bundle Seal",
                "chained_seal",
                Paragraph(hashes["composite_bundle_sha256"], mono_style),
            ],
        ]
        hash_table = Table(
            hash_rows,
            colWidths=[44 * mm, 38 * mm, 96 * mm],
        )
        hash_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.6),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("PADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(hash_table)

        # Page 2: Visual Exhibits & Section 63(4) Certificate (or VOID Notice)
        story.append(PageBreak())

        if is_demo:
            story.append(
                Paragraph(
                    f"{WATERMARK_DEMO_TEXT} — VISUAL OUTPUTS &amp; VOID CERTIFICATE",
                    demo_banner_style,
                )
            )

        story.append(
            Paragraph(
                "IV. SATELLITE &amp; FIELD VISUAL EXHIBITS (WITH PROVENANCE TAGS)",
                section_style,
            )
        )

        sar_img = RLImage(telemetry.sar_artifact.file_path, width=85 * mm, height=54 * mm)
        ndvi_img = RLImage(telemetry.ndvi_artifact.file_path, width=85 * mm, height=54 * mm)
        ground_img = RLImage(telemetry.ground_artifact.file_path, width=85 * mm, height=54 * mm)

        exhibit_meta = Paragraph(
            f"<b>Provenance &amp; Upload Verification:</b><br/>"
            f"• SAR Provenance: <b>{telemetry.sar_artifact.provenance}</b><br/>"
            f"• NDVI Provenance: <b>{telemetry.ndvi_artifact.provenance}</b><br/>"
            f"• Ground Provenance: <b>{telemetry.ground_artifact.provenance}</b><br/>"
            f"• Raw Upload Re-Hash Check: <b>{hashes['photo_upload_hash_status']}</b><br/>"
            f"• Coordinates: {telemetry.coordinates_label}<br/>"
            f"• Mouza: {profile.village_mouza} (Dag #{profile.plot_dag_no})",
            body_style,
        )

        img_grid = Table(
            [
                [
                    Paragraph(
                        f"<b>Exhibit A: SAR Mask ({telemetry.sar_artifact.provenance})</b>",
                        body_style,
                    ),
                    Paragraph(
                        f"<b>Exhibit B: NDVI Map ({telemetry.ndvi_artifact.provenance})</b>",
                        body_style,
                    ),
                ],
                [sar_img, ndvi_img],
                [
                    Paragraph(
                        f"<b>Exhibit C: Ground Photo ({telemetry.ground_artifact.provenance})</b>",
                        body_style,
                    ),
                    Paragraph("<b>Exhibit Provenance &amp; Notes</b>", body_style),
                ],
                [ground_img, exhibit_meta],
            ],
            colWidths=[89 * mm, 89 * mm],
        )
        img_grid.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(img_grid)

        story.append(
            Paragraph(
                f"V. ELECTRONIC RECORD CERTIFICATE — {CITATION_BSA_63_4}",
                section_style,
            )
        )

        if is_demo:
            void_box = Table(
                [
                    [
                        Paragraph(
                            f"<b>CERTIFICATE VOID / DISABLED ({WATERMARK_DEMO_TEXT})</b><br/><br/>"
                            f"This dossier contains one or more artifacts with provenance "
                            f"<b>synthetic_demo</b> (SAR: <b>{telemetry.sar_artifact.provenance}</b>, "
                            f"NDVI: <b>{telemetry.ndvi_artifact.provenance}</b>, "
                            f"Ground: <b>{telemetry.ground_artifact.provenance}</b>).<br/><br/>"
                            f"A certificate under <b>{CITATION_BSA_63_4}</b> cannot be executed "
                            "for synthetic demonstration data. To generate a valid draft "
                            "certificate for signature, run with authenticated live Sentinel "
                            "telemetry (<b>live_sentinel</b>) and an on-device farmer capture "
                            "(<b>farmer_capture</b>).",
                            body_style,
                        )
                    ]
                ],
                colWidths=[178 * mm],
            )
            void_box.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF2F2")),
                        ("BOX", (0, 0), (-1, -1), 1.5, colors.HexColor("#DC2626")),
                        ("PADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            story.append(void_box)
        else:
            case_ref = bsa["case_reference"]
            part_a_text = (
                "<b>PART A — SCHEDULE TO THE BSA, 2023 (DRAFT — PENDING SIGNATURE):</b><br/>"
                f"Signatory: {bsa['part_a_signatory']}<br/>"
                f"Person in charge: <b>{profile.dlsa_plv_name}</b> ({profile.dlsa_plv_id}), "
                f"on behalf of <b>{profile.cultivator_name}</b>.<br/>"
                f"Records: Sentinel-1 granule <font name='Courier' size='7'>{GRANULE_NAME}</font> "
                f"(acquired {telemetry.inundation_timestamp_utc}); field photograph "
                f"(upload check: <b>{hashes['photo_upload_hash_status']}</b>).<br/>"
                f"• SAR output SHA-256: <font name='Courier' size='7'>{hashes['sar_sha256']}</font><br/>"
                f"• Field photo capture SHA-256: <font name='Courier' size='7'>{hashes['client_photo_sha256']}</font><br/>"
                "<b>Signature Status: PENDING SIGNATURE ___________________________</b>"
            )
            part_b_text = (
                "<b>PART B — SCHEDULE TO THE BSA, 2023 (DRAFT — PENDING SIGNATURE):</b><br/>"
                f"Signatory: {bsa['part_b_signatory']}<br/>"
                "Statement: Server recomputed SHA-256 on raw upload and generated output "
                "integrity seals via <b>hashlib.sha256()</b>:<br/>"
                f"• Client Capture Photo Seal: <font name='Courier' size='7'>{hashes['client_photo_sha256']}</font><br/>"
                f"• Server Raw Upload Re-Hash: <font name='Courier' size='7'>{hashes['server_raw_photo_sha256']}</font><br/>"
                f"• Chained Bundle Seal: <font name='Courier' size='7'>{hashes['composite_bundle_sha256']}</font><br/>"
                "<b>Signature Status: PENDING SIGNATURE ___________________________</b>"
            )
            footnote_text = (
                f"<b>Note on Part B:</b> {bsa['footnote_text']} "
                f"See {case_ref['reported_name']} (reported decision date "
                f"{case_ref['reported_decision_date']})."
            )
            bsa_table = Table(
                [
                    [Paragraph(part_a_text, body_style)],
                    [Paragraph(part_b_text, body_style)],
                    [Paragraph(footnote_text, body_style)],
                ],
                colWidths=[178 * mm],
            )
            bsa_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F8FAFC")),
                        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#EFF6FF")),
                        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#1E3A8A")),
                        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
                        ("PADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.append(bsa_table)

        page_callback = _draw_demo_watermark if is_demo else _draw_standard_footer
        doc.build(story, onFirstPage=page_callback, onLaterPages=page_callback)
        return pdf_path
