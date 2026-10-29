"""Pramaana persistent store (SQLite) — cases, evidence, analyses, documents, audit.

Design notes
- One SQLite file (default: pramaana_audit.db, the file the original app already
  used). Existing tables are never dropped; the legacy `reviewer_audit_log`
  table is kept read-only for history.
- Schema changes go through numbered migrations recorded in `schema_meta`.
- `audit_events` is append-only at the database level (UPDATE/DELETE triggers
  abort) and each row carries a SHA-256 hash chained to the previous row. This
  is *tamper-evident*, not immutable: anyone with write access to the file can
  drop the triggers and rewrite the whole chain. `verify_audit_chain()` detects
  edits made without recomputing every later hash.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

SCHEMA_VERSION = 2

# Case lifecycle. Pramaana never "approves" a claim: the furthest a reviewer can
# take a case is READY_FOR_SUBMISSION (the dossier is complete enough for the
# claimant to submit through the official channel themselves).
CASE_STATUSES = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "INFO_REQUESTED",
    "READY_FOR_SUBMISSION",
    "REFERRED_FOR_LEGAL_AID",
    "CLOSED",
    "ERASED",
)
ALLOWED_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    "SUBMITTED": ("UNDER_REVIEW", "CLOSED"),
    "UNDER_REVIEW": ("INFO_REQUESTED", "READY_FOR_SUBMISSION", "REFERRED_FOR_LEGAL_AID", "CLOSED"),
    "INFO_REQUESTED": ("UNDER_REVIEW", "CLOSED"),
    "READY_FOR_SUBMISSION": ("UNDER_REVIEW", "CLOSED"),
    "REFERRED_FOR_LEGAL_AID": ("UNDER_REVIEW", "CLOSED"),
    "CLOSED": ("UNDER_REVIEW",),
    "ERASED": (),
}
RECORD_TYPES = ("real", "field_test", "synthetic_demo")
TENANCY_REVIEW_STATES = ("claimant_provided", "document_supported", "awaiting_legal_review")

GENESIS_HASH = "0" * 64


class TransitionError(ValueError):
    """Raised when a requested status change is not an allowed transition."""


def now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc
    )


class PramaanaStore:
    """Thin data-access layer over SQLite. One connection per operation."""

    def __init__(self, db_path: str, base_dir: str) -> None:
        self.db_path = db_path
        self.base_dir = base_dir
        self.migrate()

    # ------------------------------------------------------------------ infra
    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
            version = int(row["value"]) if row else 0
            if version < 1:
                # v1 = the original app's table (kept as-is, never rewritten)
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS reviewer_audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        claim_id TEXT NOT NULL, action TEXT NOT NULL,
                        reviewer TEXT NOT NULL, note TEXT NOT NULL,
                        timestamp_utc TEXT NOT NULL)"""
                )
            if version < 2:
                conn.executescript(_SCHEMA_V2)
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES('version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def resolve(self, rel_path: Optional[str]) -> Optional[str]:
        if not rel_path:
            return None
        return rel_path if os.path.isabs(rel_path) else os.path.join(self.base_dir, rel_path)

    def relpath(self, abs_path: str) -> str:
        return os.path.relpath(abs_path, self.base_dir).replace("\\", "/")

    # -------------------------------------------------------------- reviewers
    def create_reviewer(self, username: str, password_hash: str, role: str = "reviewer") -> None:
        if role not in ("reviewer", "admin"):
            raise ValueError("role must be 'reviewer' or 'admin'")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO reviewers(username, password_hash, role, created_at_utc, active) "
                "VALUES(?,?,?,?,1)",
                (username, password_hash, role, now_utc()),
            )

    def set_reviewer_password(self, username: str, password_hash: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE reviewers SET password_hash=? WHERE username=?", (password_hash, username)
            )

    def get_reviewer(self, username: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM reviewers WHERE username=? AND active=1", (username,)
            ).fetchone()
            return dict(row) if row else None

    def reviewer_count(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM reviewers WHERE active=1").fetchone()[0]

    def touch_login(self, username: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE reviewers SET last_login_utc=? WHERE username=?", (now_utc(), username)
            )

    # ------------------------------------------------------------------ cases
    def new_case_id(self, record_type: str) -> str:
        prefix = "DEMO" if record_type == "synthetic_demo" else (
            "TEST" if record_type == "field_test" else "PRM"
        )
        year = datetime.datetime.now(datetime.timezone.utc).year
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I confusion
        with self.connect() as conn:
            while True:
                suffix = "".join(secrets.choice(alphabet) for _ in range(6))
                case_id = f"{prefix}-{year}-{suffix}"
                if not conn.execute("SELECT 1 FROM cases WHERE case_id=?", (case_id,)).fetchone():
                    return case_id

    def find_case_by_submission_id(self, submission_id: str) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT case_id FROM cases WHERE client_submission_id=?", (submission_id,)
            ).fetchone()
            return row["case_id"] if row else None

    def insert_case(self, fields: Dict[str, Any]) -> None:
        if fields.get("record_type") not in RECORD_TYPES:
            raise ValueError("invalid record_type")
        cols = ", ".join(fields.keys())
        marks = ", ".join("?" for _ in fields)
        with self.connect() as conn:
            conn.execute(f"INSERT INTO cases ({cols}) VALUES ({marks})", tuple(fields.values()))

    def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
            return dict(row) if row else None

    def list_cases(
        self,
        status: Optional[str] = None,
        record_type: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM cases WHERE 1=1"
        args: List[Any] = []
        if status:
            sql += " AND status=?"
            args.append(status)
        if record_type:
            sql += " AND record_type=?"
            args.append(record_type)
        if query:
            sql += " AND (case_id LIKE ? OR village LIKE ?)"
            args.extend([f"%{query}%", f"%{query}%"])
        sql += " ORDER BY created_at_utc DESC"
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

    def update_case_fields(self, case_id: str, fields: Dict[str, Any]) -> None:
        fields = dict(fields, updated_at_utc=now_utc())
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE cases SET {sets} WHERE case_id=?", (*fields.values(), case_id)
            )

    def transition_case(
        self, case_id: str, new_status: str, actor_type: str, actor_id: str, note: str
    ) -> Dict[str, Any]:
        case = self.get_case(case_id)
        if not case:
            raise KeyError(case_id)
        old = case["status"]
        if new_status not in ALLOWED_TRANSITIONS.get(old, ()):
            raise TransitionError(f"Cannot move a case from {old} to {new_status}.")
        self.update_case_fields(case_id, {"status": new_status})
        return self.append_audit(
            case_id, "STATUS_CHANGE", actor_type, actor_id, note,
            prev_status=old, new_status=new_status,
        )

    # --------------------------------------------------------------- evidence
    def insert_evidence(self, fields: Dict[str, Any]) -> str:
        fields = dict(fields)
        fields.setdefault("evidence_id", "EV-" + uuid.uuid4().hex[:12].upper())
        fields.setdefault("uploaded_at_utc", now_utc())
        fields.setdefault("status", "active")
        cols = ", ".join(fields.keys())
        marks = ", ".join("?" for _ in fields)
        with self.connect() as conn:
            conn.execute(f"INSERT INTO evidence ({cols}) VALUES ({marks})", tuple(fields.values()))
        return fields["evidence_id"]

    def list_evidence(self, case_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence WHERE case_id=? ORDER BY uploaded_at_utc, rowid", (case_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_evidence(self, evidence_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
            return dict(row) if row else None

    def verify_evidence_file(self, evidence_id: str, actor_type: str, actor_id: str) -> Dict[str, Any]:
        """Recompute SHA-256 of the stored bytes and compare with the recorded hash.

        The recorded hash is never overwritten; each check is stored separately.
        """
        ev = self.get_evidence(evidence_id)
        if not ev:
            raise KeyError(evidence_id)
        path = self.resolve(ev["stored_path"])
        computed: Optional[str] = None
        if ev["status"] == "erased":
            result = "ERASED"
        elif not path or not os.path.exists(path):
            result = "FILE_MISSING"
        else:
            computed = sha256_file(path)
            result = "MATCH" if computed == ev["sha256"] else "MISMATCH"
        ts = now_utc()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO evidence_verifications(evidence_id, checked_at_utc, computed_sha256, "
                "result, actor_type, actor_id) VALUES(?,?,?,?,?,?)",
                (evidence_id, ts, computed, result, actor_type, actor_id),
            )
            conn.execute(
                "UPDATE evidence SET last_verified_at_utc=?, last_verification_result=? "
                "WHERE evidence_id=?",
                (ts, result, evidence_id),
            )
        self.append_audit(
            ev["case_id"], "EVIDENCE_INTEGRITY_CHECK", actor_type, actor_id,
            f"{evidence_id}: {result}", ref_type="evidence", ref_id=evidence_id,
        )
        return {"evidence_id": evidence_id, "result": result, "computed_sha256": computed,
                "recorded_sha256": ev["sha256"], "checked_at_utc": ts}

    def list_verifications(self, evidence_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM evidence_verifications WHERE evidence_id=? ORDER BY id",
                (evidence_id,),
            ).fetchall()]

    # -------------------------------------------------------------- analyses
    def insert_analysis(self, case_id: str, record: Dict[str, Any], actor_id: str) -> str:
        analysis_id = "SA-" + uuid.uuid4().hex[:10].upper()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO satellite_analyses(analysis_id, case_id, requested_at_utc, status, "
                "provenance, analysis_version, dataset, record_json, requested_by) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    analysis_id, case_id, now_utc(), record["status"], record["provenance"],
                    record.get("analysis_version", ""), record.get("dataset", ""),
                    json.dumps(record, sort_keys=True), actor_id,
                ),
            )
        return analysis_id

    def list_analyses(self, case_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM satellite_analyses WHERE case_id=? ORDER BY requested_at_utc, rowid",
                (case_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["record"] = json.loads(d.pop("record_json"))
            out.append(d)
        return out

    # -------------------------------------------------------------- documents
    def insert_document(self, fields: Dict[str, Any]) -> None:
        cols = ", ".join(fields.keys())
        marks = ", ".join("?" for _ in fields)
        with self.connect() as conn:
            conn.execute(f"INSERT INTO documents ({cols}) VALUES ({marks})", tuple(fields.values()))

    def next_document_version(self, case_id: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM documents WHERE case_id=?", (case_id,)
            ).fetchone()
            return int(row[0]) + 1

    def list_documents(self, case_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM documents WHERE case_id=? ORDER BY version DESC", (case_id,)
            ).fetchall()]

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
            return dict(row) if row else None

    def find_by_sha256(self, digest: str) -> Dict[str, List[Dict[str, Any]]]:
        """Look up generated documents and evidence whose recorded hash matches."""
        with self.connect() as conn:
            docs = [dict(r) for r in conn.execute(
                "SELECT doc_id, case_id, version, generated_at_utc, is_synthetic FROM documents "
                "WHERE sha256=?", (digest,)
            ).fetchall()]
            evs = [dict(r) for r in conn.execute(
                "SELECT evidence_id, case_id, kind, uploaded_at_utc, is_synthetic FROM evidence "
                "WHERE sha256=?", (digest,)
            ).fetchall()]
        return {"documents": docs, "evidence": evs}

    # ------------------------------------------------------------------ audit
    def append_audit(
        self,
        case_id: Optional[str],
        action: str,
        actor_type: str,
        actor_id: str,
        note: str = "",
        prev_status: Optional[str] = None,
        new_status: Optional[str] = None,
        ref_type: Optional[str] = None,
        ref_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append one event; its hash covers its fields plus the previous hash."""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            last = conn.execute(
                "SELECT event_hash FROM audit_events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev_hash = last["event_hash"] if last else GENESIS_HASH
            event = {
                "event_id": uuid.uuid4().hex,
                "case_id": case_id,
                "action": action,
                "actor_type": actor_type,
                "actor_id": actor_id,
                "timestamp_utc": now_utc(),
                "prev_status": prev_status,
                "new_status": new_status,
                "note": note,
                "ref_type": ref_type,
                "ref_id": ref_id,
                "prev_hash": prev_hash,
            }
            event["event_hash"] = _hash_event(event)
            cols = ", ".join(event.keys())
            marks = ", ".join("?" for _ in event)
            conn.execute(f"INSERT INTO audit_events ({cols}) VALUES ({marks})", tuple(event.values()))
        return event

    def list_audit(self, case_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            if case_id:
                rows = conn.execute(
                    "SELECT * FROM audit_events WHERE case_id=? ORDER BY seq", (case_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM audit_events ORDER BY seq").fetchall()
            return [dict(r) for r in rows]

    def verify_audit_chain(self) -> Dict[str, Any]:
        events = self.list_audit()
        prev = GENESIS_HASH
        for ev in events:
            body = {k: ev[k] for k in _AUDIT_HASH_FIELDS}
            if ev["prev_hash"] != prev or _hash_event(body) != ev["event_hash"]:
                return {"intact": False, "events": len(events), "broken_at_seq": ev["seq"]}
            prev = ev["event_hash"]
        return {"intact": True, "events": len(events), "broken_at_seq": None}

    def list_legacy_audit(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM reviewer_audit_log ORDER BY id"
            ).fetchall()]


_AUDIT_HASH_FIELDS = (
    "event_id", "case_id", "action", "actor_type", "actor_id", "timestamp_utc",
    "prev_status", "new_status", "note", "ref_type", "ref_id", "prev_hash",
)


def _hash_event(event: Dict[str, Any]) -> str:
    body = {k: event.get(k) for k in _AUDIT_HASH_FIELDS}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def sha256_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS reviewers (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('reviewer','admin')),
    created_at_utc TEXT NOT NULL,
    last_login_utc TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL CHECK (record_type IN ('real','field_test','synthetic_demo')),
    status TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    client_submission_id TEXT UNIQUE,
    tracking_token_hash TEXT,
    -- claimant (claimant-provided; minimal)
    claimant_name TEXT,
    guardian_name TEXT,
    phone TEXT,
    assisted_by TEXT,
    -- tenancy (claimant-provided; never auto-classified)
    tenancy_category TEXT,
    landowner_name TEXT,
    tenancy_documents TEXT,
    tenancy_review_status TEXT NOT NULL DEFAULT 'claimant_provided',
    -- field
    village TEXT,
    gram_panchayat TEXT,
    block TEXT,
    district TEXT,
    jl_number TEXT,
    khatian_no TEXT,
    plot_dag_no TEXT,
    latitude REAL,
    longitude REAL,
    location_source TEXT,
    location_accuracy_m REAL,
    location_captured_at_utc TEXT,
    -- crop & damage (claimant-reported)
    crop TEXT,
    season TEXT,
    area_acres REAL,
    incident_date TEXT,
    incident_time TEXT,
    incident_start_utc TEXT,
    damage_type TEXT,
    damage_description TEXT,
    reported_affected_pct REAL,
    -- scheme / intimation
    insurance_scheme TEXT,
    intimation_status TEXT,
    intimation_reference TEXT,
    -- consent
    consent_given INTEGER NOT NULL DEFAULT 0,
    consent_version TEXT,
    consent_at_utc TEXT,
    erasure_requested_at_utc TEXT,
    erased_at_utc TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(case_id),
    kind TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK (provenance IN ('farmer_capture','live_sentinel','synthetic_demo')),
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    original_filename TEXT,
    stored_path TEXT,
    mime_type TEXT,
    size_bytes INTEGER,
    sha256 TEXT NOT NULL,
    client_sha256 TEXT,
    client_hash_match INTEGER,
    uploaded_at_utc TEXT NOT NULL,
    embedded_capture_time TEXT,
    embedded_gps_lat REAL,
    embedded_gps_lon REAL,
    metadata_json TEXT,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    last_verified_at_utc TEXT,
    last_verification_result TEXT
);
CREATE INDEX IF NOT EXISTS idx_evidence_case ON evidence(case_id);

CREATE TABLE IF NOT EXISTS evidence_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
    checked_at_utc TEXT NOT NULL,
    computed_sha256 TEXT,
    result TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS satellite_analyses (
    analysis_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(case_id),
    requested_at_utc TEXT NOT NULL,
    status TEXT NOT NULL,
    provenance TEXT NOT NULL,
    analysis_version TEXT,
    dataset TEXT,
    record_json TEXT NOT NULL,
    requested_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(case_id),
    doc_type TEXT NOT NULL,
    version INTEGER NOT NULL,
    generated_at_utc TEXT NOT NULL,
    generated_by TEXT NOT NULL,
    file_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    is_synthetic INTEGER NOT NULL,
    generator_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    case_id TEXT,
    action TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    prev_status TEXT,
    new_status TEXT,
    note TEXT,
    ref_type TEXT,
    ref_id TEXT,
    prev_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_events(case_id);

CREATE TRIGGER IF NOT EXISTS audit_events_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
"""
