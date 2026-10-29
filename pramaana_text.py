"""Display labels and farmer-facing bilingual strings.

All user-visible enum labels live here so the web UI and the PDF stay in step.
Bengali strings are short field labels, most carried over from the original
UI. Bengali consent text exists (CONSENT_TEXT_BN) but is marked as a draft
until reviewed; all other farmer-page text lives in pramaana_i18n.
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

# Plain-language status for the claimant, with the next step, in English and Bengali.
FARMER_STATUS: Dict[str, Dict[str, str]] = {
    "SUBMITTED": {
        "en": "We have received your report. A reviewer will look at it.",
        "bn": "আমরা আপনার রিপোর্ট পেয়েছি। একজন পর্যালোচক এটি দেখবেন।",
        "next": "You do not need to do anything now. Keep your tracking code safe. "
                "If you are insured, you may still need to inform your insurer directly.",
        "next_bn": "এখন আপনাকে কিছু করতে হবে না। ট্র্যাকিং কোডটি যত্ন করে রাখুন। "
                   "বিমা থাকলে বিমা সংস্থাকে হয়তো আপনাকে নিজেই জানাতে হবে।",
    },
    "UNDER_REVIEW": {
        "en": "A reviewer is checking your report and evidence.",
        "bn": "একজন পর্যালোচক আপনার রিপোর্ট ও প্রমাণ দেখছেন।",
        "next": "Wait for the review. Check this page again later.",
        "next_bn": "পর্যালোচনা শেষ হওয়া পর্যন্ত অপেক্ষা করুন। পরে আবার এই পাতাটি দেখুন।",
    },
    "INFO_REQUESTED": {
        "en": "More information is needed.",
        "bn": "আরও তথ্য দরকার।",
        "next": "Read the reviewer's note below and add the requested photos or documents.",
        "next_bn": "নিচে পর্যালোচকের মন্তব্য পড়ুন এবং যে ছবি বা কাগজ চাওয়া হয়েছে তা যোগ করুন।",
    },
    "READY_FOR_SUBMISSION": {
        "en": "Your evidence file (dossier) has been prepared.",
        "bn": "আপনার প্রমাণ-ফাইল (ডসিয়ার) তৈরি হয়েছে।",
        "next": "This is not a claim approval. You or your helper must submit the claim "
                "through the official channel (insurer, app, helpline or office).",
        "next_bn": "এটি দাবি মঞ্জুরি নয়। আপনাকে বা আপনার সাহায্যকারীকে সরকারি মাধ্যমে "
                   "(বিমা সংস্থা, অ্যাপ, হেল্পলাইন বা অফিস) দাবি জমা দিতে হবে।",
    },
    "REFERRED_FOR_LEGAL_AID": {
        "en": "Your case has been referred for legal-aid advice.",
        "bn": "আপনার কেসটি আইনি সহায়তার পরামর্শের জন্য পাঠানো হয়েছে।",
        "next": "Someone may contact you using the phone number you gave.",
        "next_bn": "আপনার দেওয়া ফোন নম্বরে কেউ যোগাযোগ করতে পারেন।",
    },
    "CLOSED": {
        "en": "This case is closed.",
        "bn": "এই কেসটি বন্ধ করা হয়েছে।",
        "next": "Read the reviewer's note below for the reason.",
        "next_bn": "কারণ জানতে নিচে পর্যালোচকের মন্তব্য পড়ুন।",
    },
    "ERASED": {
        "en": "Your personal data has been erased.",
        "bn": "আপনার ব্যক্তিগত তথ্য মুছে ফেলা হয়েছে।",
        "next": "Only non-personal records of the case remain.",
        "next_bn": "কেসের শুধু অ-ব্যক্তিগত রেকর্ড থেকে গেছে।",
    },
}

# Field labels for the farmer form: (English, Bengali). The page shows the one
# matching the visitor's language choice (see pramaana_i18n).
FIELD: Dict[str, tuple] = {
    "claimant_name": ("Claimant's name", "কৃষকের নাম"),
    "guardian_name": ("Father / spouse name", "বাবা বা স্বামী/স্ত্রীর নাম"),
    "phone": ("Phone number", "ফোন নম্বর"),
    "assisted_by": ("Helper / field operator name", "সাহায্যকারী / মাঠকর্মীর নাম"),
    "tenancy_category": ("How do you cultivate this land?", "এই জমি আপনি কীভাবে চাষ করেন?"),
    "landowner_name": ("Landowner's name", "জমির মালিকের নাম"),
    "tenancy_documents": ("Records you have (barga record, receipt, agreement…)",
                          "আপনার কাছে থাকা কাগজ (বর্গা রেকর্ড, রসিদ, চুক্তি…)"),
    "village": ("Village / mouza", "গ্রাম / মৌজা"),
    "gram_panchayat": ("Gram panchayat", "গ্রাম পঞ্চায়েত"),
    "block": ("Block", "ব্লক"),
    "district": ("District", "জেলা"),
    "jl_number": ("JL number", "জে এল নম্বর"),
    "khatian_no": ("Khatian number", "খতিয়ান নম্বর"),
    "plot_dag_no": ("Plot / dag number", "প্লট / দাগ নম্বর"),
    "latitude": ("Latitude", "অক্ষাংশ (Latitude)"),
    "longitude": ("Longitude", "দ্রাঘিমাংশ (Longitude)"),
    "crop": ("Crop", "ফসল"),
    "season": ("Season", "মরশুম"),
    "area_acres": ("Area (acres)", "জমির পরিমাণ (একর)"),
    "incident_date": ("Date the flooding started", "বন্যা শুরুর তারিখ"),
    "incident_time": ("Time (if known)", "সময় (জানা থাকলে)"),
    "damage_type": ("What happened to the crop?", "ফসলের কী হয়েছে?"),
    "damage_description": ("Describe the damage", "ক্ষতির বিবরণ লিখুন"),
    "reported_affected_pct": ("Roughly how much of the field is damaged? (%)",
                              "জমির আনুমানিক কত অংশ ক্ষতিগ্রস্ত? (%)"),
    "insurance_scheme": ("Is the crop insured? Which scheme?", "ফসলের বিমা আছে কি? কোন প্রকল্পে?"),
    "intimation_status": ("Have you already informed the insurer?", "বিমা সংস্থাকে কি ইতিমধ্যে জানিয়েছেন?"),
    "intimation_reference": ("Complaint / docket number (if any)", "অভিযোগ / ডকেট নম্বর (থাকলে)"),
    "photos": ("Field photographs", "জমির ছবি"),
    "documents": ("Documents (land record, receipt, insurance paper)",
                  "কাগজপত্র (জমির রেকর্ড, রসিদ, বিমার কাগজ)"),
    "voice": ("Voice note (optional)", "ভয়েস নোট (ঐচ্ছিক)"),
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

# Bengali consent text. It is a translation of CONSENT_TEXT; until a team member
# and the legal lead have reviewed it, it is shown as a draft with the English
# original beside it, and cases record the draft version string.
CONSENT_BN_REVIEWED = False
CONSENT_VERSION_BN = "consent-v1-bn-2026-10-30" + ("" if CONSENT_BN_REVIEWED else "-draft")
CONSENT_TEXT_BN = [
    "প্রমাণ ছাত্রছাত্রীদের তৈরি একটি সফটওয়্যার প্রকল্প। এটি কোনো সরকারি দপ্তর, বিমা সংস্থা, আদালত "
    "বা আইনি সহায়তা পরিষেবা নয়, এবং এটি আপনার হয়ে কোনো দাবি জমা দেয় না।",
    "বন্যায় আপনার ফসলের সম্ভাব্য ক্ষতি নিয়ে একটি গোছানো প্রমাণ-ফাইল (ডসিয়ার) তৈরি করতে আমরা এই "
    "ফর্মের তথ্য আর আপনার আপলোড করা ফাইলগুলি নিই।",
    "আপনার তথ্য প্রকল্পের সার্ভারে রাখা হয় এবং শুধু লগ-ইন করা প্রকল্প-পর্যালোচকরাই তা দেখতে পারেন। "
    "এটি প্রকাশ করা হয় না। আপনি না বললে অন্য কাউকে দেওয়া হয় না।",
    "ফোন নম্বর দেওয়া ঐচ্ছিক। আধার বা ব্যাঙ্কের তথ্য লাগে না — দয়া করে সেগুলি দেবেন না।",
    "ট্র্যাকিং পাতা থেকে যেকোনো সময় আপনার ব্যক্তিগত তথ্য মুছে ফেলার অনুরোধ করতে পারেন। কেস ও তথ্য "
    "মোছার একটি ছোট, অ-ব্যক্তিগত রেকর্ড অডিট লগে থেকে যাবে।",
    "কোনো সমস্যা বা প্রশ্ন থাকলে যে মাঠকর্মী সাহায্য করেছেন তাঁকে, অথবা প্রকল্প দলকে জানান।",
]

# Consent text and version string per language shown.
CONSENT = {
    "en": (CONSENT_TEXT, CONSENT_VERSION),
    "bn": (CONSENT_TEXT_BN, CONSENT_VERSION_BN),
}
