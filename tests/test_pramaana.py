"""Tests for the legacy (pre-upgrade) evidence-bundle and PDF modules.

The case workflow is covered in test_workflow.py.
"""

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

    def test_synthetic_values_never_carry_real_acquisition_time(self) -> None:
        """Legacy synthetic SAR values must not be stamped with the real granule time."""
        bundle = self.fetcher.fetch_evidence_bundle(cultivator_name="[FICTIONAL DEMO] Test")
        if not self.fetcher.gee_live:
            self.assertEqual(bundle.sar_artifact.provenance, "synthetic_demo")
            self.assertEqual(bundle.inundation_timestamp_utc, "SYNTHETIC_NO_ACQUISITION")

    def test_provenance_override_hook_removed(self) -> None:
        """Synthetic data can no longer be relabelled as live_sentinel by a caller."""
        with self.assertRaises(TypeError):
            self.fetcher.fetch_evidence_bundle(
                cultivator_name="[FICTIONAL DEMO] Test",
                override_satellite_provenance="live_sentinel",
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
