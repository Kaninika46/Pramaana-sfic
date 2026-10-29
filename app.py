"""Pramaana web application — farmer case reporting and reviewer workflow.

Flow: a farmer or field operator reports a suspected flood loss -> evidence is
uploaded and SHA-256 fingerprinted on the server -> location and its source are
recorded -> a signed-in reviewer runs satellite analysis (only when Earth Engine
is genuinely available), re-checks evidence integrity, generates a clearly
labelled dossier, and records review decisions in a hash-chained audit log.

Run:  python app.py           (development server, http://localhost:5000)
      gunicorn app:app        (Procfile)
Reviewer accounts:  flask --app app create-reviewer <username> --role admin
"""

from __future__ import annotations

import datetime
import functools
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import click
from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash

from gee_fetcher import (
    ANALYSIS_DEFAULTS,
    ANALYSIS_LIMITATIONS,
    SATELLITE_ANALYSIS_VERSION,
    SATELLITE_UNAVAILABLE_MESSAGE,
    analyze_case_location,
    initialize_gee_with_project,
    render_synthetic_placeholder,
    validate_coordinates,
)
from pramaana_dossier import DOSSIER_GENERATOR_VERSION, fmt_size, generate_case_dossier, mask_phone
from pramaana_engine import load_legal_rules
from pramaana_rules import assess_deadline, incident_start_utc, missing_items
from pramaana_store import (
    ALLOWED_TRANSITIONS,
    CASE_STATUSES,
    RECORD_TYPES,
    TENANCY_REVIEW_STATES,
    PramaanaStore,
    TransitionError,
    now_utc,
    sha256_file,
    sha256_text,
)
import pramaana_i18n as i18n
from pramaana_text import CONSENT, CONSENT_BN_REVIEWED, FARMER_STATUS, FIELD, LABELS

APP_VERSION = "2.0.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Evidence files and dossiers live under the storage root (default: the project folder).
STORAGE_DIR = os.path.abspath(os.environ.get("PRAMAANA_STORAGE_DIR") or BASE_DIR)
UPLOAD_DIR = os.path.join(STORAGE_DIR, "uploads")
DOSSIER_DIR = os.path.join(STORAGE_DIR, "dossiers")
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
DB_PATH = os.environ.get("PRAMAANA_DB") or os.environ.get(
    "PRAMAANA_AUDIT_DB", os.path.join(BASE_DIR, "pramaana_audit.db")
)
for _d in (UPLOAD_DIR, DOSSIER_DIR, INSTANCE_DIR):
    os.makedirs(_d, exist_ok=True)

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES_PER_SUBMISSION = 10


def _load_secret_key() -> str:
    """Use PRAMAANA_SECRET_KEY, else a key persisted in instance/ so sessions survive restarts."""
    env_key = os.environ.get("PRAMAANA_SECRET_KEY", "").strip()
    if env_key:
        return env_key
    key_path = os.path.join(INSTANCE_DIR, "secret_key")
    if os.path.exists(key_path):
        with open(key_path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    key = secrets.token_hex(32)
    with open(key_path, "w", encoding="utf-8") as fh:
        fh.write(key)
    return key


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_load_secret_key(),
    MAX_CONTENT_LENGTH=MAX_FILES_PER_SUBMISSION * MAX_FILE_BYTES + 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("PRAMAANA_HTTPS_ONLY") == "1",
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(hours=8),
)

store = PramaanaStore(DB_PATH, STORAGE_DIR)


class EarthEngineState:
    """Earth Engine readiness, checked at startup and retried on demand."""

    def __init__(self) -> None:
        self.ready = False
        self.error: Optional[str] = None
        self.checked_at: Optional[str] = None
        self.refresh()

    def refresh(self) -> None:
        self.ready, self.error = initialize_gee_with_project()
        self.checked_at = now_utc()
        if not self.ready:
            app.logger.warning("Earth Engine unavailable: %s", self.error)

    @property
    def message(self) -> str:
        return "Earth Engine initialised." if self.ready else (
            f"{SATELLITE_UNAVAILABLE_MESSAGE} {self.error or ''}".strip()
        )


ee_state = EarthEngineState()


def _bootstrap_reviewer_from_env() -> None:
    """Create a reviewer from PRAMAANA_REVIEWER_USER/PASS if set (no defaults exist)."""
    user = os.environ.get("PRAMAANA_REVIEWER_USER", "").strip()
    password = os.environ.get("PRAMAANA_REVIEWER_PASS", "")
    if not user or not password:
        return
    if len(password) < 10:
        app.logger.warning("PRAMAANA_REVIEWER_PASS is shorter than 10 characters; ignored.")
        return
    if not store.get_reviewer(user):
        role = os.environ.get("PRAMAANA_REVIEWER_ROLE", "admin")
        store.create_reviewer(user, generate_password_hash(password), role)
        store.append_audit(None, "REVIEWER_CREATED", "system", "env-bootstrap", f"{user} ({role})")


_bootstrap_reviewer_from_env()


# --------------------------------------------------------------------------- language
@app.before_request
def _set_language() -> None:
    """Farmer pages follow the visitor's choice (cookie); all other pages stay English."""
    chosen = i18n.normalise(request.cookies.get(i18n.LANG_COOKIE))
    g.lang = chosen if request.endpoint in i18n.FARMER_ENDPOINTS else i18n.DEFAULT_LANG


def current_lang() -> str:
    return getattr(g, "lang", i18n.DEFAULT_LANG)


def tr(key: str, **params: Any) -> str:
    """Translated text for the current request."""
    return i18n.t(key, current_lang(), **params)


def bi(key: str, **params: Any) -> i18n.Bi:
    """Text in both languages, shown in the current one (lets farmer pages switch in place)."""
    return i18n.both(key, current_lang(), **params)


def field_label(name: str) -> i18n.Bi:
    en, bn = FIELD[name]
    return i18n.Bi(en, bn, current_lang())


def label_bi(group: str, value: Any) -> i18n.Bi:
    en = LABELS.get(group, {}).get(value or "", value or "—")
    return i18n.Bi(en, i18n.LABELS_BN.get(group, {}).get(value or "", en), current_lang())


def label_param(group: str, value: Any) -> Dict[str, str]:
    """A label as a bilingual parameter for bi(): {"en": ..., "bn": ...}."""
    return label_bi(group, value).as_dict()


def flash_bi(message: i18n.Bi, category: str) -> None:
    flash(message.as_dict(), category)  # both languages survive the redirect


def _safe_next(target: Optional[str]) -> str:
    """Only same-site paths, so the language link cannot redirect elsewhere."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return url_for("index")
    return target


@app.route("/lang/<code>")
def set_language(code: str) -> Any:
    if code not in i18n.SUPPORTED:
        abort(404)
    resp = redirect(_safe_next(request.args.get("next")))
    # Not HttpOnly on purpose: it only holds "en" or "bn", and pramaana.js sets the same
    # cookie when it switches the page in place, so the next page loads in that language.
    resp.set_cookie(i18n.LANG_COOKIE, code, max_age=365 * 24 * 3600, httponly=False,
                    samesite="Lax", secure=app.config["SESSION_COOKIE_SECURE"])
    return resp


# --------------------------------------------------------------------------- security
@app.before_request
def _csrf_protect() -> None:
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, description=bi("err.csrf"))


def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@app.after_request
def _security_headers(resp: Any) -> Any:
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
        "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    if request.path.startswith(("/reviewer", "/track")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


class RateLimiter:
    """Small in-memory sliding-window limiter (per process; adequate for a prototype)."""

    def __init__(self, limit: int, window_s: int) -> None:
        self.limit, self.window_s = limit, window_s
        self.hits: Dict[str, Deque[float]] = defaultdict(deque)

    def blocked(self, key: str) -> bool:
        q = self.hits[key]
        cutoff = time.monotonic() - self.window_s
        while q and q[0] < cutoff:
            q.popleft()
        return len(q) >= self.limit

    def hit(self, key: str) -> None:
        self.hits[key].append(time.monotonic())


login_limiter = RateLimiter(limit=5, window_s=15 * 60)
track_limiter = RateLimiter(limit=10, window_s=15 * 60)
submit_limiter = RateLimiter(limit=20, window_s=60 * 60)


def current_reviewer() -> Optional[Dict[str, Any]]:
    if "reviewer" not in g:
        username = session.get("reviewer_user")
        g.reviewer = store.get_reviewer(username) if username else None
    return g.reviewer


def reviewer_required(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not current_reviewer():
            if request.method == "GET":
                return redirect(url_for("reviewer_login", next=request.path))
            abort(403, description="Reviewer sign-in required.")
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn: Callable) -> Callable:
    @functools.wraps(fn)
    @reviewer_required
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if current_reviewer()["role"] != "admin":
            abort(403, description="This action needs an administrator account.")
        return fn(*args, **kwargs)
    return wrapper


@app.context_processor
def _template_globals() -> Dict[str, Any]:
    return {
        "csrf_token": csrf_token,
        "reviewer": current_reviewer(),
        "L": LABELS,
        "F": FIELD,
        "ee_state": ee_state,
        "app_version": APP_VERSION,
        "fmt_size": fmt_size,
        "mask_phone": mask_phone,
        "lang": current_lang(),
        "t": tr,
        "tx": bi,
        "pair": lambda en, bn: i18n.Bi(en, bn, current_lang()),
        "tb": lambda key, **params: i18n.span(bi(key, **params)),
        "ta": i18n.attrs,
        "tl": label_bi,
        "tlp": label_param,
        "fl": field_label,
        "i18n_json": i18n.i18n_json,
        "lang_names": i18n.LANG_NAMES,
        "lang_cookie": i18n.LANG_COOKIE,
        "farmer_page": request.endpoint in i18n.FARMER_ENDPOINTS,
        "js_i18n": {lang: i18n.js_strings(lang) for lang in i18n.SUPPORTED},
    }


@app.template_filter("bi")
def _bi_filter(value: Any) -> Any:
    """Bilingual text (or a flashed {"en","bn"} dict) as a switchable element; anything else escaped."""
    if isinstance(value, dict) and set(value) == {"en", "bn"}:
        value = i18n.Bi.from_dict(value, current_lang())
    return i18n.span(value)


@app.template_filter("label")
def _label_filter(value: Any, group: str) -> str:
    if current_lang() == "bn" and (value or "") in i18n.LABELS_BN.get(group, {}):
        return i18n.LABELS_BN[group][value]
    return LABELS.get(group, {}).get(value or "", value or "—")


@app.errorhandler(HTTPException)
def _http_error(exc: HTTPException) -> Any:
    if isinstance(exc, RequestEntityTooLarge):
        exc.description = bi("err.too_large", mb=MAX_FILE_BYTES // 1048576)
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "code": exc.code, "message": exc.description}), exc.code
    message = exc.description
    if message == type(exc).description and request.endpoint in i18n.FARMER_ENDPOINTS:
        # Werkzeug's built-in English text; our own messages are already bilingual.
        message = i18n.Bi(message, i18n.t("error.generic_404" if exc.code == 404 else "error.generic", "bn"),
                          current_lang())
    return render_template("error.html", code=exc.code, message=message), exc.code


@app.errorhandler(Exception)
def _unexpected_error(exc: Exception) -> Any:
    app.logger.exception("Unhandled error")
    return render_template("error.html", code=500, message=bi("err.server")), 500


# --------------------------------------------------------------------------- uploads
_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                "image/heic": ".heic"}
_DOC_TYPES = {"application/pdf": ".pdf", **_IMAGE_TYPES}
_AUDIO_TYPES = {"audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/wav": ".wav",
                "audio/ogg": ".ogg", "audio/webm": ".webm", "audio/aac": ".aac",
                "audio/amr": ".amr", "audio/3gpp": ".3gp"}
UPLOAD_KINDS = {"photos": ("photo", _IMAGE_TYPES), "documents": ("document", _DOC_TYPES),
                "voice": ("audio", _AUDIO_TYPES)}


def sniff_mime(data: bytes) -> Optional[str]:
    """Identify a file from its leading bytes; the browser-declared type is not trusted."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[:4] == b"OggS":
        return "audio/ogg"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "audio/webm"
    if data[:6] == b"#!AMR\n":
        return "audio/amr"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] in (0xFB, 0xF3, 0xF2)):
        return "audio/mpeg"
    if len(data) > 1 and data[0] == 0xFF and data[1] in (0xF1, 0xF9):
        return "audio/aac"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"heic", b"heix", b"mif1", b"msf1", b"heif", b"hevc"):
            return "image/heic"
        if brand.startswith(b"3gp"):
            return "audio/3gpp"
        if brand in (b"M4A ", b"isom", b"mp42", b"mp41", b"dash"):
            return "audio/mp4"
    return None


def _exif_summary(path: str) -> Dict[str, Any]:
    """Read embedded capture time / GPS if present. Values are unverified claims."""
    out: Dict[str, Any] = {}
    try:
        from PIL import Image
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return out
            sub = exif.get_ifd(0x8769)
            when = sub.get(36867) or exif.get(306)
            if when:
                out["capture_time"] = str(when)
            gps = exif.get_ifd(0x8825)
            if gps and 2 in gps and 4 in gps:
                def deg(v: Any) -> float:
                    return float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
                lat = deg(gps[2]) * (-1 if gps.get(1) == "S" else 1)
                lon = deg(gps[4]) * (-1 if gps.get(3) == "W" else 1)
                out["gps"] = (round(lat, 6), round(lon, 6))
            out["camera"] = " ".join(str(x) for x in (exif.get(271), exif.get(272)) if x) or None
    except Exception:
        pass
    return out


def collect_uploads() -> Tuple[List[Dict[str, Any]], List[str]]:
    """Read and validate uploaded files from the current request (nothing written yet)."""
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    try:
        client_hashes = json.loads(request.form.get("client_hashes") or "[]")
    except ValueError:
        client_hashes = []
    hash_lookup = {(h.get("name"), h.get("size")): h.get("sha256") for h in client_hashes
                   if isinstance(h, dict)}
    for field_name, (kind, allowed) in UPLOAD_KINDS.items():
        for storage in request.files.getlist(field_name):
            if not storage or not storage.filename:
                continue
            data = storage.read(MAX_FILE_BYTES + 1)
            name = os.path.basename(storage.filename)[:150]
            if not data:
                errors.append(bi("err.file_empty", name=name))
                continue
            if len(data) > MAX_FILE_BYTES:
                errors.append(bi("err.file_too_large", name=name, mb=MAX_FILE_BYTES // 1048576))
                continue
            mime = sniff_mime(data)
            if mime not in allowed:
                kind_label = label_param("evidence_kind", kind)
                errors.append(bi("err.file_type", name=name,
                                 kind={"en": kind_label["en"].lower(), "bn": kind_label["bn"]}))
                continue
            client = hash_lookup.get((storage.filename, len(data)))
            if client and not re.fullmatch(r"[0-9a-f]{64}", str(client)):
                client = None
            items.append({"kind": kind, "name": name, "data": data, "mime": mime,
                          "ext": allowed[mime], "client_sha256": client})
    if len(items) > MAX_FILES_PER_SUBMISSION:
        errors.append(bi("err.too_many_files", n=MAX_FILES_PER_SUBMISSION))
    return items, errors


def store_uploads(case_id: str, items: List[Dict[str, Any]], actor_type: str, actor_id: str) -> List[str]:
    """Write files byte-for-byte, hash them, and record evidence + audit events."""
    case_dir = os.path.join(UPLOAD_DIR, case_id)
    os.makedirs(case_dir, exist_ok=True)
    ids = []
    for it in items:
        evidence_id = "EV-" + uuid.uuid4().hex[:12].upper()
        path = os.path.join(case_dir, evidence_id + it["ext"])
        digest = hashlib.sha256(it["data"]).hexdigest()
        with open(path, "wb") as fh:
            fh.write(it["data"])
        if sha256_file(path) != digest:
            raise IOError("Stored file does not match received bytes.")
        meta = _exif_summary(path) if it["mime"].startswith("image/") else {}
        client = it.get("client_sha256")
        store.insert_evidence({
            "evidence_id": evidence_id,
            "case_id": case_id,
            "kind": it["kind"],
            "provenance": "farmer_capture",
            "is_synthetic": 0,
            "original_filename": it["name"],
            "stored_path": store.relpath(path),
            "mime_type": it["mime"],
            "size_bytes": len(it["data"]),
            "sha256": digest,
            "client_sha256": client,
            "client_hash_match": None if not client else int(client == digest),
            "embedded_capture_time": meta.get("capture_time"),
            "embedded_gps_lat": (meta.get("gps") or (None, None))[0],
            "embedded_gps_lon": (meta.get("gps") or (None, None))[1],
            "metadata_json": json.dumps({k: v for k, v in meta.items() if v}),
        })
        store.append_audit(case_id, "EVIDENCE_RECEIVED", actor_type, actor_id,
                           f"{evidence_id} {it['kind']} sha256={digest}",
                           ref_type="evidence", ref_id=evidence_id)
        ids.append(evidence_id)
    return ids


# --------------------------------------------------------------------------- forms
def _clean(name: str, max_len: int = 200) -> Optional[str]:
    value = (request.form.get(name) or "").strip()
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    return value[:max_len] or None


def _choice(name: str, options: Any, default: Optional[str] = None) -> Optional[str]:
    value = request.form.get(name) or default
    return value if value in options else default


def parse_case_form() -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Validate the report form. Returns (fields, errors keyed by field name)."""
    errors: Dict[str, str] = {}
    f: Dict[str, Any] = {
        "claimant_name": _clean("claimant_name", 120),
        "guardian_name": _clean("guardian_name", 120),
        "phone": _clean("phone", 20),
        "assisted_by": _clean("assisted_by", 120),
        "tenancy_category": _choice("tenancy_category", LABELS["tenancy"], "unsure"),
        "landowner_name": _clean("landowner_name", 120),
        "tenancy_documents": _clean("tenancy_documents", 500),
        "village": _clean("village", 120),
        "gram_panchayat": _clean("gram_panchayat", 120),
        "block": _clean("block", 120),
        "district": _clean("district", 120),
        "jl_number": _clean("jl_number", 40),
        "khatian_no": _clean("khatian_no", 40),
        "plot_dag_no": _clean("plot_dag_no", 40),
        "crop": _clean("crop", 80),
        "season": _clean("season", 40),
        "incident_date": _clean("incident_date", 10),
        "incident_time": _clean("incident_time", 5),
        "damage_type": _choice("damage_type", LABELS["damage_type"]),
        "damage_description": _clean("damage_description", 2000),
        "insurance_scheme": _choice("insurance_scheme", LABELS["scheme"], "UNKNOWN"),
        "intimation_status": _choice("intimation_status", LABELS["intimation_status"], "unknown"),
        "intimation_reference": _clean("intimation_reference", 80),
        "record_type": _choice("record_type", ("real", "field_test"), "real"),
    }
    for key in ("claimant_name", "village", "crop", "incident_date", "damage_description"):
        if not f[key]:
            errors[key] = bi("err.required")
    if f["claimant_name"] and len(f["claimant_name"]) < 2:
        errors["claimant_name"] = bi("err.full_name")
    if not f["damage_type"]:
        errors["damage_type"] = bi("err.damage_type")
    if f["phone"]:
        digits = re.sub(r"\D", "", f["phone"])
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        if not re.fullmatch(r"[6-9]\d{9}", digits):
            errors["phone"] = bi("err.phone")
        else:
            f["phone"] = digits
    today = datetime.datetime.now(datetime.timezone.utc).date()
    if f["incident_date"]:
        try:
            day = datetime.date.fromisoformat(f["incident_date"])
            if day > today + datetime.timedelta(days=1):
                errors["incident_date"] = bi("err.future")
            elif day < datetime.date(2015, 1, 1):
                errors["incident_date"] = bi("err.year")
        except ValueError:
            errors["incident_date"] = bi("err.date_format")
    if f["incident_time"] and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", f["incident_time"]):
        errors["incident_time"] = bi("err.time_format")
    for key, lo, hi in (("area_acres", 0.001, 1000.0), ("reported_affected_pct", 0.0, 100.0)):
        raw = _clean(key, 20)
        f[key] = None
        if raw:
            try:
                val = float(raw)
                if not lo <= val <= hi:
                    raise ValueError
                f[key] = val
            except ValueError:
                errors[key] = bi("err.number_range", lo=f"{lo:g}", hi=f"{hi:g}")
    lat_raw, lon_raw = _clean("latitude", 20), _clean("longitude", 20)
    f.update(latitude=None, longitude=None, location_source="none",
             location_accuracy_m=None, location_captured_at_utc=None)
    if lat_raw or lon_raw:
        try:
            f["latitude"], f["longitude"] = validate_coordinates(lat_raw, lon_raw)
            gps = request.form.get("location_source") == "device_gps"
            f["location_source"] = "device_gps" if gps else "manual"
            f["location_captured_at_utc"] = now_utc()
            if gps:
                try:
                    acc = float(request.form.get("location_accuracy_m") or "")
                    f["location_accuracy_m"] = acc if 0 < acc < 100000 else None
                except ValueError:
                    pass
        except ValueError as exc:
            errors["latitude"] = i18n.Bi(str(exc), i18n.t("err.coordinates", "bn"), current_lang())
    if request.form.get("consent") != "yes":
        errors["consent"] = bi("err.consent")
    return f, errors


# --------------------------------------------------------------------------- views: public
@app.route("/")
def index() -> str:
    return render_template("home.html")


def _consent_context() -> Dict[str, Any]:
    # Both texts are on the page; the language switch shows one (see report.html).
    return {"consent_en": CONSENT["en"][0], "consent_bn": CONSENT["bn"][0],
            "consent_lang": current_lang(), "consent_bn_draft": not CONSENT_BN_REVIEWED}


@app.route("/report", methods=["GET", "POST"])
def report() -> Any:
    if request.method == "GET":
        return render_template("report.html", values={}, errors={}, file_errors=[],
                               submission_id=uuid.uuid4().hex, **_consent_context())
    submission_id = re.sub(r"[^0-9a-f]", "", request.form.get("submission_id", ""))[:32] or None
    if submission_id:
        existing = store.find_case_by_submission_id(submission_id)
        if existing:
            flash_bi(bi("report.already"), "info")
            return redirect(url_for("report_done", case_id=existing))
    ip = request.remote_addr or "?"
    if submit_limiter.blocked(ip):
        abort(429, description=bi("err.too_many_reports"))
    fields, errors = parse_case_form()
    items, file_errors = collect_uploads()
    if errors or file_errors:
        return render_template("report.html", values=request.form, errors=errors,
                               file_errors=file_errors, submission_id=submission_id or uuid.uuid4().hex,
                               **_consent_context()), 422
    submit_limiter.hit(ip)
    case_id = store.new_case_id(fields["record_type"])
    tracking_code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    ts = now_utc()
    # Record the consent text actually shown: the form says which language it displayed.
    consent_version = CONSENT[i18n.normalise(request.form.get("consent_lang"))][1]
    fields.update(
        case_id=case_id, status="SUBMITTED", created_at_utc=ts, updated_at_utc=ts,
        client_submission_id=submission_id, tracking_token_hash=sha256_text(tracking_code),
        incident_start_utc=incident_start_utc(fields["incident_date"], fields["incident_time"]),
        consent_given=1, consent_version=consent_version, consent_at_utc=ts,
    )
    store.insert_case(fields)
    actor = "claimant-or-field-operator (not signed in)"
    store.append_audit(case_id, "CASE_SUBMITTED", "submitter", actor,
                       f"record_type={fields['record_type']}", new_status="SUBMITTED")
    store.append_audit(case_id, "CONSENT_RECORDED", "submitter", actor, consent_version)
    store_uploads(case_id, items, "submitter", actor)
    issued = session.get("issued_codes", {})
    issued[case_id] = tracking_code
    session["issued_codes"] = issued
    session["tracked_case"] = case_id
    return redirect(url_for("report_done", case_id=case_id))


@app.route("/report/done/<case_id>")
def report_done(case_id: str) -> str:
    case = store.get_case(case_id)
    if not case or session.get("tracked_case") != case_id:
        abort(404, description=bi("err.case_not_in_session"))
    code = session.get("issued_codes", {}).get(case_id)
    return render_template("report_done.html", case=case, tracking_code=code,
                           evidence=store.list_evidence(case_id))


@app.route("/track", methods=["GET", "POST"])
def track() -> Any:
    if request.method == "GET":
        return render_template("track.html", error=None)
    ip = request.remote_addr or "?"
    if track_limiter.blocked(ip):
        abort(429, description=bi("err.too_many_attempts"))
    case_id = (request.form.get("case_id") or "").strip().upper()
    code = (request.form.get("tracking_code") or "").strip().upper().replace(" ", "")
    case = store.get_case(case_id)
    if not case or not case["tracking_token_hash"] or not hmac.compare_digest(
            case["tracking_token_hash"], sha256_text(code)):
        track_limiter.hit(ip)
        return render_template("track.html", error=bi("track.bad_code")), 401
    session["tracked_case"] = case_id
    return redirect(url_for("track_case", case_id=case_id))


def _tracked_case_or_404(case_id: str) -> Dict[str, Any]:
    case = store.get_case(case_id)
    if not case or session.get("tracked_case") != case_id:
        abort(404, description=bi("err.open_from_track"))
    return case


@app.route("/track/<case_id>")
def track_case(case_id: str) -> str:
    case = _tracked_case_or_404(case_id)
    evidence = store.list_evidence(case_id)
    notes = [a for a in store.list_audit(case_id) if a["action"] == "STATUS_CHANGE"]
    docs = [d for d in store.list_documents(case_id) if d["status"] == "active"]
    status = FARMER_STATUS.get(case["status"], FARMER_STATUS["SUBMITTED"])
    lang = current_lang()
    deadline = assess_deadline(case, load_legal_rules())
    deadline["message"] = i18n.Bi(deadline["message"], i18n.deadline_message_bn(deadline), lang)
    return render_template(
        "track_case.html", case=case, evidence=evidence, notes=notes,
        farmer_status={"text": i18n.Bi(status["en"], status["bn"], lang),
                       "next": i18n.Bi(status["next"], status["next_bn"], lang)},
        deadline=deadline, latest_doc=docs[0] if docs else None,
        server_now_ms=int(time.time() * 1000),
    )


@app.route("/track/<case_id>/evidence", methods=["POST"])
def track_add_evidence(case_id: str) -> Any:
    case = _tracked_case_or_404(case_id)
    if case["status"] in ("CLOSED", "ERASED"):
        abort(409, description=bi("err.no_new_files"))
    items, errors = collect_uploads()
    for e in errors:
        flash_bi(e, "error")
    if items:
        store_uploads(case_id, items, "submitter", "claimant-or-field-operator (tracking code)")
        flash_bi(bi("case.files_received", count=len(items)), "success")
    elif not errors:
        flash_bi(bi("case.choose_file"), "error")
    return redirect(url_for("track_case", case_id=case_id))


@app.route("/track/<case_id>/erasure-request", methods=["POST"])
def track_erasure_request(case_id: str) -> Any:
    case = _tracked_case_or_404(case_id)
    if not case["erasure_requested_at_utc"]:
        store.update_case_fields(case_id, {"erasure_requested_at_utc": now_utc()})
        store.append_audit(case_id, "ERASURE_REQUESTED", "submitter",
                           "claimant-or-field-operator (tracking code)")
    flash_bi(bi("case.erasure_recorded"), "success")
    return redirect(url_for("track_case", case_id=case_id))


@app.route("/track/<case_id>/dossier/<doc_id>")
def track_download(case_id: str, doc_id: str) -> Any:
    _tracked_case_or_404(case_id)
    return _send_document(doc_id, case_id)


@app.route("/verify", methods=["GET", "POST"])
def verify_file() -> Any:
    result = None
    if request.method == "POST":
        upload = request.files.get("file")
        if not upload or not upload.filename:
            result = {"error": bi("verify.choose")}
        else:
            hasher = hashlib.sha256()
            for chunk in iter(lambda: upload.stream.read(65536), b""):
                hasher.update(chunk)
            digest = hasher.hexdigest()
            result = {"sha256": digest, "filename": os.path.basename(upload.filename),
                      **store.find_by_sha256(digest)}
    return render_template("verify.html", result=result)


@app.route("/about")
def about() -> str:
    rules = load_legal_rules()
    return render_template("about.html", rules=rules, limitations=ANALYSIS_LIMITATIONS,
                           params=ANALYSIS_DEFAULTS, analysis_version=SATELLITE_ANALYSIS_VERSION)


@app.route("/api/health")
def api_health() -> Any:
    return jsonify({
        "status": "ok",
        "version": APP_VERSION,
        "database": "ok" if os.path.exists(DB_PATH) else "missing",
        "earth_engine": {"ready": ee_state.ready, "message": ee_state.message,
                         "checked_at_utc": ee_state.checked_at},
        "reviewers_configured": store.reviewer_count() > 0,
    })


# --------------------------------------------------------------------------- views: reviewer
@app.route("/reviewer/login", methods=["GET", "POST"])
def reviewer_login() -> Any:
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if login_limiter.blocked(ip):
            abort(429, description="Too many failed sign-in attempts. Wait 15 minutes.")
        username = (request.form.get("username") or "").strip()[:64]
        password = request.form.get("password") or ""
        rev = store.get_reviewer(username) if username else None
        if rev and check_password_hash(rev["password_hash"], password):
            session.clear()
            session.permanent = True
            session["reviewer_user"] = rev["username"]
            store.touch_login(rev["username"])
            store.append_audit(None, "REVIEWER_SIGN_IN", "reviewer", rev["username"])
            nxt = request.args.get("next") or ""
            return redirect(nxt if nxt.startswith("/reviewer") else url_for("reviewer_dashboard"))
        login_limiter.hit(ip)
        error = "Username or password is not correct."
    return render_template("reviewer_login.html", error=error,
                           no_reviewers=store.reviewer_count() == 0)


@app.route("/reviewer/logout", methods=["POST"])
def reviewer_logout() -> Any:
    session.clear()
    return redirect(url_for("index"))


def _case_summary(case: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    ev = store.list_evidence(case["case_id"])
    an = store.list_analyses(case["case_id"])
    active = [e for e in ev if e["status"] == "active"]
    return {
        "case": case,
        "evidence_count": len(active),
        "checked": sum(1 for e in active if e["last_verification_result"]),
        "mismatch": sum(1 for e in active if e["last_verification_result"] in ("MISMATCH", "FILE_MISSING")),
        "satellite": an[-1]["status"] if an else None,
        "deadline": assess_deadline(case, rules),
        "gaps": len(missing_items(case, ev, an)),
    }


@app.route("/reviewer")
@reviewer_required
def reviewer_dashboard() -> str:
    status = request.args.get("status") if request.args.get("status") in CASE_STATUSES else None
    rtype = request.args.get("type") if request.args.get("type") in RECORD_TYPES else None
    q = (request.args.get("q") or "").strip()[:40] or None
    rules = load_legal_rules()
    cases = [_case_summary(c, rules) for c in store.list_cases(status, rtype, q)]
    all_cases = store.list_cases()
    counts = {s: sum(1 for c in all_cases if c["status"] == s) for s in CASE_STATUSES}
    return render_template("reviewer_dashboard.html", cases=cases, counts=counts,
                           f_status=status, f_type=rtype, f_q=q or "",
                           legacy_count=len(store.list_legacy_audit()))


def _case_or_404(case_id: str) -> Dict[str, Any]:
    case = store.get_case(case_id)
    if not case:
        abort(404, description="Case not found.")
    return case


@app.route("/reviewer/case/<case_id>")
@reviewer_required
def reviewer_case(case_id: str) -> str:
    case = _case_or_404(case_id)
    rules = load_legal_rules()
    evidence = store.list_evidence(case_id)
    analyses = store.list_analyses(case_id)
    return render_template(
        "reviewer_case.html", case=case, evidence=evidence, analyses=analyses,
        verifications={e["evidence_id"]: store.list_verifications(e["evidence_id"]) for e in evidence},
        documents=store.list_documents(case_id), audit=store.list_audit(case_id),
        deadline=assess_deadline(case, rules), gaps=missing_items(case, evidence, analyses),
        transitions=ALLOWED_TRANSITIONS.get(case["status"], ()),
        tenancy_states=TENANCY_REVIEW_STATES, server_now_ms=int(time.time() * 1000),
    )


@app.route("/reviewer/case/<case_id>/verify", methods=["POST"])
@reviewer_required
def reviewer_verify(case_id: str) -> Any:
    _case_or_404(case_id)
    results = [store.verify_evidence_file(e["evidence_id"], "reviewer", current_reviewer()["username"])
               for e in store.list_evidence(case_id) if e["status"] == "active"]
    if not results:
        flash("There is no evidence to check.", "info")
    else:
        bad = [r for r in results if r["result"] != "MATCH"]
        if bad:
            flash(f"{len(bad)} of {len(results)} file(s) FAILED the integrity check: "
                  + ", ".join(f"{r['evidence_id']} ({r['result']})" for r in bad), "error")
        else:
            flash(f"All {len(results)} file(s) match their recorded SHA-256 hash.", "success")
    return redirect(url_for("reviewer_case", case_id=case_id) + "#evidence")


@app.route("/reviewer/case/<case_id>/satellite", methods=["POST"])
@reviewer_required
def reviewer_satellite(case_id: str) -> Any:
    case = _case_or_404(case_id)
    actor = current_reviewer()["username"]
    if case["record_type"] == "synthetic_demo":
        record = _synthetic_analysis_record(case_id)
    else:
        if not ee_state.ready:
            ee_state.refresh()
        record = analyze_case_location(case.get("latitude"), case.get("longitude"),
                                       case.get("incident_date"), ee_state.ready, ee_state.error)
    analysis_id = store.insert_analysis(case_id, record, actor)
    store.append_audit(case_id, "SATELLITE_ANALYSIS", "reviewer", actor,
                       f"{analysis_id}: {record['status']}", ref_type="analysis", ref_id=analysis_id)
    level = "success" if record["status"] in ("completed", "synthetic") else (
        "info" if record["status"] == "partial" else "error")
    flash(f"Satellite analysis {LABELS['analysis_status'].get(record['status'], record['status'])}: "
          f"{record.get('message') or ''}", level)
    return redirect(url_for("reviewer_case", case_id=case_id) + "#satellite")


@app.route("/reviewer/case/<case_id>/dossier", methods=["POST"])
@reviewer_required
def reviewer_dossier(case_id: str) -> Any:
    case = _case_or_404(case_id)
    if case["status"] == "ERASED":
        abort(409, description="Personal data for this case was erased; no dossier can be generated.")
    actor = current_reviewer()["username"]
    rules = load_legal_rules()
    evidence = store.list_evidence(case_id)
    analyses = store.list_analyses(case_id)
    version = store.next_document_version(case_id)
    doc_id = "DOC-" + uuid.uuid4().hex[:10].upper()
    out_dir = os.path.join(DOSSIER_DIR, case_id)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"Pramaana_Dossier_{case_id}_v{version}.pdf")
    generated_at = now_utc()
    generate_case_dossier(
        output_path=path, doc_id=doc_id, version=version, case=case, evidence=evidence,
        analyses=analyses, audit=store.list_audit(case_id), deadline=assess_deadline(case, rules),
        gaps=missing_items(case, evidence, analyses), legal_rules=rules, labels=LABELS,
        resolve_path=store.resolve, generated_at_utc=generated_at, generated_by=actor,
    )
    digest = sha256_file(path)
    store.insert_document({
        "doc_id": doc_id, "case_id": case_id, "doc_type": "dossier", "version": version,
        "generated_at_utc": generated_at, "generated_by": actor, "file_path": store.relpath(path),
        "sha256": digest, "size_bytes": os.path.getsize(path),
        "is_synthetic": int(case["record_type"] == "synthetic_demo"),
        "generator_version": DOSSIER_GENERATOR_VERSION,
    })
    store.append_audit(case_id, "DOSSIER_GENERATED", "reviewer", actor,
                       f"{doc_id} v{version} sha256={digest}", ref_type="document", ref_id=doc_id)
    flash(f"Dossier v{version} generated. SHA-256: {digest}", "success")
    return redirect(url_for("reviewer_case", case_id=case_id) + "#documents")


def _send_document(doc_id: str, case_id: Optional[str] = None) -> Any:
    doc = store.get_document(doc_id)
    if not doc or (case_id and doc["case_id"] != case_id) or doc["status"] != "active":
        abort(404, description="Document not found.")
    path = store.resolve(doc["file_path"])
    if not path or not os.path.exists(path):
        abort(410, description="The document file is missing from storage. Regenerate it; "
                               "the original hash remains on record.")
    return send_file(path, mimetype="application/pdf", as_attachment=True,
                     download_name=os.path.basename(path))


@app.route("/reviewer/document/<doc_id>")
@reviewer_required
def reviewer_document(doc_id: str) -> Any:
    return _send_document(doc_id)


@app.route("/reviewer/document/<doc_id>/verify", methods=["POST"])
@reviewer_required
def reviewer_document_verify(doc_id: str) -> Any:
    doc = store.get_document(doc_id)
    if not doc:
        abort(404, description="Document not found.")
    path = store.resolve(doc["file_path"])
    if not path or not os.path.exists(path):
        result = "FILE_MISSING"
    else:
        result = "MATCH" if sha256_file(path) == doc["sha256"] else "MISMATCH"
    store.append_audit(doc["case_id"], "DOCUMENT_INTEGRITY_CHECK", "reviewer",
                       current_reviewer()["username"], f"{doc_id}: {result}",
                       ref_type="document", ref_id=doc_id)
    flash(f"Stored dossier {doc_id}: {result}", "success" if result == "MATCH" else "error")
    return redirect(url_for("reviewer_case", case_id=doc["case_id"]) + "#documents")


@app.route("/reviewer/evidence/<evidence_id>/file")
@reviewer_required
def reviewer_evidence_file(evidence_id: str) -> Any:
    ev = store.get_evidence(evidence_id)
    if not ev or ev["status"] != "active":
        abort(404, description="Evidence not found.")
    path = store.resolve(ev["stored_path"])
    if not path or not os.path.exists(path):
        abort(410, description="The evidence file is missing from storage.")
    inline = ev["mime_type"] in ("image/jpeg", "image/png", "image/webp")
    return send_file(path, mimetype=ev["mime_type"] or "application/octet-stream",
                     as_attachment=not inline,
                     download_name=f"{evidence_id}_{ev['original_filename'] or 'file'}")


@app.route("/reviewer/case/<case_id>/status", methods=["POST"])
@reviewer_required
def reviewer_status(case_id: str) -> Any:
    _case_or_404(case_id)
    new_status = request.form.get("new_status", "")
    note = (request.form.get("note") or "").strip()[:1000]
    if new_status in ("INFO_REQUESTED", "REFERRED_FOR_LEGAL_AID", "CLOSED") and len(note) < 5:
        flash("Please write a reason (the claimant will see it).", "error")
        return redirect(url_for("reviewer_case", case_id=case_id) + "#decision")
    try:
        store.transition_case(case_id, new_status, "reviewer", current_reviewer()["username"], note)
        flash(f"Status changed to: {LABELS['status'].get(new_status, new_status)}", "success")
    except TransitionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("reviewer_case", case_id=case_id) + "#decision")


@app.route("/reviewer/case/<case_id>/tenancy-review", methods=["POST"])
@reviewer_required
def reviewer_tenancy(case_id: str) -> Any:
    case = _case_or_404(case_id)
    state = request.form.get("tenancy_review_status")
    if state not in TENANCY_REVIEW_STATES:
        abort(400, description="Invalid tenancy review state.")
    note = (request.form.get("note") or "").strip()[:500]
    store.update_case_fields(case_id, {"tenancy_review_status": state})
    store.append_audit(case_id, "TENANCY_REVIEW", "reviewer", current_reviewer()["username"],
                       f"{case['tenancy_review_status']} -> {state}. {note}".strip())
    flash("Tenancy review status updated.", "success")
    return redirect(url_for("reviewer_case", case_id=case_id) + "#tenancy")


ERASABLE_FIELDS = ("claimant_name", "guardian_name", "phone", "assisted_by", "landowner_name",
                   "tenancy_documents", "damage_description", "jl_number", "khatian_no",
                   "plot_dag_no", "latitude", "longitude", "location_accuracy_m",
                   "intimation_reference", "tracking_token_hash")


@app.route("/reviewer/case/<case_id>/erase", methods=["POST"])
@admin_required
def reviewer_erase(case_id: str) -> Any:
    case = _case_or_404(case_id)
    if request.form.get("confirm_case_id", "").strip() != case_id:
        flash("Type the case ID exactly to confirm erasure.", "error")
        return redirect(url_for("reviewer_case", case_id=case_id) + "#erasure")
    actor = current_reviewer()["username"]
    removed = 0
    for ev in store.list_evidence(case_id):
        path = store.resolve(ev["stored_path"])
        if path and os.path.exists(path):
            os.remove(path)
            removed += 1
    for doc in store.list_documents(case_id):
        path = store.resolve(doc["file_path"])
        if path and os.path.exists(path):
            os.remove(path)
            removed += 1
    with store.connect() as conn:
        conn.execute("UPDATE evidence SET status='erased', stored_path=NULL, original_filename=NULL, "
                     "embedded_gps_lat=NULL, embedded_gps_lon=NULL, metadata_json=NULL "
                     "WHERE case_id=?", (case_id,))
        conn.execute("UPDATE documents SET status='erased' WHERE case_id=?", (case_id,))
    ts = now_utc()
    store.update_case_fields(case_id, {**{k: None for k in ERASABLE_FIELDS},
                                       "status": "ERASED", "erased_at_utc": ts})
    store.append_audit(case_id, "PERSONAL_DATA_ERASED", "reviewer", actor,
                       f"{removed} file(s) deleted; personal fields cleared. Hashes and audit "
                       f"events retained.", prev_status=case["status"], new_status="ERASED")
    flash("Personal data erased. Non-personal hashes and the audit trail are retained.", "success")
    return redirect(url_for("reviewer_case", case_id=case_id))


@app.route("/reviewer/audit")
@reviewer_required
def reviewer_audit() -> str:
    return render_template("reviewer_audit.html", events=store.list_audit(),
                           chain=store.verify_audit_chain(), legacy=store.list_legacy_audit())


@app.route("/reviewer/earth-engine/recheck", methods=["POST"])
@reviewer_required
def reviewer_ee_recheck() -> Any:
    ee_state.refresh()
    flash(ee_state.message, "success" if ee_state.ready else "error")
    return redirect(request.referrer if (request.referrer or "").startswith(request.host_url)
                    else url_for("reviewer_dashboard"))


# --------------------------------------------------------------------------- synthetic demo
def _synthetic_analysis_record(case_id: str) -> Dict[str, Any]:
    """Clearly fictional satellite record for demonstration cases only."""
    seed = hashlib.sha256(case_id.encode()).digest()
    note = "SYNTHETIC — fictional values generated for demonstration. No satellite was queried."
    return {
        "status": "synthetic",
        "provenance": "synthetic_demo",
        "analysis_version": SATELLITE_ANALYSIS_VERSION + "+synthetic",
        "dataset": "None (synthetic demonstration)",
        "message": note,
        "sentinel1": {
            "status": "synthetic", "message": note, "dataset": "None", "synthetic_note": note,
            "post_mean_vv_db": round(-19.0 - seed[0] / 128, 2),
            "baseline_mean_vv_db": round(-12.0 - seed[1] / 128, 2),
            "change_db": round((-19.0 - seed[0] / 128) - (-12.0 - seed[1] / 128), 2),
            "sensitivity": [{"threshold_db": t, "new_low_backscatter_pct": round(30 + seed[i] / 6, 1),
                             "uncertain_pct": round(3 + seed[i + 3] / 40, 1)}
                            for i, t in enumerate((-17.0, -18.0, -19.0))],
        },
        "sentinel2": {"status": "synthetic", "message": note, "dataset": "None",
                      "synthetic_note": note},
        "parameters": ANALYSIS_DEFAULTS,
        "limitations": ANALYSIS_LIMITATIONS,
    }


def create_synthetic_case(actor: str) -> str:
    case_id = store.new_case_id("synthetic_demo")
    ts = now_utc()
    incident = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=20)).astimezone(
        datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    store.insert_case({
        "case_id": case_id, "record_type": "synthetic_demo", "status": "SUBMITTED",
        "created_at_utc": ts, "updated_at_utc": ts,
        "claimant_name": "Fictional Demo Claimant", "guardian_name": "Fictional Parent",
        "assisted_by": "Demo Field Operator (fictional)", "tenancy_category": "unrecorded_sharecropper",
        "landowner_name": "Fictional Landowner", "village": "Demo Village (fictional)",
        "district": "Fictional District", "plot_dag_no": "DEMO-000", "crop": "Paddy (Aman)",
        "season": "Kharif", "area_acres": 1.0, "incident_date": incident.date().isoformat(),
        "incident_time": incident.strftime("%H:%M"),
        "incident_start_utc": incident_start_utc(incident.date().isoformat(), incident.strftime("%H:%M")),
        "damage_type": "submergence", "damage_description": "Fictional description for demonstration.",
        "reported_affected_pct": 60.0, "insurance_scheme": "PMFBY", "intimation_status": "not_done",
        "location_source": "synthetic", "consent_given": 0, "consent_version": "not applicable (synthetic)",
    })
    store.append_audit(case_id, "SYNTHETIC_CASE_CREATED", "reviewer", actor,
                       "Synthetic demonstration case — not real evidence", new_status="SUBMITTED")
    case_dir = os.path.join(UPLOAD_DIR, case_id)
    os.makedirs(case_dir, exist_ok=True)
    for title, lines in (("Placeholder field photograph", ("No real field was photographed.",)),
                         ("Placeholder land record", ("No real document exists.",))):
        evidence_id = "EV-" + uuid.uuid4().hex[:12].upper()
        path = os.path.join(case_dir, evidence_id + ".png")
        render_synthetic_placeholder(path, title, lines + (f"Case {case_id}",))
        digest = sha256_file(path)
        store.insert_evidence({
            "evidence_id": evidence_id, "case_id": case_id, "kind": "synthetic_placeholder",
            "provenance": "synthetic_demo", "is_synthetic": 1,
            "original_filename": f"synthetic_{title.lower().replace(' ', '_')}.png",
            "stored_path": store.relpath(path), "mime_type": "image/png",
            "size_bytes": os.path.getsize(path), "sha256": digest,
            "description": "SYNTHETIC placeholder",
        })
        store.append_audit(case_id, "EVIDENCE_RECEIVED", "system", "synthetic-demo-generator",
                           f"{evidence_id} synthetic placeholder sha256={digest}",
                           ref_type="evidence", ref_id=evidence_id)
    return case_id


@app.route("/reviewer/demo", methods=["POST"])
@reviewer_required
def reviewer_demo() -> Any:
    case_id = create_synthetic_case(current_reviewer()["username"])
    flash("Synthetic demonstration case created. It is labelled as not real evidence everywhere.", "info")
    return redirect(url_for("reviewer_case", case_id=case_id))


# --------------------------------------------------------------------------- CLI
@app.cli.command("create-reviewer")
@click.argument("username")
@click.option("--role", type=click.Choice(["reviewer", "admin"]), default="reviewer")
@click.password_option()
def cli_create_reviewer(username: str, role: str, password: str) -> None:
    """Create a reviewer account (password is hashed; never stored in plaintext)."""
    if len(password) < 10:
        raise click.ClickException("Use a password of at least 10 characters.")
    if store.get_reviewer(username):
        raise click.ClickException("That username already exists.")
    store.create_reviewer(username, generate_password_hash(password), role)
    store.append_audit(None, "REVIEWER_CREATED", "system", "cli", f"{username} ({role})")
    click.echo(f"Created {role} '{username}'.")


@app.cli.command("seed-demo")
def cli_seed_demo() -> None:
    """Create one SYNTHETIC demonstration case."""
    click.echo(create_synthetic_case("cli"))


@app.cli.command("verify-audit")
def cli_verify_audit() -> None:
    """Check the audit hash chain."""
    click.echo(json.dumps(store.verify_audit_chain()))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host=os.environ.get("PRAMAANA_HOST", "127.0.0.1"), port=port, debug=False)
