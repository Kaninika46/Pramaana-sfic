"""Unit tests for Pramaana provenance, hash chains, watermarks, UI accuracy, and audit logs."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import tempfile
import unittest
import zlib

from PIL import Image

import app as pramaana_app
from gee_fetcher import (
    EVENT_GRANULE,
    EvidenceArtifact,
    GhatalGEEFetcher,
    VALID_PROVENANCES,
    classify_backscatter,
)
from pramaana_engine import (
    BargadarClaimProfile,
    PramaanaPDFGenerator,
    WATERMARK_DEMO_TEXT,
    compute_chained_integrity_seals,
    load_legal_rules,
)


def extract_pdf_text_streams(pdf_path: str) -> str:
    """Decompress ASCII85 + FlateDecode streams in a ReportLab PDF to inspect text."""
    with open(pdf_path, "rb") as f:
        raw = f.read()

    texts = [raw.decode("latin-1", errors="ignore")]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\n?endstream", raw, re.DOTALL):
        stream_bytes = match.group(1).strip()
        try:
            a85_decoded = base64.a85decode(stream_bytes, adobe=True)
            decompressed = zlib.decompress(a85_decoded)
            texts.append(decompressed.decode("latin-1", errors="ignore"))
        except Exception:
            try:
                decompressed = zlib.decompress(stream_bytes)
                texts.append(decompressed.decode("latin-1", errors="ignore"))
            except Exception:
                pass
    return "\n".join(texts)


class PramaanaSafetyAndLegalTests(unittest.TestCase):
    """Verify provenance enforcement, watermarking, upload re-hashing, and UI fixes."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.fetcher = GhatalGEEFetcher(artifact_dir=self.temp_dir.name)
        self.pdf_gen = PramaanaPDFGenerator(output_dir=self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_provenance_validation_rejects_invalid_values(self) -> None:
        """Every artifact must use live_sentinel, synthetic_demo, or farmer_capture."""
        self.assertEqual(
            set(VALID_PROVENANCES),
            {"live_sentinel", "synthetic_demo", "farmer_capture"},
        )
        with self.assertRaises(ValueError):
            EvidenceArtifact(
                artifact_type="TEST",
                file_path="dummy.png",
                sha256_hash="0" * 64,
                provenance="invalid_provenance",
                sensor_source="Test",
                capture_timestamp_utc="2026-10-25T00:00:00Z",
            )

    def test_no_silent_fallback_when_synthetic_disabled(self) -> None:
        """If GEE is unauthenticated and allow_synthetic_demo=False, raise error."""
        if not self.fetcher.gee_live:
            with self.assertRaises(RuntimeError):
                self.fetcher.fetch_evidence_bundle(
                    cultivator_name="[FICTIONAL DEMO] Test",
                    allow_synthetic_demo=False,
                )

    def test_server_recomputes_and_compares_raw_upload_hash(self) -> None:
        """Server must recompute raw upload SHA-256 and detect match or mismatch."""
        sample_photo = os.path.join(self.temp_dir.name, "raw_capture.png")
        Image.new("RGB", (100, 80), (20, 100, 180)).save(sample_photo, format="PNG")
        with open(sample_photo, "rb") as f:
            true_sha256 = hashlib.sha256(f.read()).hexdigest()

        bundle_match = self.fetcher.fetch_evidence_bundle(
            cultivator_name="[FICTIONAL DEMO] Cultivator A",
            custom_ground_photo_path=sample_photo,
            client_photo_sha256=true_sha256,
        )
        seals_match = compute_chained_integrity_seals(bundle_match)
        self.assertTrue(bundle_match.ground_artifact.upload_hash_verified)
        self.assertEqual(
            seals_match["photo_upload_hash_status"], "MATCH_VERIFIED_ON_UPLOAD"
        )

        bundle_mismatch = self.fetcher.fetch_evidence_bundle(
            cultivator_name="[FICTIONAL DEMO] Cultivator A",
            custom_ground_photo_path=sample_photo,
            client_photo_sha256="0" * 64,
        )
        seals_mismatch = compute_chained_integrity_seals(bundle_mismatch)
        self.assertFalse(bundle_mismatch.ground_artifact.upload_hash_verified)
        self.assertEqual(
            seals_mismatch["photo_upload_hash_status"], "MISMATCH_WARNING"
        )

    def test_synthetic_demo_triggers_watermark_and_void_certificate(self) -> None:
        """If any artifact is synthetic_demo, PDF must have DEMO watermark and VOID cert."""
        bundle = self.fetcher.fetch_evidence_bundle(
            cultivator_name="[FICTIONAL DEMO] Test",
            allow_synthetic_demo=True,
        )
        self.assertTrue(bundle.contains_synthetic_demo)

        profile = BargadarClaimProfile(
            claim_id="TEST-SYNTH-001",
            cultivator_name="[FICTIONAL DEMO] Test Cultivator",
            father_or_spouse_name="[FICTIONAL DEMO] Parent",
            village_mouza="Mansuka",
            gram_panchayat="Mansuka GP",
            jl_number="JL-38",
            khatian_no="KH-1",
            plot_dag_no="101",
            cultivator_category="Unrecorded Bargadar (Sec. 21B Statutory Presumption)",
            landowner_raiyat_name="[FICTIONAL DEMO] Raiyat",
        )
        pdf_path = self.pdf_gen.generate_dossier(profile=profile, telemetry=bundle)
        pdf_text = extract_pdf_text_streams(pdf_path)

        self.assertIn(WATERMARK_DEMO_TEXT, pdf_text)
        self.assertIn("CERTIFICATE VOID / DISABLED", pdf_text)
        self.assertNotIn("court-ready", pdf_text.lower())
        self.assertNotIn("Clause 21.5.1", pdf_text)
        self.assertNotIn("1.8 dB", pdf_text)

    def test_non_synthetic_bundle_renders_pending_signature_certificate(self) -> None:
        """When all artifacts are live_sentinel or farmer_capture, cert is PENDING SIGNATURE."""
        sample_photo = os.path.join(self.temp_dir.name, "farmer_photo.png")
        Image.new("RGB", (120, 90), (40, 120, 60)).save(sample_photo, format="PNG")

        bundle = self.fetcher.fetch_evidence_bundle(
            cultivator_name="[FICTIONAL DEMO] Real Capture Test",
            custom_ground_photo_path=sample_photo,
            client_photo_sha256="f" * 64,
            override_satellite_provenance="live_sentinel",
        )
        self.assertFalse(bundle.contains_synthetic_demo)

        profile = BargadarClaimProfile(
            claim_id="TEST-LIVE-002",
            cultivator_name="[FICTIONAL DEMO] Real Capture Test",
            father_or_spouse_name="[FICTIONAL DEMO] Parent",
            village_mouza="Kharar",
            gram_panchayat="Kharar GP",
            jl_number="JL-42",
            khatian_no="KH-2",
            plot_dag_no="202",
            cultivator_category="Recorded Bargadar (Barga Khatian Holder)",
            landowner_raiyat_name="[FICTIONAL DEMO] Raiyat",
        )
        pdf_path = self.pdf_gen.generate_dossier(profile=profile, telemetry=bundle)
        pdf_text = extract_pdf_text_streams(pdf_path)

        self.assertIn("PENDING SIGNATURE", pdf_text)
        self.assertNotIn("CERTIFICATE VOID / DISABLED", pdf_text)
        self.assertIn(EVENT_GRANULE["granule_name"], pdf_text)
        self.assertIn("2024-09-19T12:12:50.332521Z", pdf_text)
        self.assertIn("21.5.5.4", pdf_text)
        self.assertIn("14447", pdf_text)
        self.assertIn("West Ben. Act XI of 1969", pdf_text)
        self.assertIn("not a member of the family", pdf_text)
        self.assertIn("geomatics professional", pdf_text)
        self.assertIn("excluded from the certified flood-extent count", pdf_text)

    def test_ui_has_no_prefilled_login_or_75_25_and_supports_delete(self) -> None:
        """Verify UI removes pre-filled login, 75:25 default, and supports DPDP deletion."""
        client = pramaana_app.app.test_client()
        home_html = client.get("/").get_data(as_text=True)

        self.assertIn("Demo mode: synthetic data, not evidence.", home_html)
        self.assertIn("SIMULATED", home_html)
        self.assertIn("আপনার দাবিটি", home_html)
        self.assertNotIn('value="dlsa_reviewer"', home_html)
        self.assertNotIn('value="ghatal2026"', home_html)
        self.assertNotIn("75:25", home_html)
        self.assertIn(
            "Your claim data will be deleted, subject to 48-hour notice and "
            "statutory retention of security logs for one year under the DPDP Rules, 2025.",
            home_html,
        )
        self.assertIn(EVENT_GRANULE["granule_name"], home_html)

        # Trigger a new claim with an uploaded image and delete it via DPDP button
        img_bytes = io.BytesIO()
        Image.new("RGB", (60, 60), (10, 20, 30)).save(img_bytes, format="PNG")
        img_raw = img_bytes.getvalue()
        img_sha = hashlib.sha256(img_raw).hexdigest()

        post_resp = client.post(
            "/api/trigger-claim",
            data={
                "cultivator_name": "[FICTIONAL DEMO] Delete Test",
                "village_mouza": "Sultanpur",
                "plot_dag_no": "999",
                "client_photo_sha256": img_sha,
                "ground_photo": (io.BytesIO(img_raw), "capture.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(post_resp.status_code, 302)

        claims_json = client.get("/api/claims").get_json()
        created = next(
            c for c in claims_json["claims"] if c["plot_dag_no"] == "999"
        )
        self.assertEqual(
            created["integrity_seals"]["photo_upload_hash_status"],
            "MATCH_VERIFIED_ON_UPLOAD",
        )

        # Delete the claim
        del_resp = client.post(f"/api/delete-claim/{created['claim_id']}")
        self.assertEqual(del_resp.status_code, 302)
        after_json = client.get("/api/claims").get_json()
        self.assertFalse(
            any(c["claim_id"] == created["claim_id"] for c in after_json["claims"])
        )

    def test_verified_legal_rules_and_copernicus_granule_and_uncertain_pixels(self) -> None:
        """Verify restored primary citations, Copernicus granule, and uncertain pixel rule."""
        rules = load_legal_rules()
        self.assertEqual(rules["deadlines"]["localized_calamity_intimation_hours"], 72)
        self.assertEqual(rules["deadlines"]["complete_details_days"], 7)
        self.assertEqual(rules["deadlines"]["bank_or_official_forwarding_hours"], 48)

        wblra = rules["statutory_citations"]["wblra_section_21b"]
        self.assertIn("not a member of the family", wblra["verbatim_section_text"])
        self.assertIn("West Ben. Act XI of 1969", wblra["insertion_history"])

        pmfby = rules["statutory_citations"]["pmfby_72h_trigger"]
        self.assertEqual(pmfby["primary_clause"]["clause"], "21.5.5.4")
        self.assertIn("14447", pmfby["primary_clause"]["text"])

        bsa = rules["statutory_citations"]["bsa_section_63_4"]
        self.assertIn("qualified geomatics professional", bsa["footnote_text"])

        dpdp = rules["statutory_citations"]["dpdp_act_2023"]
        self.assertEqual(
            dpdp["delete_button_notice"],
            "Your claim data will be deleted, subject to 48-hour notice and "
            "statutory retention of security logs for one year under the DPDP Rules, 2025.",
        )

        self.assertEqual(
            EVENT_GRANULE["granule_name"],
            "S1A_IW_GRDH_1SDV_20240919T121250_20240919T121315_055734_06CEC2_FD14",
        )
        self.assertEqual(
            EVENT_GRANULE["acquisition_start_utc"],
            "2024-09-19T12:12:50.332521Z",
        )

        self.assertEqual(classify_backscatter(-18.2, -10.0), "uncertain")
        self.assertEqual(classify_backscatter(-21.0, -10.0), "flood")
        self.assertEqual(classify_backscatter(-12.0, -10.0), "not_flood")


if __name__ == "__main__":
    unittest.main()
