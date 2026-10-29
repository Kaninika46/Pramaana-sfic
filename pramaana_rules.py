"""Deadline assessment and readiness checks derived from persisted case data.

Nothing here is a legal determination. Deadlines come from `legal_rules.json`
and are labelled provisional unless the legal reviewer has marked the rule's
applicability as verified.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from pramaana_store import parse_utc

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), "IST")
UNVERIFIED_DEADLINE_MESSAGE = (
    "Deadline requires verification against the applicable scheme or policy."
)


def incident_start_utc(incident_date: Optional[str], incident_time: Optional[str]) -> Optional[str]:
    """Convert a claimant-reported local (IST) date/time to a UTC timestamp string.

    When only a date is given, 00:00 IST is used — the earliest possible start,
    which gives the most cautious deadline.
    """
    if not incident_date:
        return None
    try:
        day = datetime.date.fromisoformat(incident_date)
        tm = datetime.time.fromisoformat(incident_time) if incident_time else datetime.time(0, 0)
    except ValueError:
        return None
    local = datetime.datetime.combine(day, tm, tzinfo=IST)
    return local.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def assess_deadline(
    case: Dict[str, Any], rules: Dict[str, Any], now: Optional[datetime.datetime] = None
) -> Dict[str, Any]:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    table = rules.get("deadline_rules", {})
    scheme = case.get("insurance_scheme") or "UNKNOWN"
    rule = table.get(scheme) or table.get("UNKNOWN") or {}
    out: Dict[str, Any] = {
        "scheme": scheme,
        "scheme_label": rule.get("label", scheme),
        "source": rule.get("source"),
        "applicability_note": rule.get("applicability_note", ""),
        "verified": bool(rule.get("applicability_verified")),
        "duration_hours": rule.get("duration_hours"),
        "incident_start_utc": case.get("incident_start_utc"),
        "incident_time_assumed": bool(case.get("incident_date")) and not case.get("incident_time"),
        "case_recorded_utc": case.get("created_at_utc"),
        "deadline_utc": None,
        "deadline_epoch_ms": None,
        "remaining_seconds": None,
        "state": "no_rule",
        "is_simulated": case.get("record_type") == "synthetic_demo",
    }
    if not out["duration_hours"]:
        out["message"] = (
            f"No intimation deadline is configured for '{out['scheme_label']}'. "
            + UNVERIFIED_DEADLINE_MESSAGE
        )
        return out
    start = parse_utc(out["incident_start_utc"])
    if not start:
        out["state"] = "no_incident_time"
        out["message"] = "The incident date is missing, so no deadline can be calculated."
        return out
    deadline = start + datetime.timedelta(hours=float(out["duration_hours"]))
    out["deadline_utc"] = deadline.strftime("%Y-%m-%dT%H:%M:%SZ")
    out["deadline_ist"] = deadline.astimezone(IST).strftime("%d %b %Y, %H:%M IST")
    out["deadline_epoch_ms"] = int(deadline.timestamp() * 1000)
    out["remaining_seconds"] = int((deadline - now).total_seconds())
    out["state"] = "open" if out["remaining_seconds"] > 0 else "passed"
    recorded = parse_utc(case.get("created_at_utc"))
    out["recorded_before_deadline"] = bool(recorded and recorded <= deadline)
    prefix = "" if out["verified"] else "PROVISIONAL — " + UNVERIFIED_DEADLINE_MESSAGE + " "
    if out["state"] == "open":
        out["message"] = (
            f"{prefix}If the {out['duration_hours']}-hour rule applies, intimation to the insurer "
            f"would be due by {out['deadline_ist']}. Pramaana does not file the intimation."
        )
    else:
        out["message"] = (
            f"{prefix}If the {out['duration_hours']}-hour rule applies, the window ended at "
            f"{out['deadline_ist']}. A delay explanation may be needed."
        )
    return out


# Information a reviewer needs before treating a dossier as complete.
REQUIRED_FOR_READINESS = (
    ("claimant_name", "Claimant name"),
    ("village", "Village / mouza"),
    ("crop", "Crop"),
    ("incident_date", "Incident date"),
    ("damage_description", "Damage description"),
)


def missing_items(case: Dict[str, Any], evidence: List[Dict[str, Any]],
                  analyses: List[Dict[str, Any]]) -> List[str]:
    gaps = [f"{label} not provided" for key, label in REQUIRED_FOR_READINESS if not case.get(key)]
    if case.get("latitude") is None:
        gaps.append("Field coordinates not recorded (needed for satellite analysis)")
    if not case.get("plot_dag_no") and not case.get("khatian_no"):
        gaps.append("Land record reference (dag / khatian number) not provided")
    active = [e for e in evidence if e["status"] == "active" and e["provenance"] == "farmer_capture"]
    if not any(e["kind"] == "photo" for e in active):
        gaps.append("No field photograph uploaded")
    if case.get("tenancy_category") in ("recorded_bargadar", "unrecorded_sharecropper", "lessee") \
            and not any(e["kind"] == "document" for e in active):
        gaps.append("No tenancy / cultivation supporting document uploaded")
    if not any(e["last_verification_result"] for e in evidence if e["status"] == "active"):
        gaps.append("Evidence integrity has not been checked yet")
    if not any(a["status"] in ("completed", "partial") for a in analyses):
        gaps.append("No completed satellite analysis")
    if case.get("insurance_scheme") in (None, "", "UNKNOWN"):
        gaps.append("Insurance / relief scheme not identified")
    return gaps
