"""Case dossier PDF generator for the Pramaana case workflow.

Builds the dossier only from persisted records. It never pre-fills
signatories, never states that a certificate is completed, and prints
"SYNTHETIC DEMONSTRATION — NOT REAL EVIDENCE" on every page of synthetic cases.
The legacy generator (`pramaana_engine.PramaanaPDFGenerator`) is unchanged.
"""

from __future__ import annotations

import io
import os
from typing import Any, Callable, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

DOSSIER_GENERATOR_VERSION = "pramaana-dossier-2.0.0"
SYNTHETIC_WATERMARK = "SYNTHETIC DEMONSTRATION — NOT REAL EVIDENCE"
PRODUCT_LINE = "PRAMAANA — AI-Assisted Agricultural Flood Evidence & Claim-Preparation System"
NOT_OFFICIAL_LINE = (
    "Prepared document. Not an insurance claim, official certificate, government record or "
    "decision. Pramaana is not affiliated with any court, DLSA, insurer or government body."
)


def _register_unicode_font() -> Optional[str]:
    """Register a system font with Bengali glyphs, if one is available.

    ReportLab does not shape Indic scripts, so conjuncts may still render
    imperfectly; the case record in the app remains the reference text.
    """
    candidates: List[Tuple[str, Optional[int]]] = [
        (r"C:\Windows\Fonts\Nirmala.ttc", 0),
        (r"C:\Windows\Fonts\Nirmala.ttf", None),
        ("/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf", None),
    ]
    for path, idx in candidates:
        if os.path.exists(path):
            try:
                font = TTFont("PramaanaUnicode", path) if idx is None else TTFont(
                    "PramaanaUnicode", path, subfontIndex=idx)
                pdfmetrics.registerFont(font)
                return "PramaanaUnicode"
            except Exception:
                continue
    return None


UNICODE_FONT = _register_unicode_font()


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    """Paragraph with escaped user text; switches font for non-Latin text."""
    raw = "—" if text is None or text == "" else str(text)
    safe = xml_escape(raw).replace("\n", "<br/>")
    if UNICODE_FONT and any(0x0900 <= ord(ch) <= 0x0DFF for ch in raw):
        safe = f"<font name='{UNICODE_FONT}'>{safe}</font>"
    return Paragraph(safe, style)


class _NumberedCanvas(canvas.Canvas):
    """Canvas that writes 'Page X of Y', a footer and the synthetic watermark."""

    footer_text = ""
    synthetic = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_pages: List[Dict[str, Any]] = []

    def showPage(self) -> None:  # noqa: N802 (ReportLab API)
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total: int) -> None:
        width, height = A4
        self.saveState()
        if self.synthetic:
            self.saveState()
            self.setFont("Helvetica-Bold", 26)
            self.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.18))
            self.translate(width / 2, height / 2)
            self.rotate(40)
            self.drawCentredString(0, 14, "SYNTHETIC DEMONSTRATION")
            self.drawCentredString(0, -20, "NOT REAL EVIDENCE")
            self.restoreState()
            self.setFillColor(colors.HexColor("#991B1B"))
            self.rect(0, height - 9 * mm, width, 9 * mm, stroke=0, fill=1)
            self.setFillColor(colors.white)
            self.setFont("Helvetica-Bold", 9)
            self.drawCentredString(width / 2, height - 6 * mm, SYNTHETIC_WATERMARK)
        self.setFont("Helvetica", 7)
        self.setFillColor(colors.HexColor("#475569"))
        self.drawString(16 * mm, 8 * mm, self.footer_text)
        self.drawRightString(width - 16 * mm, 8 * mm, f"Page {self._pageNumber} of {total}")
        self.restoreState()


def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Heading1"], fontName="Helvetica-Bold",
                                fontSize=15, leading=19, textColor=colors.HexColor("#0F172A"),
                                spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontName="Helvetica", fontSize=8.5,
                              leading=11.5, textColor=colors.HexColor("#1E3A8A"), spaceAfter=4),
        "h": ParagraphStyle("h", parent=base["Heading2"], fontName="Helvetica-Bold",
                            fontSize=10.5, leading=13.5, textColor=colors.HexColor("#0F172A"),
                            backColor=colors.HexColor("#E2E8F0"), borderPadding=(3, 4, 3, 4),
                            spaceBefore=9, spaceAfter=5),
        "body": ParagraphStyle("b", parent=base["Normal"], fontName="Helvetica", fontSize=8.4,
                               leading=11.4, textColor=colors.HexColor("#1E293B"), spaceAfter=3),
        "cell": ParagraphStyle("c", parent=base["Normal"], fontName="Helvetica", fontSize=7.8,
                               leading=10, textColor=colors.HexColor("#0F172A")),
        "cellb": ParagraphStyle("cb", parent=base["Normal"], fontName="Helvetica-Bold",
                                fontSize=7.8, leading=10, textColor=colors.HexColor("#0F172A")),
        "mono": ParagraphStyle("m", parent=base["Normal"], fontName="Courier", fontSize=6.4,
                               leading=8.2, textColor=colors.HexColor("#0F172A")),
        "warn": ParagraphStyle("w", parent=base["Normal"], fontName="Helvetica-Bold",
                               fontSize=8.4, leading=11.4, textColor=colors.HexColor("#7C2D12"),
                               backColor=colors.HexColor("#FEF3C7"), borderPadding=5,
                               spaceBefore=3, spaceAfter=7),
        "danger": ParagraphStyle("d", parent=base["Normal"], fontName="Helvetica-Bold",
                                 fontSize=9.5, leading=12.5, textColor=colors.white,
                                 backColor=colors.HexColor("#991B1B"), borderPadding=6,
                                 spaceBefore=2, spaceAfter=9),
    }


def _kv_table(rows: List[List[Any]], st: Dict[str, ParagraphStyle],
              widths: Tuple[float, float] = (48 * mm, 130 * mm)) -> Table:
    data = [[_p(k, st["cellb"]), v if isinstance(v, Paragraph) else _p(v, st["cell"])]
            for k, v in rows]
    t = Table(data, colWidths=list(widths))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F5F9")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _grid_table(header: List[str], rows: List[List[Any]], widths: List[float],
                st: Dict[str, ParagraphStyle]) -> Table:
    data = [[_p(h, st["cellb"]) for h in header]]
    for r in rows:
        data.append([c if isinstance(c, Paragraph) else _p(c, st["cell"]) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#CBD5E1")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94A3B8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return t


def _photo_flowable(path: str, max_w: float, max_h: float) -> Optional[RLImage]:
    try:
        from PIL import Image as PILImage
        with PILImage.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((900, 900))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=80)
            w, h = im.size
        buf.seek(0)
        scale = min(max_w / w, max_h / h)
        return RLImage(buf, width=w * scale, height=h * scale)
    except Exception:
        return None


def generate_case_dossier(
    output_path: str,
    doc_id: str,
    version: int,
    case: Dict[str, Any],
    evidence: List[Dict[str, Any]],
    analyses: List[Dict[str, Any]],
    audit: List[Dict[str, Any]],
    deadline: Dict[str, Any],
    gaps: List[str],
    legal_rules: Dict[str, Any],
    labels: Dict[str, Dict[str, str]],
    resolve_path: Callable[[Optional[str]], Optional[str]],
    generated_at_utc: str,
    generated_by: str,
) -> str:
    """Render a case dossier PDF to `output_path` and return the path."""
    st = _styles()
    synthetic = case["record_type"] == "synthetic_demo"
    field_test = case["record_type"] == "field_test"

    def label(group: str, key: Any) -> str:
        return labels.get(group, {}).get(key or "", key or "—")

    story: List[Any] = []
    story.append(Paragraph("PRAMAANA — Flood Evidence &amp; Claim-Preparation Dossier", st["title"]))
    story.append(_p(PRODUCT_LINE, st["sub"]))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#1E3A8A"),
                            spaceAfter=5))
    if synthetic:
        story.append(_p(
            f"{SYNTHETIC_WATERMARK}. Every identity, location, photograph and satellite value in "
            "this document is fictional and was generated for software demonstration. It must "
            "not be submitted to any insurer, authority or court.", st["danger"]))
    elif field_test:
        story.append(_p(
            "FIELD USABILITY TEST RECORD — collected to test the software with the participant's "
            "consent. Not prepared for submission.", st["warn"]))
    story.append(_p(NOT_OFFICIAL_LINE, st["warn"]))

    # 1. Identification
    story.append(Paragraph("1. Document identification", st["h"]))
    story.append(_kv_table([
        ["Case ID", case["case_id"]],
        ["Record type", label("record_type", case["record_type"])],
        ["Document ID / version", f"{doc_id} / v{version}"],
        ["Generated (UTC)", generated_at_utc],
        ["Generated by (authenticated reviewer)", generated_by],
        ["Generator version", DOSSIER_GENERATOR_VERSION],
        ["Case status at generation", label("status", case["status"])],
        ["Case created (UTC, server clock)", case["created_at_utc"]],
        ["Document hash", "The SHA-256 of this PDF is recorded in Pramaana at generation time. "
                          "A hash cannot be printed inside the file it describes; use the "
                          "'Verify a file' page to compare a copy against the record."],
    ], st))

    # 2. Claimant
    story.append(Paragraph("2. Claimant-provided details (not independently verified)", st["h"]))
    if case.get("erased_at_utc"):
        story.append(_p(f"Personal details were erased on {case['erased_at_utc']} at the "
                        "claimant's request.", st["body"]))
    story.append(_kv_table([
        ["Claimant name", case.get("claimant_name")],
        ["Father / spouse name", case.get("guardian_name")],
        ["Contact phone", mask_phone(case.get("phone"))],
        ["Assisted by (field operator)", case.get("assisted_by")],
        ["Consent recorded", f"{'Yes' if case.get('consent_given') else 'No'} — "
                             f"{case.get('consent_at_utc') or ''} (consent text "
                             f"{case.get('consent_version') or '—'})"],
    ], st))

    # 3. Location
    story.append(Paragraph("3. Field location", st["h"]))
    coords = ("Not recorded" if case.get("latitude") is None
              else f"{case['latitude']:.6f} N, {case['longitude']:.6f} E (WGS84)")
    story.append(_kv_table([
        ["Coordinates", coords],
        ["Location source", label("location_source", case.get("location_source"))],
        ["Reported GPS accuracy", f"±{case['location_accuracy_m']:.0f} m"
            if case.get("location_accuracy_m") else "Not reported"],
        ["Location recorded at (UTC)", case.get("location_captured_at_utc")],
        ["Village / mouza", case.get("village")],
        ["Gram panchayat / block / district",
         " / ".join(x or "—" for x in (case.get("gram_panchayat"), case.get("block"),
                                       case.get("district")))],
        ["JL no. / khatian no. / dag (plot) no.",
         " / ".join(x or "—" for x in (case.get("jl_number"), case.get("khatian_no"),
                                       case.get("plot_dag_no")))],
    ], st))
    story.append(_p("Administrative names and land-record numbers are as reported by the "
                    "claimant and have not been checked against official land records.", st["body"]))

    # 4. Crop, incident and deadline
    story.append(Paragraph("4. Crop, reported damage and intimation timeline", st["h"]))
    deadline_text = deadline["message"]
    if deadline.get("is_simulated"):
        deadline_text += " (Synthetic demonstration case — simulated timeline.)"
    story.append(_kv_table([
        ["Crop / season", f"{case.get('crop') or '—'} / {case.get('season') or '—'}"],
        ["Reported area", f"{case['area_acres']} acres" if case.get("area_acres") else None],
        ["Reported incident start",
         f"{case.get('incident_date') or '—'} {case.get('incident_time') or '(time not given)'} IST"],
        ["Type of damage (reported)", label("damage_type", case.get("damage_type"))],
        ["Damage description (reported)", case.get("damage_description")],
        ["Portion affected (claimant estimate)",
         f"{case['reported_affected_pct']:.0f}%" if case.get("reported_affected_pct") is not None
         else None],
        ["Insurance / relief scheme (reported)", deadline["scheme_label"]],
        ["Intimation already made? (reported)", label("intimation_status", case.get("intimation_status"))],
        ["Intimation reference (reported)", case.get("intimation_reference")],
        ["Deadline assessment", deadline_text],
        ["Deadline rule source", deadline.get("source") or "None configured"],
    ], st))

    # 5. Evidence inventory
    story.append(Paragraph("5. Evidence inventory and integrity", st["h"]))
    story.append(_p(
        "SHA-256 values are computed by the server from the exact stored bytes. A later MATCH "
        "means the stored file is unchanged since it was recorded. It does not establish who "
        "created the file, when or where a photograph was taken, or that its content is true. "
        "Embedded photo metadata (EXIF) can be edited and is shown only as unverified.", st["body"]))
    ev_rows = []
    for ev in evidence:
        verify = ev.get("last_verification_result") or "Not yet checked"
        if ev.get("last_verified_at_utc"):
            verify += f" ({ev['last_verified_at_utc']})"
        browser = {1: "browser hash matched", 0: "browser hash DID NOT match"}.get(
            ev.get("client_hash_match"), "no browser hash")
        ev_rows.append([
            ev["evidence_id"],
            f"{label('evidence_kind', ev['kind'])} — {label('provenance', ev['provenance'])}",
            f"{ev.get('original_filename') or '—'} ({fmt_size(ev.get('size_bytes'))}); "
            f"uploaded {ev['uploaded_at_utc']}; embedded time (unverified): "
            f"{ev.get('embedded_capture_time') or 'none'}; {browser}",
            _p(ev["sha256"], st["mono"]),
            verify if ev["status"] == "active" else "ERASED",
        ])
    if ev_rows:
        story.append(_grid_table(["Evidence ID", "Type / source", "Details", "SHA-256", "Last check"],
                                 ev_rows, [24 * mm, 30 * mm, 52 * mm, 44 * mm, 28 * mm], st))
    else:
        story.append(_p("No evidence files are attached to this case.", st["body"]))

    images = [e for e in evidence if e["status"] == "active" and e["kind"] in
              ("photo", "satellite_rendering", "synthetic_placeholder")]
    cells: List[Tuple[Any, Paragraph]] = []
    for ev in images[:6]:
        path = resolve_path(ev.get("stored_path"))
        img = _photo_flowable(path, 82 * mm, 58 * mm) if path and os.path.exists(path) else None
        cap = _p(f"{ev['evidence_id']} — {label('evidence_kind', ev['kind'])} — "
                 f"{label('provenance', ev['provenance'])}", st["cell"])
        cells.append((img or _p("(image could not be rendered)", st["cell"]), cap))
    if cells:
        blank = (Spacer(1, 1), Spacer(1, 1))
        rows = []
        for i in range(0, len(cells), 2):
            left = cells[i]
            right = cells[i + 1] if i + 1 < len(cells) else blank
            rows.append([left[0], right[0]])
            rows.append([left[1], right[1]])
        grid = Table(rows, colWidths=[89 * mm, 89 * mm])
        grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                  ("PADDING", (0, 0), (-1, -1), 3)]))
        story.append(Spacer(1, 4))
        story.append(grid)

    # 6. Satellite
    story.append(Paragraph("6. Satellite observations", st["h"]))
    if not analyses:
        story.append(_p("No satellite analysis has been run for this case.", st["body"]))
    for an in analyses:
        rec = an["record"]
        story.append(_p(f"Analysis {an['analysis_id']} — requested {an['requested_at_utc']} by "
                        f"{an['requested_by']} — status: {rec['status'].upper()} — source: "
                        f"{label('provenance', rec['provenance'])} — version "
                        f"{rec.get('analysis_version')}", st["cellb"]))
        story.append(_p(rec.get("message") or "", st["body"]))
        for sensor in ("sentinel1", "sentinel2"):
            data = rec.get(sensor)
            if data:
                story.append(_kv_table(_sensor_rows(sensor, data), st, (40 * mm, 138 * mm)))
                story.append(Spacer(1, 3))
    limitations = analyses[-1]["record"].get("limitations") if analyses else None
    if limitations:
        story.append(_p("Limitations of the satellite indicators:", st["cellb"]))
        for lim in limitations:
            story.append(_p(f"• {lim}", st["body"]))

    # 7. Tenancy
    story.append(Paragraph("7. Tenancy / cultivation information", st["h"]))
    story.append(_kv_table([
        ["Tenancy category (claimant-provided)", label("tenancy", case.get("tenancy_category"))],
        ["Landowner (claimant-provided)", case.get("landowner_name")],
        ["Supporting records described", case.get("tenancy_documents")],
        ["Review status", label("tenancy_review", case.get("tenancy_review_status"))],
    ], st))
    story.append(_p("Pramaana does not determine whether a person is a bargadar or any other "
                    "tenancy category. That is a legal question for the competent authority.",
                    st["body"]))

    # 8. Certificate preparation (never a completed certificate)
    story.append(Paragraph(
        "8. Electronic-record certificate — preparation checklist (NOT A CERTIFICATE)", st["h"]))
    if synthetic:
        story.append(_p("Not applicable: a certificate cannot be prepared for synthetic data.",
                        st["danger"]))
    else:
        story.append(_p(
            "If these electronic records are to be produced in proceedings, a certificate under "
            "Section 63 of the Bharatiya Sakshya Adhiniyam, 2023 may be required. The form, "
            "wording and the persons competent to sign Part A and Part B must be confirmed by a "
            "qualified legal professional. Pramaana has not completed, signed or certified "
            "anything below.", st["warn"]))
        story.append(_grid_table(
            ["Information typically needed", "Available in this record?"],
            [
                ["Identification of each electronic record (ID, file name, hash)",
                 "Yes — section 5" if evidence else "No evidence attached"],
                ["Device(s) used to capture the records", "Not recorded by Pramaana — to be provided"],
                ["How the records were produced and stored",
                 "Uploaded to the Pramaana server; stored unmodified; hashes in section 5"],
                ["Hash values of the records", "Yes — section 5" if evidence else "None"],
                ["Part A signatory (name, role, date, signature)",
                 "BLANK — to be completed by the competent person"],
                ["Part B signatory (expert; name, role, date, signature)",
                 "BLANK — to be completed by the competent person"],
            ],
            [95 * mm, 83 * mm], st))

    # 9. Missing information
    story.append(Paragraph("9. Missing or incomplete information", st["h"]))
    if gaps:
        for g in gaps:
            story.append(_p(f"• {g}", st["body"]))
    else:
        story.append(_p("No gaps detected by the automatic checklist (a reviewer must still "
                        "check the content).", st["body"]))

    # 10. Review history
    story.append(Paragraph("10. Review status and processing history", st["h"]))
    story.append(_p(f"Current status: {label('status', case['status'])}. Review decisions in "
                    "Pramaana are internal workflow steps, not approvals of a claim.", st["body"]))
    story.append(_grid_table(
        ["UTC time", "Event", "Actor", "Note"],
        [[a["timestamp_utc"],
          a["action"] + (f" ({a['prev_status'] or '—'} → {a['new_status']})" if a.get("new_status") else ""),
          f"{a['actor_type']}: {a['actor_id']}", a.get("note") or ""] for a in audit],
        [34 * mm, 46 * mm, 34 * mm, 64 * mm], st))

    # 11. Legal references
    story.append(Paragraph("11. Legal references and verification status", st["h"]))
    cit = legal_rules.get("statutory_citations", {})
    for key in ("bsa_section_63_4", "wblra_section_21b", "pmfby_72h_trigger"):
        c = cit.get(key)
        if c:
            story.append(_p(f"• {c.get('short_citation')} — status recorded by project legal "
                            f"lead: {c.get('verification_status', 'not recorded')}", st["body"]))
    for item in legal_rules.get("software_audit_flags", {}).get("items", []):
        story.append(_p(f"• [{item['flag']}] {item['ref']}: {item['detail']}", st["body"]))

    footer = f"Pramaana dossier {doc_id} v{version} — Case {case['case_id']}"
    if synthetic:
        footer += " — SYNTHETIC DEMONSTRATION"
    canvas_cls = type("_DossierCanvas", (_NumberedCanvas,),
                      {"footer_text": footer, "synthetic": synthetic})
    doc = SimpleDocTemplate(
        output_path, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=(f"{SYNTHETIC_WATERMARK} — " if synthetic else "") + f"Pramaana dossier {case['case_id']}",
        author="Pramaana (software-generated)",
    )
    doc.build(story, canvasmaker=canvas_cls)
    return output_path


def _sensor_rows(sensor: str, d: Dict[str, Any]) -> List[List[Any]]:
    name = "Sentinel-1 SAR" if sensor == "sentinel1" else "Sentinel-2 optical"
    rows: List[List[Any]] = [[name, f"{d.get('status', '').upper()} — {d.get('message') or ''}"],
                             ["Dataset", d.get("dataset")]]
    if d.get("synthetic_note"):
        rows.append(["SYNTHETIC", d["synthetic_note"]])
    if sensor == "sentinel1":
        if d.get("post_image"):
            pi = d["post_image"]
            rows.append(["Post-incident image", f"{pi['id']} acquired {pi['acquired_utc']} "
                                                f"({pi['orbit_pass']}, rel. orbit {pi['relative_orbit']})"])
        if d.get("baseline_window"):
            rows.append(["Baseline window / images",
                         f"{d['baseline_window'][0]} to {d['baseline_window'][1]}; "
                         f"{len(d.get('baseline_images') or [])} same-orbit image(s)"])
        if d.get("post_mean_vv_db") is not None:
            rows.append(["Mean VV (post / baseline)",
                         f"{d['post_mean_vv_db']} dB / {_dash(d.get('baseline_mean_vv_db'))} dB "
                         f"(change {_dash(d.get('change_db'))} dB)"])
        for s in d.get("sensitivity") or []:
            rows.append([f"Indicator at {s['threshold_db']} dB",
                         f"{s['new_low_backscatter_pct']}% of area newly low-backscatter; "
                         f"{s['uncertain_pct']}% within the uncertainty margin"])
        fmod = d.get("flood_model")
        if fmod and fmod.get("status") == "completed":
            fr = fmod["fractions_pct"]
            rows.append(["Flood model result",
                         f"{fr['flood']}% flood; {fr['uncertain']}% uncertain; "
                         f"{fr['permanent_water']}% permanent water; {fr['excluded']}% excluded "
                         f"(terrain). {fmod['version']}. {fmod.get('method_note', '')}"])
            cal = fmod.get("calibration")
            rows.append(["Flood model accuracy",
                         f"Held-out F1 {cal['test_f1_flood']}, overall accuracy "
                         f"{cal['test_overall_accuracy']}, coverage {cal['test_coverage']} "
                         f"({cal['test_samples']} samples, reference: {cal['reference']})"
                         if cal else "Not calibrated: default parameters, accuracy unmeasured"])
        elif fmod:
            rows.append(["Flood model result", f"{fmod.get('status')}: {fmod.get('message')}"])
    else:
        for part in ("pre", "post"):
            if d.get(part):
                x = d[part]
                rows.append([f"{part.title()}-incident window",
                             f"{' to '.join(d.get(part + '_window') or [])}: "
                             f"{len(x.get('images') or [])} image(s); mean NDVI "
                             f"{x.get('mean_ndvi', '—')}; cloud-free "
                             f"{x.get('cloud_free_fraction_pct', '—')}%"])
        if d.get("ndvi_change") is not None:
            rows.append(["NDVI change (post − pre)",
                         f"{d['ndvi_change']} (vegetation indicator, not a crop-loss measure)"])
    return rows


def _dash(value: Any) -> Any:
    return "—" if value is None else value


def fmt_size(n: Optional[int]) -> str:
    if not n:
        return "—"
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1048576:.1f} MB"


def mask_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    return ("•" * max(0, len(digits) - 4)) + digits[-4:] if len(digits) > 4 else "••••"
