"""Display labels and farmer-facing bilingual strings.

All user-visible enum labels live here so the web UI and the PDF stay in step.
Bengali strings are short field labels, most carried over from the original
UI. They still need review by a native speaker before field use. Legal and
consent text is deliberately English-only until a reviewed Bengali version
exists — the field operator should explain it orally.
"""

from __future__ import annotations

from typing import Dict

LABELS: Dict[str, Dict[str, str]] = {
    "record_type": {
        "real": "Real claim record",
        "field_test": "Field usability test",
        "synthetic_demo": "SYNTHETIC DEMONSTRATION — NOT REAL EVIDENCE",
    },
    "status": {
        "SUBMITTED": "Submitted — waiting for review",
        "UNDER_REVIEW": "Under review",
        "INFO_REQUESTED": "More information needed",
        "READY_FOR_SUBMISSION": "Dossier ready — claimant to submit via official channel",
        "REFERRED_FOR_LEGAL_AID": "Referred for legal-aid advice",
        "CLOSED": "Closed",
        "ERASED": "Personal data erased",
    },
    "tenancy": {
        "owner": "Owner-cultivator (raiyat)",
        "recorded_bargadar": "Recorded bargadar (claimed)",
        "unrecorded_sharecropper": "Sharecropper, not recorded (claimed)",
        "lessee": "Lessee / other tenancy (claimed)",
        "unsure": "Not sure",
    },
    "tenancy_review": {
        "claimant_provided": "Claimant-provided only",
        "document_supported": "Supporting document seen by reviewer",
        "awaiting_legal_review": "Awaiting legal review",
    },
    "location_source": {
        "device_gps": "Phone GPS (as reported by the device)",
        "manual": "Typed in manually",
        "none": "Not provided",
        "synthetic": "Synthetic (fictional — no real location)",
    },
    "damage_type": {
        "submergence": "Crop submerged by flood water",
        "waterlogging": "Prolonged waterlogging",
        "silt_sand": "Sand / silt deposited on field",
        "other": "Other",
    },
    "intimation_status": {
        "done": "Yes, already informed insurer / authority",
        "not_done": "No, not yet",
        "unknown": "Don't know",
    },
    "scheme": {
        "PMFBY": "PMFBY (Pradhan Mantri Fasal Bima Yojana)",
        "BSB": "Bangla Shasya Bima (West Bengal)",
        "OTHER": "Other scheme",
        "NOT_INSURED": "Not insured",
        "UNKNOWN": "Don't know",
    },
    "evidence_kind": {
        "photo": "Field photograph",
        "document": "Supporting document",
        "audio": "Voice note",
        "satellite_rendering": "Satellite rendering",
        "synthetic_placeholder": "Synthetic placeholder image",
    },
    "provenance": {
        "farmer_capture": "Submitted by claimant / field operator",
        "live_sentinel": "Google Earth Engine (Copernicus Sentinel)",
        "synthetic_demo": "SYNTHETIC — fictional",
        "not_queried": "None — no satellite data retrieved",
    },
    "analysis_status": {
        "completed": "Completed",
        "partial": "Partly completed",
        "no_data": "No usable satellite data",
        "unavailable": "Unavailable",
        "invalid_input": "Cannot run — input problem",
        "error": "Failed",
        "synthetic": "SYNTHETIC — fictional values",
    },
}

# Plain-language status for the claimant, with the next step.
FARMER_STATUS: Dict[str, Dict[str, str]] = {
    "SUBMITTED": {
        "en": "We have received your report. A reviewer will look at it.",
        "bn": "আপনার দাবিটি পর্যালোচনার অপেক্ষায় রয়েছে।",
        "next": "You do not need to do anything now. Keep your tracking code safe. "
                "If you are insured, you may still need to inform your insurer directly.",
    },
    "UNDER_REVIEW": {
        "en": "A reviewer is checking your report and evidence.",
        "bn": "",
        "next": "Wait for the review. Check this page again later.",
    },
    "INFO_REQUESTED": {
        "en": "More information is needed.",
        "bn": "আপনার দাবিতে আরও তথ্যের প্রয়োজন।",
        "next": "Read the reviewer's note below and add the requested photos or documents.",
    },
    "READY_FOR_SUBMISSION": {
        "en": "Your evidence file (dossier) has been prepared.",
        "bn": "",
        "next": "This is not a claim approval. You or your helper must submit the claim "
                "through the official channel (insurer, app, helpline or office).",
    },
    "REFERRED_FOR_LEGAL_AID": {
        "en": "Your case has been referred for legal-aid advice.",
        "bn": "",
        "next": "Someone may contact you using the phone number you gave.",
    },
    "CLOSED": {
        "en": "This case is closed.",
        "bn": "",
        "next": "Read the reviewer's note below for the reason.",
    },
    "ERASED": {
        "en": "Your personal data has been erased.",
        "bn": "",
        "next": "Only non-personal records of the case remain.",
    },
}

# Bilingual field labels for the farmer form: (English, Bengali).
FIELD: Dict[str, tuple] = {
    "claimant_name": ("Claimant's name", "চাষির নাম"),
    "guardian_name": ("Father / spouse name", "পিতা বা স্বামীর নাম"),
    "phone": ("Phone number", "ফোন নম্বর"),
    "assisted_by": ("Helper / field operator name", "সহায়তাকারী"),
    "tenancy_category": ("How do you cultivate this land?", "ভাগচাষি / রাইয়ত শ্রেণী"),
    "landowner_name": ("Landowner's name", "জমির মালিকের নাম"),
    "tenancy_documents": ("Records you have (barga record, receipt, agreement…)", ""),
    "village": ("Village / mouza", "মৌজা"),
    "gram_panchayat": ("Gram panchayat", "গ্রাম পঞ্চায়েত"),
    "block": ("Block", "ব্লক"),
    "district": ("District", "জেলা"),
    "jl_number": ("JL number", "জে এল নম্বর"),
    "khatian_no": ("Khatian number", "খতিয়ান নম্বর"),
    "plot_dag_no": ("Plot / dag number", "দাগ নম্বর"),
    "latitude": ("Latitude", "অক্ষাংশ"),
    "longitude": ("Longitude", "দ্রাঘিমাংশ"),
    "crop": ("Crop", "ফসল"),
    "season": ("Season", "মরশুম"),
    "area_acres": ("Area (acres)", "জমির পরিমাণ"),
    "incident_date": ("Date the flooding started", "বন্যা শুরুর তারিখ"),
    "incident_time": ("Time (if known)", "সময়"),
    "damage_type": ("What happened to the crop?", ""),
    "damage_description": ("Describe the damage", "ক্ষতির বিবরণ"),
    "reported_affected_pct": ("Roughly how much of the field is damaged? (%)", ""),
    "insurance_scheme": ("Is the crop insured? Which scheme?", "ফসল বিমা"),
    "intimation_status": ("Have you already informed the insurer?", ""),
    "intimation_reference": ("Complaint / docket number (if any)", ""),
    "photos": ("Field photographs", "জমির ছবি"),
    "documents": ("Documents (land record, receipt, insurance paper)", "নথি"),
    "voice": ("Voice note (optional)", "ভয়েস নোট"),
}

CONSENT_VERSION = "consent-v1-en-2026-10-29"
CONSENT_TEXT = [
    "Pramaana is a student-built software project. It is not a government, insurer, court or "
    "legal-aid service, and it does not file claims for you.",
    "We collect the details on this form and the files you upload to prepare an organised "
    "evidence file (dossier) about suspected flood damage to your crop.",
    "Your information is stored on the project's server and can be seen only by signed-in "
    "project reviewers. It is not published. It is not shared with anyone else unless you "
    "ask us to.",
    "Giving your phone number is optional. Giving Aadhaar or bank details is not needed — "
    "please do not include them.",
    "You can ask for your personal data to be deleted at any time from the tracking page. A "
    "short, non-personal record of the case and the deletion will remain in the audit log.",
    "If you have a concern, tell the field operator who helped you or the project team.",
]
