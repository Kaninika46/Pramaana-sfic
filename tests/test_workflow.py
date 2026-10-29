"""End-to-end tests for the Pramaana case workflow (acceptance criteria).

All data here is fictional. The app is pointed at a temporary database and
storage folder before it is imported, so no project data is touched.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import os
import re
import sqlite3
import sys
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="pramaana_test_")
os.environ["PRAMAANA_DB"] = os.path.join(_TMP, "test.db")
os.environ["PRAMAANA_STORAGE_DIR"] = _TMP
os.environ.pop("GEE_PROJECT_ID", None)
os.environ.pop("PRAMAANA_REVIEWER_USER", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

import app as A  # noqa: E402
import gee_fetcher  # noqa: E402
from pramaana_rules import UNVERIFIED_DEADLINE_MESSAGE, assess_deadline, incident_start_utc  # noqa: E402
from pramaana_store import PramaanaStore, TransitionError  # noqa: E402
from test_pramaana import extract_pdf_text_streams  # noqa: E402

A.app.config["TESTING"] = True
PASSWORD = "correct-horse-battery"


def jpeg_bytes(color=(10, 120, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, format="JPEG")
    return buf.getvalue()


def csrf(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def ensure_reviewer(username: str, role: str) -> None:
    if not A.store.get_reviewer(username):
        A.store.create_reviewer(username, A.generate_password_hash(PASSWORD), role)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        for limiter in (A.login_limiter, A.track_limiter, A.submit_limiter):
            limiter.hits.clear()
        self.farmer = A.app.test_client()
        self.token = csrf(self.farmer.get("/report").get_data(as_text=True))

    def report(self, client=None, token=None, files=None, **overrides):
        client = client or self.farmer
        data = {
            "csrf_token": token or self.token,
            "submission_id": os.urandom(16).hex(),
            "record_type": "field_test",
            "claimant_name": "Fictional Tester",
            "village": "Fictional Village",
            "crop": "Paddy",
            "incident_date": "2026-10-20",
            "damage_type": "submergence",
            "damage_description": "Fictional test description.",
            "consent": "yes",
        }
        data.update(overrides)
        for k, v in list(data.items()):
            if v is None:
                del data[k]
        if files:
            data.update(files)
        return client.post("/report", data=data, content_type="multipart/form-data")

    def new_case(self, **kw) -> str:
        resp = self.report(**kw)
        self.assertEqual(resp.status_code, 302, resp.get_data(as_text=True)[:500])
        return resp.location.rsplit("/", 1)[-1]

    def reviewer(self, username="rev_admin", role="admin"):
        ensure_reviewer(username, role)
        client = A.app.test_client()
        tok = csrf(client.get("/reviewer/login").get_data(as_text=True))
        resp = client.post("/reviewer/login", data={"csrf_token": tok, "username": username,
                                                    "password": PASSWORD})
        self.assertEqual(resp.status_code, 302)
        tok = csrf(client.get("/reviewer").get_data(as_text=True))
        return client, tok


class StartupTests(Base):
    def test_starts_without_earth_engine_and_reports_honestly(self):
        health = self.farmer.get("/api/health").get_json()
        self.assertFalse(health["earth_engine"]["ready"])
        self.assertIn("Satellite analysis unavailable: Earth Engine configuration is incomplete.",
                      health["earth_engine"]["message"])
        for path in ("/", "/report", "/track", "/verify", "/about", "/reviewer/login"):
            self.assertEqual(self.farmer.get(path).status_code, 200, path)

    def test_no_default_reviewer_credentials(self):
        self.assertIsNone(A.store.get_reviewer("dlsa_reviewer"))
        html = self.farmer.get("/reviewer/login").get_data(as_text=True)
        self.assertNotIn("ghatal_dlsa_2026", html)

    def test_legacy_database_is_migrated_without_losing_rows(self):
        path = os.path.join(_TMP, "legacy.db")
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE reviewer_audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                         "claim_id TEXT NOT NULL, action TEXT NOT NULL, reviewer TEXT NOT NULL, "
                         "note TEXT NOT NULL, timestamp_utc TEXT NOT NULL)")
            conn.execute("INSERT INTO reviewer_audit_log(claim_id, action, reviewer, note, timestamp_utc) "
                         "VALUES ('X-1', 'APPROVED', 'r', 'n', '2026-01-01T00:00:00Z')")
        store = PramaanaStore(path, _TMP)
        self.assertEqual(len(store.list_legacy_audit()), 1)
        self.assertEqual(store.list_cases(), [])


class CaseTests(Base):
    def test_case_created_and_persists_across_restart(self):
        case_id = self.new_case(phone=None, latitude=None, longitude=None)
        reopened = PramaanaStore(os.environ["PRAMAANA_DB"], _TMP)  # simulates a restart
        case = reopened.get_case(case_id)
        self.assertEqual(case["claimant_name"], "Fictional Tester")
        self.assertEqual(case["status"], "SUBMITTED")
        self.assertIsNone(case["phone"])
        self.assertIsNone(case["latitude"])
        self.assertEqual(case["location_source"], "none")
        self.assertTrue(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", case["created_at_utc"]))

    def test_required_fields_and_consent_are_validated(self):
        before = len(A.store.list_cases())
        resp = self.report(claimant_name="", crop="", consent=None)
        self.assertEqual(resp.status_code, 422)
        html = resp.get_data(as_text=True)
        self.assertIn("This is required.", html)
        self.assertIn("Consent is needed", html)
        self.assertEqual(len(A.store.list_cases()), before)

    def test_invalid_coordinates_phone_and_future_date_rejected(self):
        future = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
        resp = self.report(latitude="95", longitude="87.7", phone="12345", incident_date=future)
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("Latitude must be between -90 and 90.", html)
        self.assertIn("10-digit Indian mobile number", html)
        self.assertIn("cannot be in the future", html)

    def test_duplicate_submission_creates_one_case(self):
        sid = os.urandom(16).hex()
        first = self.report(submission_id=sid)
        second = self.report(submission_id=sid)
        self.assertEqual(first.location, second.location)
        case_id = first.location.rsplit("/", 1)[-1]
        self.assertEqual(sum(1 for c in A.store.list_cases() if c["client_submission_id"] == sid), 1)
        self.assertTrue(case_id)

    def test_csrf_required(self):
        resp = self.farmer.post("/report", data={"claimant_name": "x"})
        self.assertEqual(resp.status_code, 400)

    def test_report_form_has_no_prefilled_fictional_values_or_consent(self):
        html = self.farmer.get("/report").get_data(as_text=True)
        self.assertNotIn("[FICTIONAL DEMO]", html)
        self.assertNotRegex(html, r'name="consent"[^>]*checked')

    def test_gps_location_source_and_accuracy_recorded(self):
        case_id = self.new_case(latitude="22.70", longitude="87.70", location_source="device_gps",
                                location_accuracy_m="12")
        case = A.store.get_case(case_id)
        self.assertEqual(case["location_source"], "device_gps")
        self.assertEqual(case["location_accuracy_m"], 12.0)


class EvidenceTests(Base):
    def test_hash_recorded_verified_and_tamper_detected(self):
        raw = jpeg_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        case_id = self.new_case(
            client_hashes=f'[{{"name": "field.jpg", "size": {len(raw)}, "sha256": "{digest}"}}]',
            files={"photos": (io.BytesIO(raw), "field.jpg")})
        [ev] = A.store.list_evidence(case_id)
        self.assertEqual(ev["sha256"], digest)
        self.assertEqual(ev["client_hash_match"], 1)
        self.assertEqual(ev["provenance"], "farmer_capture")
        path = A.store.resolve(ev["stored_path"])
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), raw)  # stored byte-for-byte

        self.assertEqual(A.store.verify_evidence_file(ev["evidence_id"], "test", "t")["result"], "MATCH")
        with open(path, "ab") as fh:
            fh.write(b"tamper")
        result = A.store.verify_evidence_file(ev["evidence_id"], "test", "t")
        self.assertEqual(result["result"], "MISMATCH")
        self.assertEqual(A.store.get_evidence(ev["evidence_id"])["sha256"], digest)  # never overwritten
        os.remove(path)
        self.assertEqual(A.store.verify_evidence_file(ev["evidence_id"], "test", "t")["result"], "FILE_MISSING")
        self.assertEqual([v["result"] for v in A.store.list_verifications(ev["evidence_id"])],
                         ["MATCH", "MISMATCH", "FILE_MISSING"])

    def test_client_hash_mismatch_flagged(self):
        raw = jpeg_bytes()
        case_id = self.new_case(
            client_hashes=f'[{{"name": "a.jpg", "size": {len(raw)}, "sha256": "{"0" * 64}"}}]',
            files={"photos": (io.BytesIO(raw), "a.jpg")})
        self.assertEqual(A.store.list_evidence(case_id)[0]["client_hash_match"], 0)

    def test_malformed_and_empty_uploads_rejected_with_message(self):
        resp = self.report(files={"photos": [(io.BytesIO(b"not really an image"), "fake.jpg"),
                                             (io.BytesIO(b""), "empty.jpg")]})
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("is not an accepted field photograph file type", html)
        self.assertIn("is empty", html)

    def test_voice_note_is_stored_not_discarded(self):
        ogg = b"OggS" + b"\x00" * 60
        case_id = self.new_case(files={"voice": (io.BytesIO(ogg), "note.ogg")})
        [ev] = A.store.list_evidence(case_id)
        self.assertEqual(ev["kind"], "audio")
        self.assertTrue(os.path.exists(A.store.resolve(ev["stored_path"])))

    def test_evidence_stays_with_its_case(self):
        a = self.new_case(files={"photos": (io.BytesIO(jpeg_bytes((1, 1, 1))), "same.jpg")})
        b = self.new_case(files={"photos": (io.BytesIO(jpeg_bytes((200, 1, 1))), "same.jpg")})
        ea, eb = A.store.list_evidence(a)[0], A.store.list_evidence(b)[0]
        self.assertNotEqual(ea["stored_path"], eb["stored_path"])
        self.assertNotEqual(ea["sha256"], eb["sha256"])
        self.assertIn(a, ea["stored_path"])


class _FakeChain:
    """Stands in for Earth Engine objects; every collection comes back empty."""

    def __init__(self, last=""):
        self.last = last

    def __getattr__(self, name):
        return lambda *a, **k: _FakeChain(name)

    def __call__(self, *a, **k):
        return _FakeChain(self.last)

    def getInfo(self):  # noqa: N802
        return {"size": 0, "aggregate_array": []}.get(self.last, {})


class _FakeEE:
    def __getattr__(self, name):
        return _FakeChain(name)


class SatelliteTests(Base):
    def test_missing_credentials_reported_without_values(self):
        rec = gee_fetcher.analyze_case_location(22.7, 87.7, "2026-10-01", gee_ready=False,
                                                gee_error="GEE_PROJECT_ID not set")
        self.assertEqual(rec["status"], "unavailable")
        self.assertEqual(rec["provenance"], "not_queried")
        self.assertIn("Satellite analysis unavailable", rec["message"])
        self.assertIsNone(rec["sentinel1"])
        self.assertIsNone(rec["sentinel2"])

    def test_invalid_inputs_rejected(self):
        for lat, lon, day in ((91, 87, "2026-10-01"), ("x", 87, "2026-10-01"), (0, 0, "2026-10-01"),
                              (22.7, 87.7, "2999-01-01"), (22.7, 87.7, None)):
            rec = gee_fetcher.analyze_case_location(lat, lon, day, gee_ready=True)
            self.assertEqual(rec["status"], "invalid_input", (lat, lon, day))

    def test_empty_collections_do_not_produce_values(self):
        original_ee, original_avail = getattr(gee_fetcher, "ee", None), gee_fetcher.EE_AVAILABLE
        gee_fetcher.ee, gee_fetcher.EE_AVAILABLE = _FakeEE(), True
        try:
            rec = gee_fetcher.analyze_case_location(22.7, 87.7, "2026-09-01", gee_ready=True)
        finally:
            gee_fetcher.ee, gee_fetcher.EE_AVAILABLE = original_ee, original_avail
        self.assertEqual(rec["status"], "no_data")
        self.assertEqual(rec["sentinel1"]["status"], "no_data")
        self.assertEqual(rec["sentinel2"]["status"], "no_data")
        self.assertNotIn("post_mean_vv_db", rec["sentinel1"])
        self.assertNotIn("ndvi_change", rec["sentinel2"])

    def test_real_case_never_gets_synthetic_and_workflow_continues(self):
        case_id = self.new_case(latitude="22.7", longitude="87.7")
        client, tok = self.reviewer()
        client.post(f"/reviewer/case/{case_id}/satellite", data={"csrf_token": tok})
        [an] = A.store.list_analyses(case_id)
        self.assertEqual(an["status"], "unavailable")
        self.assertNotEqual(an["provenance"], "synthetic_demo")
        resp = client.post(f"/reviewer/case/{case_id}/dossier", data={"csrf_token": tok})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(A.store.list_documents(case_id)), 1)

    def test_synthetic_case_analysis_is_labelled(self):
        client, tok = self.reviewer()
        case_id = A.create_synthetic_case("test")
        client.post(f"/reviewer/case/{case_id}/satellite", data={"csrf_token": tok})
        [an] = A.store.list_analyses(case_id)
        self.assertEqual(an["provenance"], "synthetic_demo")
        self.assertIn("SYNTHETIC", an["record"]["sentinel1"]["synthetic_note"])
        case = A.store.get_case(case_id)
        self.assertIsNone(case["latitude"])  # no real-world coordinates on synthetic cases
        self.assertTrue(all(e["is_synthetic"] for e in A.store.list_evidence(case_id)))


class DossierTests(Base):
    def test_real_dossier_contents_hash_download_and_verify(self):
        case_id = self.new_case(files={"photos": (io.BytesIO(jpeg_bytes()), "f.jpg")},
                                claimant_name="Fictional Person <b>&")
        client, tok = self.reviewer()
        client.post(f"/reviewer/case/{case_id}/dossier", data={"csrf_token": tok})
        [doc] = A.store.list_documents(case_id)
        path = A.store.resolve(doc["file_path"])
        self.assertTrue(os.path.exists(path))
        resp = client.get(f"/reviewer/document/{doc['doc_id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(hashlib.sha256(resp.data).hexdigest(), doc["sha256"])
        text = extract_pdf_text_streams(path)
        self.assertIn(case_id, text)
        self.assertIn("Fictional Person", text)
        self.assertIn("NOT A CERTIFICATE", text)
        self.assertIn("BLANK", text)
        self.assertIn("Page 1 of", text)
        self.assertNotIn("SYNTHETIC DEMONSTRATION", text)
        for forbidden in ("Pune Bar Association", "APPROVED", "court-ready", "DLSA-PMD-PLV"):
            self.assertNotIn(forbidden, text)

        public = A.app.test_client()
        ptok = csrf(public.get("/verify").get_data(as_text=True))
        ok = public.post("/verify", data={"csrf_token": ptok, "file": (io.BytesIO(resp.data), "d.pdf")},
                         content_type="multipart/form-data").get_data(as_text=True)
        self.assertIn("Match found", ok)
        bad = public.post("/verify", data={"csrf_token": ptok,
                                           "file": (io.BytesIO(resp.data + b"x"), "d.pdf")},
                          content_type="multipart/form-data").get_data(as_text=True)
        self.assertIn("No match", bad)

        with open(path, "ab") as fh:
            fh.write(b"%tamper")
        client.post(f"/reviewer/document/{doc['doc_id']}/verify", data={"csrf_token": tok})
        events = [a for a in A.store.list_audit(case_id) if a["action"] == "DOCUMENT_INTEGRITY_CHECK"]
        self.assertTrue(events[-1]["note"].endswith("MISMATCH"))

    def test_synthetic_dossier_is_watermarked_and_has_no_certificate(self):
        client, tok = self.reviewer()
        case_id = A.create_synthetic_case("test")
        client.post(f"/reviewer/case/{case_id}/dossier", data={"csrf_token": tok})
        [doc] = A.store.list_documents(case_id)
        self.assertEqual(doc["is_synthetic"], 1)
        text = extract_pdf_text_streams(A.store.resolve(doc["file_path"]))
        self.assertIn("SYNTHETIC DEMONSTRATION", text)
        self.assertIn("NOT REAL EVIDENCE", text)
        self.assertIn("a certificate cannot be prepared for synthetic data", text)


class ReviewerTests(Base):
    def test_privileged_routes_require_sign_in(self):
        case_id = self.new_case()
        anon = A.app.test_client()
        tok = csrf(anon.get("/report").get_data(as_text=True))
        self.assertEqual(anon.get("/reviewer").status_code, 302)
        for path in (f"/reviewer/case/{case_id}/status", f"/reviewer/case/{case_id}/dossier",
                     f"/reviewer/case/{case_id}/erase", "/reviewer/demo"):
            self.assertEqual(anon.post(path, data={"csrf_token": tok, "new_status": "UNDER_REVIEW"}).status_code,
                             403, path)
        self.assertEqual(A.store.get_case(case_id)["status"], "SUBMITTED")

    def test_non_admin_cannot_erase(self):
        case_id = self.new_case()
        client, tok = self.reviewer("plain_reviewer", "reviewer")
        resp = client.post(f"/reviewer/case/{case_id}/erase", data={"csrf_token": tok,
                                                                   "confirm_case_id": case_id})
        self.assertEqual(resp.status_code, 403)

    def test_transitions_recorded_and_invalid_rejected(self):
        case_id = self.new_case()
        client, tok = self.reviewer()
        client.post(f"/reviewer/case/{case_id}/status",
                    data={"csrf_token": tok, "new_status": "READY_FOR_SUBMISSION"})
        self.assertEqual(A.store.get_case(case_id)["status"], "SUBMITTED")  # not allowed directly
        client.post(f"/reviewer/case/{case_id}/status", data={"csrf_token": tok, "new_status": "UNDER_REVIEW"})
        client.post(f"/reviewer/case/{case_id}/status", data={"csrf_token": tok, "new_status": "INFO_REQUESTED"})
        self.assertEqual(A.store.get_case(case_id)["status"], "UNDER_REVIEW")  # reason required
        client.post(f"/reviewer/case/{case_id}/status",
                    data={"csrf_token": tok, "new_status": "INFO_REQUESTED", "note": "Need a wide photo."})
        self.assertEqual(A.store.get_case(case_id)["status"], "INFO_REQUESTED")
        changes = [a for a in A.store.list_audit(case_id) if a["action"] == "STATUS_CHANGE"]
        self.assertEqual([(c["prev_status"], c["new_status"]) for c in changes],
                         [("SUBMITTED", "UNDER_REVIEW"), ("UNDER_REVIEW", "INFO_REQUESTED")])
        self.assertTrue(all(c["actor_id"] == "rev_admin" for c in changes))
        self.assertTrue(all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", c["timestamp_utc"]) for c in changes))
        with self.assertRaises(TransitionError):
            A.store.transition_case(case_id, "ERASED", "test", "t", "")

    def test_audit_log_append_only_and_tamper_evident(self):
        self.new_case()
        self.assertTrue(A.store.verify_audit_chain()["intact"])
        with sqlite3.connect(os.environ["PRAMAANA_DB"]) as conn:
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("UPDATE audit_events SET note='edited' WHERE seq=1")
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("DELETE FROM audit_events WHERE seq=1")
        copy = os.path.join(_TMP, "tamper.db")
        with sqlite3.connect(os.environ["PRAMAANA_DB"]) as src, sqlite3.connect(copy) as dst:
            src.backup(dst)
        with sqlite3.connect(copy) as conn:
            conn.execute("DROP TRIGGER audit_events_no_update")
            conn.execute("UPDATE audit_events SET note='edited' WHERE seq=1")
        self.assertFalse(PramaanaStore(copy, _TMP).verify_audit_chain()["intact"])

    def test_passwords_hashed_and_login_rate_limited(self):
        ensure_reviewer("rate_user", "reviewer")
        self.assertNotEqual(A.store.get_reviewer("rate_user")["password_hash"], PASSWORD)
        client = A.app.test_client()
        tok = csrf(client.get("/reviewer/login").get_data(as_text=True))
        codes = [client.post("/reviewer/login", data={"csrf_token": tok, "username": "rate_user",
                                                      "password": "wrong"}).status_code for _ in range(6)]
        self.assertEqual(codes[:5], [200] * 5)
        self.assertEqual(codes[5], 429)

    def test_erasure_flow(self):
        case_id = self.new_case(phone="9876543210", latitude="22.7", longitude="87.7",
                                files={"photos": (io.BytesIO(jpeg_bytes()), "f.jpg")})
        [ev] = A.store.list_evidence(case_id)
        stored = A.store.resolve(ev["stored_path"])
        self.farmer.post(f"/track/{case_id}/erasure-request", data={"csrf_token": self.token})
        self.assertIsNotNone(A.store.get_case(case_id)["erasure_requested_at_utc"])
        client, tok = self.reviewer()
        client.post(f"/reviewer/case/{case_id}/erase", data={"csrf_token": tok, "confirm_case_id": case_id})
        case = A.store.get_case(case_id)
        self.assertEqual(case["status"], "ERASED")
        for field in ("claimant_name", "phone", "latitude", "damage_description"):
            self.assertIsNone(case[field], field)
        self.assertFalse(os.path.exists(stored))
        ev_after = A.store.get_evidence(ev["evidence_id"])
        self.assertEqual(ev_after["status"], "erased")
        self.assertEqual(ev_after["sha256"], ev["sha256"])
        self.assertIn("PERSONAL_DATA_ERASED", [a["action"] for a in A.store.list_audit(case_id)])


class DeadlineTests(Base):
    RULES = {"deadline_rules": {
        "PMFBY": {"label": "PMFBY", "duration_hours": 72, "applicability_verified": False},
        "BSB": {"label": "BSB", "duration_hours": None, "applicability_verified": False},
        "UNKNOWN": {"label": "Unknown", "duration_hours": None}}}

    def case(self, **kw):
        c = {"insurance_scheme": "PMFBY", "incident_date": "2026-10-27", "incident_time": "06:00",
             "created_at_utc": "2026-10-27T10:00:00Z", "record_type": "real"}
        c.update(kw)
        c["incident_start_utc"] = incident_start_utc(c["incident_date"], c["incident_time"])
        return c

    def test_deadline_derived_from_persisted_timestamps(self):
        c = self.case()
        self.assertEqual(c["incident_start_utc"], "2026-10-27T00:30:00Z")  # IST -> UTC
        now1 = datetime.datetime(2026, 10, 28, 0, 30, tzinfo=datetime.timezone.utc)
        now2 = now1 + datetime.timedelta(hours=5)
        d1, d2 = assess_deadline(c, self.RULES, now1), assess_deadline(c, self.RULES, now2)
        self.assertEqual(d1["deadline_utc"], "2026-10-30T00:30:00Z")
        self.assertEqual(d1["deadline_epoch_ms"], d2["deadline_epoch_ms"])  # stable across refreshes
        self.assertEqual(d1["remaining_seconds"] - d2["remaining_seconds"], 5 * 3600)
        self.assertEqual(d1["state"], "open")
        self.assertFalse(d1["verified"])
        self.assertIn(UNVERIFIED_DEADLINE_MESSAGE, d1["message"])

    def test_expired_unconfigured_and_date_only(self):
        late = datetime.datetime(2026, 11, 5, tzinfo=datetime.timezone.utc)
        self.assertEqual(assess_deadline(self.case(), self.RULES, late)["state"], "passed")
        bsb = assess_deadline(self.case(insurance_scheme="BSB"), self.RULES)
        self.assertEqual(bsb["state"], "no_rule")
        self.assertIn(UNVERIFIED_DEADLINE_MESSAGE, bsb["message"])
        date_only = assess_deadline(self.case(incident_time=None), self.RULES)
        self.assertTrue(date_only["incident_time_assumed"])
        self.assertEqual(date_only["incident_start_utc"], "2026-10-26T18:30:00Z")

    def test_synthetic_timer_visibly_simulated_and_stable_on_refresh(self):
        client, _ = self.reviewer()
        case_id = A.create_synthetic_case("test")
        pages = [client.get(f"/reviewer/case/{case_id}").get_data(as_text=True) for _ in range(2)]
        marks = [re.search(r'data-deadline-ms="(\d+)"', p).group(1) for p in pages]
        self.assertEqual(marks[0], marks[1])
        self.assertIn("SIMULATED (synthetic case)", pages[0])

    def test_tracking_page_shows_provisional_deadline(self):
        today = datetime.date.today().isoformat()
        case_id = self.new_case(insurance_scheme="PMFBY", incident_date=today)
        html = self.farmer.get(f"/track/{case_id}").get_data(as_text=True)
        self.assertIn("Provisional", html)
        self.assertIn(UNVERIFIED_DEADLINE_MESSAGE, html)


class TrackingTests(Base):
    def test_tracking_requires_code_and_allows_adding_evidence(self):
        resp = self.report()
        case_id = resp.location.rsplit("/", 1)[-1]
        code = re.findall(r'code-display">([^<]+)<',
                          self.farmer.get(resp.location).get_data(as_text=True))[1]
        other = A.app.test_client()
        tok = csrf(other.get("/track").get_data(as_text=True))
        self.assertEqual(other.get(f"/track/{case_id}").status_code, 404)
        self.assertEqual(other.post("/track", data={"csrf_token": tok, "case_id": case_id,
                                                    "tracking_code": "WRONG123"}).status_code, 401)
        self.assertEqual(other.post("/track", data={"csrf_token": tok, "case_id": case_id,
                                                    "tracking_code": code}).status_code, 302)
        resp = other.post(f"/track/{case_id}/evidence", content_type="multipart/form-data",
                          data={"csrf_token": tok, "photos": (io.BytesIO(jpeg_bytes()), "more.jpg")})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(A.store.list_evidence(case_id)), 1)


if __name__ == "__main__":
    unittest.main()
