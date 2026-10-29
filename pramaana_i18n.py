"""English / Bengali text for the farmer-facing pages.

Every string a farmer or field operator sees on home, report, report-done,
track, track-case, verify and error pages lives here, so the whole Bengali
text can be reviewed in one place. Reviewer pages, the About page and the
dossier PDF stay English.

Rules for editing:
- Keep the English wording identical to the app's original text unless the
  change is deliberate (tests check some of it).
- Placeholders such as {name} must appear in both languages.
- Keys ending in "_html" contain fixed markup and are rendered unescaped;
  never put user input into them.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from markupsafe import Markup

SUPPORTED = ("en", "bn")
DEFAULT_LANG = "en"
LANG_COOKIE = "pramaana_lang"
LANG_NAMES = {"en": "English", "bn": "বাংলা"}

# Pages that follow the visitor's language choice. Everything else is English.
FARMER_ENDPOINTS = frozenset({
    "index", "report", "report_done", "track", "track_case", "track_add_evidence",
    "track_erasure_request", "track_download", "verify_file", "set_language",
})

STRINGS: Dict[str, Dict[str, str]] = {
    # ------------------------------------------------------------ layout
    "lang.label": {"en": "Language", "bn": "ভাষা"},
    "skip": {"en": "Skip to content", "bn": "মূল অংশে যান"},
    "brand.sub": {"en": "AI-assisted agricultural flood evidence & claim-preparation system",
                  "bn": "বন্যায় ফসলের ক্ষতির প্রমাণ ও দাবি প্রস্তুতির এআই-সহায়ক ব্যবস্থা"},
    "nav.main": {"en": "Main", "bn": "প্রধান মেনু"},
    "nav.report": {"en": "Report a loss", "bn": "ক্ষতির খবর দিন"},
    "nav.track": {"en": "Track a case", "bn": "দাবির অবস্থা দেখুন"},
    "nav.verify": {"en": "Verify a file", "bn": "ফাইল যাচাই করুন"},
    "nav.about": {"en": "About & limits", "bn": "পরিচিতি ও সীমাবদ্ধতা (ইংরেজি)"},
    "nav.reviewer": {"en": "Reviewer", "bn": "পর্যালোচক"},
    "nav.reviewer_signin": {"en": "Reviewer sign-in", "bn": "পর্যালোচকের লগ-ইন"},
    "nav.sign_out": {"en": "Sign out ({user})", "bn": "লগ-আউট ({user})"},
    "footer": {"en": "Pramaana v{version} — a student public-interest technology prototype. Not a "
                     "government, insurer, court or legal-aid service. It does not file claims or "
                     "make decisions.",
               "bn": "প্রমাণ v{version} — জনস্বার্থে ছাত্রছাত্রীদের তৈরি একটি প্রযুক্তি-নমুনা (প্রোটোটাইপ)। "
                     "এটি কোনো সরকারি দপ্তর, বিমা সংস্থা, আদালত বা আইনি সহায়তা পরিষেবা নয়। এটি কোনো "
                     "দাবি জমা দেয় না বা কোনো সিদ্ধান্ত নেয় না।"},
    "footer.limits": {"en": "Limitations", "bn": "সীমাবদ্ধতা (ইংরেজি)"},
    "required_mark": {"en": "required", "bn": "আবশ্যক"},
    "optional": {"en": "optional", "bn": "ঐচ্ছিক"},
    "back": {"en": "← Back", "bn": "← পিছনে"},

    # ------------------------------------------------------------ home
    "home.title": {"en": "Home", "bn": "মূল পাতা"},
    "home.h1": {"en": "Organise evidence of flood damage to your crop",
                "bn": "বন্যায় ফসলের ক্ষতির প্রমাণ গুছিয়ে রাখুন"},
    "home.intro": {"en": "Pramaana helps farmers and field helpers in the Ghatal area record suspected "
                         "flood damage, keep photographs and documents safe with a digital fingerprint, "
                         "and prepare a clear evidence file (dossier) for a human reviewer.",
                   "bn": "প্রমাণ ঘাটাল এলাকার কৃষক ও তাঁদের সাহায্যকারীদের জন্য। এখানে বন্যায় ফসলের "
                         "সম্ভাব্য ক্ষতির কথা লিখে রাখা যায়, ছবি ও কাগজপত্র একটি ডিজিটাল ফিঙ্গারপ্রিন্ট দিয়ে "
                         "নিরাপদে রাখা যায়, আর একজন পর্যালোচকের জন্য একটি গোছানো প্রমাণ-ফাইল (ডসিয়ার) "
                         "তৈরি করা যায়।"},
    "home.important_html": {"en": "<strong>Important:</strong> Pramaana does <strong>not</strong> file an "
                                  "insurance claim or inform your insurer. If your crop is insured, inform the "
                                  "insurer or official channel yourself as soon as possible.",
                            "bn": "<strong>জরুরি:</strong> প্রমাণ কোনো বিমা দাবি জমা দেয় <strong>না</strong> এবং "
                                  "আপনার বিমা সংস্থাকে কিছু জানায় না। ফসলের বিমা থাকলে যত তাড়াতাড়ি সম্ভব নিজে "
                                  "বিমা সংস্থা বা সরকারি মাধ্যমে জানান।"},
    "home.card_report_h": {"en": "Report a loss →", "bn": "ক্ষতির খবর দিন →"},
    "home.card_report_p": {"en": "Start a new case: your details, the field, the crop, what happened, and "
                                 "photos. About 10 minutes.",
                           "bn": "নতুন দাবি শুরু করুন: আপনার পরিচয়, জমি, ফসল, কী হয়েছে, আর ছবি। প্রায় ১০ "
                                 "মিনিট লাগবে।"},
    "home.card_track_h": {"en": "Track a case →", "bn": "দাবির অবস্থা দেখুন →"},
    "home.card_track_p": {"en": "Use your case ID and tracking code to see progress, add files, or ask for "
                                "your data to be deleted.",
                          "bn": "কেস আইডি আর ট্র্যাকিং কোড দিয়ে অগ্রগতি দেখুন, নতুন ফাইল যোগ করুন, বা আপনার "
                                "তথ্য মুছে ফেলার অনুরোধ করুন।"},
    "home.card_verify_h": {"en": "Verify a file →", "bn": "ফাইল যাচাই করুন →"},
    "home.card_verify_p": {"en": "Check whether a dossier or photo is byte-for-byte identical to the copy "
                                 "Pramaana recorded.",
                           "bn": "দেখুন কোনো ডসিয়ার বা ছবি প্রমাণে রাখা কপির সঙ্গে হুবহু (প্রতিটি বাইট) এক কি না।"},
    "home.flow_h": {"en": "What happens to a report", "bn": "রিপোর্ট জমা পড়ার পরে কী হয়"},
    "home.flow1": {"en": "You report the suspected loss and give consent.",
                   "bn": "আপনি সম্ভাব্য ক্ষতির কথা জানান এবং সম্মতি দেন।"},
    "home.flow2": {"en": "Photos and documents are stored unchanged, and a SHA-256 fingerprint is "
                         "recorded for each.",
                   "bn": "ছবি ও কাগজপত্র কোনো বদল ছাড়াই রাখা হয়, আর প্রতিটির একটি SHA-256 ফিঙ্গারপ্রিন্ট "
                         "লিখে রাখা হয়।"},
    "home.flow3": {"en": "The field location and how it was recorded (phone GPS or typed) are saved.",
                   "bn": "জমির অবস্থান, আর সেটি কীভাবে নেওয়া হয়েছে (ফোনের জিপিএস নাকি হাতে লেখা), দুটোই "
                         "রাখা হয়।"},
    "home.flow4": {"en": "A reviewer runs satellite analysis — only if Earth Engine is genuinely connected.",
                   "bn": "একজন পর্যালোচক উপগ্রহের তথ্য বিশ্লেষণ করেন — শুধুমাত্র যদি আর্থ ইঞ্জিন সত্যিই যুক্ত "
                         "থাকে।"},
    "home.flow5": {"en": "The reviewer re-checks every file's fingerprint and prepares a labelled dossier.",
                   "bn": "পর্যালোচক প্রতিটি ফাইলের ফিঙ্গারপ্রিন্ট আবার মিলিয়ে দেখেন এবং চিহ্নিত একটি ডসিয়ার "
                         "তৈরি করেন।"},
    "home.flow6": {"en": "The reviewer records a decision. You see the status and any notes on the "
                         "tracking page.",
                   "bn": "পর্যালোচক সিদ্ধান্ত লিখে রাখেন। ট্র্যাকিং পাতায় আপনি অবস্থা ও মন্তব্য দেখতে পাবেন।"},
    "home.status_h": {"en": "System status", "bn": "ব্যবস্থার অবস্থা"},
    "home.storage": {"en": "Case storage", "bn": "কেস সংরক্ষণ"},
    "home.storage_ok": {"en": "✓ Persistent (SQLite)", "bn": "✓ স্থায়ীভাবে সংরক্ষিত (SQLite)"},
    "home.satellite": {"en": "Satellite analysis", "bn": "উপগ্রহ বিশ্লেষণ"},
    "home.ee_ok": {"en": "✓ Earth Engine connected", "bn": "✓ আর্থ ইঞ্জিন যুক্ত"},
    "home.ee_off": {"en": "! Unavailable", "bn": "! এখন পাওয়া যাচ্ছে না"},
    "home.integrations": {"en": "Integrations", "bn": "অন্য ব্যবস্থার সঙ্গে যোগ"},
    "home.integrations_html": {"en": "None. Pramaana is <strong>not connected</strong> to any insurer, DLSA, "
                                     "court or government portal.",
                               "bn": "নেই। প্রমাণ কোনো বিমা সংস্থা, জেলা আইনি পরিষেবা কর্তৃপক্ষ (DLSA), আদালত "
                                     "বা সরকারি পোর্টালের সঙ্গে <strong>যুক্ত নয়</strong>।"},
    "home.field_validation": {"en": "Field validation", "bn": "মাঠে পরীক্ষা"},
    "home.field_validation_html": {"en": "No field test has been recorded yet. See "
                                         "<a href=\"{url}\">field-testing plan</a>.",
                                   "bn": "এখনও মাঠে কোনো পরীক্ষা লেখা হয়নি। দেখুন "
                                         "<a href=\"{url}\">মাঠে পরীক্ষার পরিকল্পনা (ইংরেজি)</a>।"},

    # ------------------------------------------------------------ report form
    "report.title": {"en": "Report a loss", "bn": "ক্ষতির খবর দিন"},
    "report.h1": {"en": "Report suspected flood damage", "bn": "বন্যায় ফসলের সম্ভাব্য ক্ষতির খবর দিন"},
    "report.intro_html": {"en": "Fields marked <span class=\"req\">*</span> are required. Everything else is "
                                "optional — leave it empty if you are not sure. Please do not enter Aadhaar or "
                                "bank numbers.",
                          "bn": "<span class=\"req\">*</span> চিহ্ন দেওয়া ঘরগুলি পূরণ করা আবশ্যক। বাকি সব "
                                "ঐচ্ছিক — নিশ্চিত না হলে খালি রাখুন। দয়া করে আধার বা ব্যাঙ্কের নম্বর লিখবেন না।"},
    "report.fix": {"en": "Please fix the following before submitting:",
                   "bn": "জমা দেওয়ার আগে নিচের বিষয়গুলি ঠিক করুন:"},
    "report.files_not_kept": {"en": "For your safety, files are never kept from a rejected form — please "
                                    "choose your photos again.",
                              "bn": "আপনার সুরক্ষার জন্য বাতিল হওয়া ফর্মের কোনো ফাইল রাখা হয় না — দয়া করে "
                                    "ছবিগুলি আবার বেছে নিন।"},
    "report.progress": {"en": "Progress", "bn": "অগ্রগতি"},
    "report.step_you": {"en": "1. You", "bn": "১. আপনি"},
    "report.step_field": {"en": "2. Field", "bn": "২. জমি"},
    "report.step_crop": {"en": "3. Crop & damage", "bn": "৩. ফসল ও ক্ষতি"},
    "report.step_photos": {"en": "4. Photos", "bn": "৪. ছবি"},
    "report.step_check": {"en": "5. Check & consent", "bn": "৫. যাচাই ও সম্মতি"},
    "report.busy": {"en": "Submitting… please wait", "bn": "জমা হচ্ছে… অপেক্ষা করুন"},
    "report.s1": {"en": "Step 1 — About this report", "bn": "ধাপ ১ — এই রিপোর্ট সম্পর্কে"},
    "report.s1_intro": {"en": "Who is reporting the loss?", "bn": "কে ক্ষতির খবর দিচ্ছেন?"},
    "report.record_type": {"en": "What kind of record is this?", "bn": "এটি কী ধরনের রেকর্ড?"},
    "report.record_type_label": {"en": "Record type", "bn": "রেকর্ডের ধরন"},
    "report.real": {"en": "A real loss", "bn": "সত্যিকারের ক্ষতি"},
    "report.real_hint": {"en": "A farmer's actual report.", "bn": "একজন কৃষকের প্রকৃত রিপোর্ট।"},
    "report.test": {"en": "Field test of this app", "bn": "এই অ্যাপের মাঠ-পরীক্ষা"},
    "report.test_hint": {"en": "Trying the software with a volunteer. Not for submission.",
                         "bn": "একজন স্বেচ্ছাসেবকের সঙ্গে সফটওয়্যারটি পরীক্ষা করা হচ্ছে। জমা দেওয়ার জন্য নয়।"},
    "report.phone_hint": {"en": "So a reviewer can call back. Optional.",
                          "bn": "যাতে পর্যালোচক ফোন করতে পারেন। ঐচ্ছিক।"},
    "report.assisted_hint": {"en": "If someone is helping fill in this form.",
                             "bn": "কেউ যদি এই ফর্ম পূরণে সাহায্য করেন।"},
    "report.next_field": {"en": "Next: the field →", "bn": "পরের ধাপ: জমি →"},
    "report.s2": {"en": "Step 2 — The affected field", "bn": "ধাপ ২ — ক্ষতিগ্রস্ত জমি"},
    "report.s2_intro": {"en": "Where is the damaged field? Land-record numbers help, but are optional.",
                        "bn": "ক্ষতিগ্রস্ত জমিটি কোথায়? জমির রেকর্ডের নম্বর থাকলে সুবিধা হয়, তবে সেগুলি ঐচ্ছিক।"},
    "report.location_h": {"en": "Field location", "bn": "জমির অবস্থান"},
    "report.location_opt": {"en": "optional, but needed for satellite checks",
                            "bn": "ঐচ্ছিক, তবে উপগ্রহ যাচাইয়ের জন্য দরকার"},
    "report.location_help": {"en": "Stand in or beside the affected field, then press the button. The phone's "
                                   "GPS accuracy is saved too. You can also type the numbers.",
                             "bn": "ক্ষতিগ্রস্ত জমির মধ্যে বা পাশে দাঁড়িয়ে বোতামটি টিপুন। ফোনের জিপিএস কতটা "
                                   "নির্ভুল, সেটিও রাখা হয়। চাইলে সংখ্যাগুলি নিজেও লিখতে পারেন।"},
    "report.gps_button": {"en": "📍 Use this phone's location", "bn": "📍 এই ফোনের লোকেশন নিন"},
    "report.lat_placeholder": {"en": "e.g. 22.66", "bn": "যেমন 22.66"},
    "report.lon_placeholder": {"en": "e.g. 87.72", "bn": "যেমন 87.72"},
    "report.tenancy_h": {"en": "How do you cultivate this land?", "bn": "এই জমি আপনি কীভাবে চাষ করেন?"},
    "report.tenancy_hint": {"en": "This is recorded as what you tell us. Pramaana does not decide anyone's "
                                  "legal tenancy status.",
                            "bn": "আপনি যা বলবেন, সেটাই লেখা হবে। প্রমাণ কারও আইনি প্রজাস্বত্ব (রায়তি বা বর্গা) "
                                  "ঠিক করে না।"},
    "report.tenancy_docs_hint": {"en": "Describe any records you have. You can upload them in step 4.",
                                 "bn": "আপনার কাছে কী কী কাগজ আছে লিখুন। ধাপ ৪-এ সেগুলি আপলোড করতে পারবেন।"},
    "report.next_crop": {"en": "Next: crop & damage →", "bn": "পরের ধাপ: ফসল ও ক্ষতি →"},
    "report.s3": {"en": "Step 3 — Crop and damage", "bn": "ধাপ ৩ — ফসল ও ক্ষতি"},
    "report.s3_intro": {"en": "Tell us what was growing and what happened, in your own words.",
                        "bn": "জমিতে কী ফসল ছিল আর কী হয়েছে, নিজের ভাষায় লিখুন।"},
    "report.crop_placeholder": {"en": "e.g. Aman paddy", "bn": "যেমন আমন ধান"},
    "report.season_placeholder": {"en": "e.g. Kharif 2026", "bn": "যেমন খরিফ ২০২৬"},
    "report.time_hint": {"en": "Leave empty if you do not know.", "bn": "না জানলে খালি রাখুন।"},
    "report.damage_type_label": {"en": "Damage type", "bn": "ক্ষতির ধরন"},
    "report.description_label": {"en": "Damage description", "bn": "ক্ষতির বিবরণ"},
    "report.description_placeholder": {"en": "For example: water entered the field on the night of …, plants "
                                             "are lying flat, water is still knee-deep…",
                                       "bn": "যেমন: … তারিখ রাতে জমিতে জল ঢোকে, গাছ শুয়ে পড়েছে, এখনও হাঁটু-জল "
                                             "দাঁড়িয়ে আছে…"},
    "report.pct_hint": {"en": "Your own estimate. It is recorded as your estimate, not a measurement.",
                        "bn": "এটি আপনার নিজের আন্দাজ। মাপজোক নয়, আপনার আন্দাজ হিসেবেই লেখা থাকবে।"},
    "report.next_photos": {"en": "Next: photos →", "bn": "পরের ধাপ: ছবি →"},
    "report.s4": {"en": "Step 4 — Photos and documents", "bn": "ধাপ ৪ — ছবি ও কাগজপত্র"},
    "report.s4_intro": {"en": "Take clear photos of the damaged field, including a wide photo showing "
                              "landmarks. Files are stored exactly as uploaded. Up to 10 files, 10 MB each.",
                        "bn": "ক্ষতিগ্রস্ত জমির পরিষ্কার ছবি তুলুন, আশেপাশের চেনা জিনিস (গাছ, রাস্তা, বাড়ি) দেখা "
                              "যায় এমন একটি দূরের ছবিও তুলুন। ফাইলগুলি ঠিক যেমন আপলোড হয় তেমনই রাখা হয়। "
                              "সর্বোচ্চ ১০টি ফাইল, প্রতিটি ১০ MB পর্যন্ত।"},
    "report.doc_types": {"en": "PDF or photo", "bn": "PDF বা ছবি"},
    "report.photos_label": {"en": "Photos", "bn": "ছবি"},
    "report.documents_label": {"en": "Documents", "bn": "কাগজপত্র"},
    "report.voice_label": {"en": "Voice note", "bn": "ভয়েস নোট"},
    "report.fingerprint_hint": {"en": "Each file gets a SHA-256 fingerprint on this phone and again on the "
                                      "server. Matching fingerprints show the file arrived unchanged. They do not "
                                      "prove when or where a photo was taken.",
                                "bn": "প্রতিটি ফাইলের একটি SHA-256 ফিঙ্গারপ্রিন্ট এই ফোনে, আবার সার্ভারেও তৈরি হয়। "
                                      "দুটো মিললে বোঝা যায় ফাইলটি কোনো বদল ছাড়াই পৌঁছেছে। তবে ছবিটি কবে বা কোথায় "
                                      "তোলা, তা এতে প্রমাণ হয় না।"},
    "report.next_check": {"en": "Next: check & consent →", "bn": "পরের ধাপ: যাচাই ও সম্মতি →"},
    "report.s5": {"en": "Step 5 — Check and give consent", "bn": "ধাপ ৫ — যাচাই করুন ও সম্মতি দিন"},
    "report.answers": {"en": "Your answers", "bn": "আপনার উত্তর"},
    "report.change": {"en": "Change something", "bn": "কিছু বদলাতে চাই"},
    "report.consent_h": {"en": "Consent", "bn": "সম্মতি"},
    "report.consent_other_lang": {"en": "এই সম্মতিপত্র বাংলায় পড়তে পাতার উপরে ‘বাংলা’ বেছে নিন।",
                                  "bn": "Prefer English? Choose ‘English’ at the top of the page."},
    "report.consent_draft": {"en": "",
                             "bn": "এই বাংলা পাঠটি খসড়া অনুবাদ, এখনও যাচাই হয়নি। কোনো অমিল থাকলে ইংরেজি "
                                   "পাঠটিই গ্রাহ্য হবে।"},
    "report.consent_original": {"en": "", "bn": "ইংরেজি পাঠটি দেখুন"},
    "report.consent_agree": {"en": "I understand the above and agree that this information and these files may "
                                   "be stored and used to prepare my case.",
                             "bn": "আমি উপরের কথাগুলি বুঝেছি, এবং এই তথ্য ও ফাইলগুলি রাখা ও আমার দাবির কাগজ তৈরিতে "
                                   "ব্যবহার করায় সম্মতি দিচ্ছি।"},
    "report.clear_draft": {"en": "Clear draft", "bn": "খসড়া মুছুন"},
    "report.submit": {"en": "Submit report", "bn": "রিপোর্ট জমা দিন"},
    "report.already": {"en": "This report was already received. Showing the saved case.",
                       "bn": "এই রিপোর্টটি আগেই জমা পড়েছে। জমা পড়া কেসটি দেখানো হচ্ছে।"},

    # ------------------------------------------------------------ report done
    "done.title": {"en": "Report received", "bn": "রিপোর্ট জমা পড়েছে"},
    "done.saved": {"en": "✓ Your report has been saved.", "bn": "✓ আপনার রিপোর্ট জমা পড়েছে।"},
    "done.h1": {"en": "Keep these two codes safe", "bn": "এই দুটি কোড যত্ন করে রাখুন"},
    "done.intro": {"en": "You need both to check progress, add photos, or ask for your data to be deleted. "
                         "Write them down or take a screenshot.",
                   "bn": "অগ্রগতি দেখতে, ছবি যোগ করতে বা তথ্য মুছে ফেলার অনুরোধ করতে দুটোই লাগবে। লিখে রাখুন "
                         "বা স্ক্রিনশট নিন।"},
    "done.case_id": {"en": "Case ID", "bn": "কেস আইডি"},
    "done.tracking_code": {"en": "Tracking code", "bn": "ট্র্যাকিং কোড"},
    "done.code_once": {"en": "Shown only once, when the report was first submitted.",
                       "bn": "এটি শুধু একবারই দেখানো হয় — রিপোর্ট প্রথম জমা দেওয়ার সময়।"},
    "done.saved_at": {"en": "Saved at {when} (UTC, server clock).",
                      "bn": "জমা পড়েছে {when} (UTC, সার্ভারের ঘড়ি অনুযায়ী)।"},
    "done.received_h": {"en": "What we received", "bn": "আমরা যা পেয়েছি"},
    "done.item": {"en": "{kind} — {name} ({size}) — fingerprinted",
                  "bn": "{kind} — {name} ({size}) — ফিঙ্গারপ্রিন্ট নেওয়া হয়েছে"},
    "done.item_match": {"en": ", arrived unchanged ✓", "bn": ", কোনো বদল ছাড়াই পৌঁছেছে ✓"},
    "done.item_mismatch": {"en": "did not match the phone's fingerprint",
                           "bn": "ফোনের ফিঙ্গারপ্রিন্টের সঙ্গে মেলেনি"},
    "done.no_files": {"en": "No files were attached. You can add photos later from the tracking page.",
                      "bn": "কোনো ফাইল দেওয়া হয়নি। পরে ট্র্যাকিং পাতা থেকে ছবি যোগ করতে পারবেন।"},
    "done.next_h": {"en": "What happens next", "bn": "এরপর কী হবে"},
    "done.next1": {"en": "A reviewer will check your report. This is an internal review by the Pramaana "
                         "project team.",
                   "bn": "একজন পর্যালোচক আপনার রিপোর্ট দেখবেন। এটি প্রমাণ প্রকল্প দলের নিজস্ব পর্যালোচনা।"},
    "done.next2": {"en": "If more information is needed, the tracking page will say what.",
                   "bn": "আরও তথ্য লাগলে ট্র্যাকিং পাতায় কী লাগবে তা জানানো হবে।"},
    "done.next3_html": {"en": "<strong>If your crop is insured, you must still inform your insurer "
                              "yourself</strong> (for example through the insurer's app, helpline or office). "
                              "Pramaana does not do this for you.",
                        "bn": "<strong>ফসলের বিমা থাকলে বিমা সংস্থাকে আপনাকেই জানাতে হবে</strong> (যেমন বিমা "
                              "সংস্থার অ্যাপ, হেল্পলাইন বা অফিসের মাধ্যমে)। প্রমাণ আপনার হয়ে এটা করে না।"},
    "done.open_tracking": {"en": "Open tracking page", "bn": "ট্র্যাকিং পাতা খুলুন"},
    "done.another": {"en": "Report another field", "bn": "অন্য জমির খবর দিন"},

    # ------------------------------------------------------------ track
    "track.title": {"en": "Track a case", "bn": "দাবির অবস্থা দেখুন"},
    "track.intro": {"en": "Enter the case ID and tracking code you received when you submitted the report.",
                    "bn": "রিপোর্ট জমা দেওয়ার সময় যে কেস আইডি আর ট্র্যাকিং কোড পেয়েছিলেন, সেগুলি লিখুন।"},
    "track.open": {"en": "Open case", "bn": "কেস খুলুন"},
    "track.lost": {"en": "Lost your code? Ask the field operator or the project team. For your privacy, codes "
                         "cannot be recovered on this page.",
                   "bn": "কোড হারিয়ে গেছে? মাঠকর্মী বা প্রকল্প দলের সঙ্গে যোগাযোগ করুন। আপনার গোপনীয়তার জন্য "
                         "এই পাতা থেকে কোড ফেরত পাওয়া যায় না।"},
    "track.bad_code": {"en": "Case ID or tracking code is not correct.",
                       "bn": "কেস আইডি বা ট্র্যাকিং কোড ঠিক নয়।"},
    "case.title": {"en": "Case {case_id}", "bn": "কেস {case_id}"},
    "case.h1": {"en": "Case", "bn": "কেস"},
    "case.next_step": {"en": "Next step:", "bn": "পরের ধাপ:"},
    "case.reviewer_note": {"en": "Reviewer's note ({when}):", "bn": "পর্যালোচকের মন্তব্য ({when}):"},
    "case.files_h": {"en": "Files received ({count})", "bn": "পাওয়া ফাইল ({count})"},
    "case.file_item": {"en": "{kind} — {name} — received {when}", "bn": "{kind} — {name} — পাওয়া গেছে {when}"},
    "case.no_files": {"en": "No files yet.", "bn": "এখনও কোনো ফাইল নেই।"},
    "case.uploading": {"en": "Uploading…", "bn": "আপলোড হচ্ছে…"},
    "case.add_h": {"en": "Add more files", "bn": "আরও ফাইল যোগ করুন"},
    "case.upload": {"en": "Upload files", "bn": "ফাইল আপলোড করুন"},
    "case.dossier_h": {"en": "Evidence file (dossier)", "bn": "প্রমাণ-ফাইল (ডসিয়ার)"},
    "case.dossier_p": {"en": "Version {version} prepared {when}. It is a prepared document, not a claim "
                             "approval or an official certificate.",
                       "bn": "সংস্করণ {version}, তৈরি হয়েছে {when}। এটি একটি গোছানো নথি মাত্র — দাবি মঞ্জুরি বা "
                             "সরকারি শংসাপত্র নয়। ডসিয়ারটি ইংরেজিতে।"},
    "case.download": {"en": "⬇ Download dossier (PDF)", "bn": "⬇ ডসিয়ার ডাউনলোড করুন (PDF)"},
    "case.erase_h": {"en": "Delete my personal data", "bn": "আমার ব্যক্তিগত তথ্য মুছে দিন"},
    "case.erase_requested": {"en": "You asked for deletion on {when}. An administrator will carry it out.",
                             "bn": "আপনি {when} তারিখে তথ্য মোছার অনুরোধ করেছেন। একজন প্রশাসক কাজটি করবেন।"},
    "case.erase_explain": {"en": "Your name, phone number, land details, location, photos and documents will "
                                 "be deleted. A short non-personal record (case ID, dates, file fingerprints and "
                                 "the audit log) will remain.",
                           "bn": "আপনার নাম, ফোন নম্বর, জমির বিবরণ, অবস্থান, ছবি ও কাগজপত্র মুছে ফেলা হবে। একটি "
                                 "ছোট, অ-ব্যক্তিগত রেকর্ড (কেস আইডি, তারিখ, ফাইলের ফিঙ্গারপ্রিন্ট আর অডিট লগ) "
                                 "থেকে যাবে।"},
    "case.erase_confirm": {"en": "Ask for your personal data to be deleted? This cannot be undone once "
                                 "carried out.",
                           "bn": "আপনার ব্যক্তিগত তথ্য মুছে ফেলার অনুরোধ করবেন? একবার মুছে ফেলা হলে আর ফেরানো "
                                 "যাবে না।"},
    "case.erase_button": {"en": "Request deletion", "bn": "মুছে ফেলার অনুরোধ করুন"},
    "case.files_received": {"en": "{count} file(s) received and fingerprinted.",
                            "bn": "{count}টি ফাইল পাওয়া গেছে এবং ফিঙ্গারপ্রিন্ট নেওয়া হয়েছে।"},
    "case.choose_file": {"en": "Please choose at least one file.", "bn": "অন্তত একটি ফাইল বেছে নিন।"},
    "case.erasure_recorded": {"en": "Your deletion request is recorded. An administrator will carry it out.",
                              "bn": "তথ্য মোছার অনুরোধ লেখা হয়েছে। একজন প্রশাসক কাজটি করবেন।"},
    "case.synthetic": {"en": "SYNTHETIC DEMONSTRATION — NOT REAL EVIDENCE",
                       "bn": "কাল্পনিক নমুনা — আসল প্রমাণ নয়"},

    # ------------------------------------------------------------ badges
    "badge.synthetic": {"en": "⚠ SYNTHETIC — NOT REAL EVIDENCE", "bn": "⚠ কাল্পনিক — আসল প্রমাণ নয়"},
    "badge.field_test": {"en": "Field usability test", "bn": "মাঠ-পরীক্ষা"},
    "badge.real": {"en": "Real record", "bn": "আসল রেকর্ড"},
    "badge.synthetic_short": {"en": "SYNTHETIC", "bn": "কাল্পনিক"},

    # ------------------------------------------------------------ deadline panel
    "dl.heading": {"en": "Intimation deadline", "bn": "বিমা সংস্থাকে জানানোর সময়সীমা"},
    "dl.simulated": {"en": "SIMULATED (synthetic case)", "bn": "কাল্পনিক (নমুনা কেস)"},
    "dl.verified": {"en": "Rule verified", "bn": "নিয়ম যাচাই করা"},
    "dl.provisional": {"en": "Provisional — unverified", "bn": "অস্থায়ী — যাচাই হয়নি"},
    "dl.prefix_simulated": {"en": "SIMULATED: ", "bn": "কাল্পনিক: "},
    "dl.prefix": {"en": "If applicable: ", "bn": "প্রযোজ্য হলে: "},
    "dl.due": {"en": "Due by {when}", "bn": "শেষ সময়: {when}"},
    "dl.ended": {"en": "Window ended {when}", "bn": "সময়সীমা শেষ হয়েছে: {when}"},
    "dl.how": {"en": "How this is calculated", "bn": "কীভাবে হিসাব করা হয়"},
    "dl.english_rules": {"en": "", "bn": "নিয়মের বিবরণ ইংরেজিতে রাখা হয়েছে, কারণ সেগুলি আইনি নথি থেকে নেওয়া।"},
    "dl.scheme": {"en": "Scheme (reported)", "bn": "বিমা প্রকল্প (আপনার দেওয়া তথ্য)"},
    "dl.incident_start": {"en": "Incident start (UTC)", "bn": "ঘটনা শুরুর সময় (UTC)"},
    "dl.time_assumed": {"en": "(time not given — 00:00 IST assumed, the earliest possible)",
                        "bn": "(সময় দেওয়া হয়নি — সবচেয়ে আগের সম্ভাব্য সময়, রাত ১২টা IST, ধরা হয়েছে)"},
    "dl.duration": {"en": "Rule duration", "bn": "নিয়মের সময়কাল"},
    "dl.hours": {"en": "{hours} hours", "bn": "{hours} ঘণ্টা"},
    "dl.none_configured": {"en": "None configured", "bn": "কিছু ঠিক করা নেই"},
    "dl.source": {"en": "Rule source", "bn": "নিয়মের উৎস"},
    "dl.applicability": {"en": "Applicability", "bn": "কখন প্রযোজ্য"},
    "dl.recorded": {"en": "Case recorded (UTC)", "bn": "কেস লেখা হয়েছে (UTC)"},
    "dl.no_filing": {"en": "Pramaana does not file, send or forward any intimation.",
                     "bn": "প্রমাণ কোনো খবর (ইন্টিমেশন) জমা দেয়, পাঠায় বা এগিয়ে দেয় না।"},
    # Bengali renderings of pramaana_rules.assess_deadline messages (English comes from that module).
    "dl.msg_unverified": {"en": "", "bn": "প্রযোজ্য বিমা প্রকল্প বা পলিসির সঙ্গে মিলিয়ে সময়সীমাটি যাচাই করা দরকার।"},
    "dl.msg_provisional": {"en": "", "bn": "অস্থায়ী — "},
    "dl.msg_no_rule": {"en": "", "bn": "‘{scheme}’-এর জন্য কোনো সময়সীমা ঠিক করা নেই। "},
    "dl.msg_no_incident": {"en": "", "bn": "ঘটনার তারিখ না থাকায় সময়সীমা হিসাব করা যায়নি।"},
    "dl.msg_open": {"en": "", "bn": "যদি {hours} ঘণ্টার নিয়মটি প্রযোজ্য হয়, তাহলে বিমা সংস্থাকে {when}-এর মধ্যে "
                                    "জানাতে হবে। প্রমাণ নিজে এই খবর পাঠায় না।"},
    "dl.msg_passed": {"en": "", "bn": "যদি {hours} ঘণ্টার নিয়মটি প্রযোজ্য হয়, তাহলে সময়সীমা {when}-এ শেষ "
                                      "হয়েছে। দেরির কারণ ব্যাখ্যা করার দরকার হতে পারে।"},

    # ------------------------------------------------------------ verify
    "verify.title": {"en": "Verify a file", "bn": "ফাইল যাচাই করুন"},
    "verify.intro": {"en": "Choose a dossier PDF or an evidence file. Pramaana computes its SHA-256 fingerprint "
                           "and checks whether it matches a file it recorded. The file is not saved.",
                     "bn": "একটি ডসিয়ার PDF বা প্রমাণের ফাইল বেছে নিন। প্রমাণ এর SHA-256 ফিঙ্গারপ্রিন্ট বের করে "
                           "দেখবে, সেটি আগে রাখা কোনো ফাইলের সঙ্গে মেলে কি না। ফাইলটি রাখা হয় না।"},
    "verify.file": {"en": "File", "bn": "ফাইল"},
    "verify.check": {"en": "Check file", "bn": "ফাইল যাচাই করুন"},
    "verify.busy": {"en": "Checking…", "bn": "যাচাই হচ্ছে…"},
    "verify.choose": {"en": "Choose a file to check.", "bn": "যাচাই করার জন্য একটি ফাইল বেছে নিন।"},
    "verify.result": {"en": "Result for {name}", "bn": "{name}-এর ফলাফল"},
    "verify.match_html": {"en": "<strong>✓ Match found.</strong> This file is byte-for-byte identical to a file "
                                "Pramaana recorded:",
                          "bn": "<strong>✓ মিল পাওয়া গেছে।</strong> এই ফাইলটি প্রমাণে রাখা একটি ফাইলের সঙ্গে "
                                "হুবহু (প্রতিটি বাইট) এক:"},
    "verify.doc_item": {"en": "Dossier {doc_id} (version {version}) for case {case_id}, generated {when}",
                        "bn": "কেস {case_id}-এর ডসিয়ার {doc_id} (সংস্করণ {version}), তৈরি {when}"},
    "verify.ev_item": {"en": "Evidence {evidence_id} ({kind}) for case {case_id}, received {when}",
                       "bn": "কেস {case_id}-এর প্রমাণ {evidence_id} ({kind}), পাওয়া গেছে {when}"},
    "verify.match_note": {"en": "A match shows the file has not changed since Pramaana recorded it. It does not "
                                "show that the content is true, who made it, or that it is legally admissible.",
                          "bn": "মিল পাওয়া মানে প্রমাণে রাখার পর থেকে ফাইলটি বদলায়নি। এতে বোঝা যায় না যে "
                                "বিষয়বস্তু সত্য, কে তৈরি করেছেন, বা এটি আইনত গ্রাহ্য।"},
    "verify.no_match_html": {"en": "<strong>No match.</strong> Pramaana has no record of a file with this "
                                   "fingerprint. The file may have been changed (even one byte), re-saved, or never "
                                   "recorded here.",
                             "bn": "<strong>মিল পাওয়া যায়নি।</strong> এই ফিঙ্গারপ্রিন্টের কোনো ফাইল প্রমাণে নেই। "
                                   "ফাইলটি হয়তো বদলানো হয়েছে (এমনকি একটি বাইটও), আবার সেভ করা হয়েছে, অথবা এখানে "
                                   "কখনও রাখা হয়নি।"},

    # ------------------------------------------------------------ errors
    "error.404": {"en": "Not found", "bn": "পাওয়া যায়নি"},
    "error.403": {"en": "Not allowed", "bn": "অনুমতি নেই"},
    "error.429": {"en": "Please wait", "bn": "একটু অপেক্ষা করুন"},
    "error.413": {"en": "File too large", "bn": "ফাইলটি খুব বড়"},
    "error.other": {"en": "Something went wrong", "bn": "কিছু একটা সমস্যা হয়েছে"},
    "error.back": {"en": "← Go back", "bn": "← ফিরে যান"},
    "error.home": {"en": "Home", "bn": "মূল পাতা"},
    "error.generic": {"en": "", "bn": "অনুরোধটি সম্পূর্ণ করা যায়নি।"},
    "error.generic_404": {"en": "", "bn": "আপনি যে পাতাটি খুঁজছেন সেটি নেই।"},
    "err.csrf": {"en": "Your form session expired or is invalid. Please go back, reload the page and try again.",
                 "bn": "ফর্মের সময় পেরিয়ে গেছে বা সেটি অবৈধ। ফিরে গিয়ে পাতাটি আবার লোড করে চেষ্টা করুন।"},
    "err.too_large": {"en": "The upload is too large. Each file may be up to {mb} MB.",
                      "bn": "আপলোড খুব বড়। প্রতিটি ফাইল সর্বোচ্চ {mb} MB হতে পারে।"},
    "err.server": {"en": "Something went wrong on the server. Nothing you entered has been published. Please "
                         "try again.",
                   "bn": "সার্ভারে সমস্যা হয়েছে। আপনার দেওয়া কোনো তথ্য প্রকাশ করা হয়নি। আবার চেষ্টা করুন।"},
    "err.too_many_reports": {"en": "Too many reports from this device. Please wait and try again.",
                             "bn": "এই ডিভাইস থেকে অনেকগুলি রিপোর্ট এসেছে। কিছুক্ষণ পরে আবার চেষ্টা করুন।"},
    "err.too_many_attempts": {"en": "Too many attempts. Please wait 15 minutes.",
                              "bn": "অনেকবার চেষ্টা করা হয়েছে। ১৫ মিনিট অপেক্ষা করুন।"},
    "err.case_not_in_session": {"en": "Case not found in this browser session. Use 'Track a case'.",
                                "bn": "এই ব্রাউজারে কেসটি পাওয়া যায়নি। ‘দাবির অবস্থা দেখুন’ ব্যবহার করুন।"},
    "err.open_from_track": {"en": "Open this case from 'Track a case' with your tracking code.",
                            "bn": "‘দাবির অবস্থা দেখুন’ পাতা থেকে ট্র্যাকিং কোড দিয়ে কেসটি খুলুন।"},
    "err.no_new_files": {"en": "This case no longer accepts new files.",
                         "bn": "এই কেসে আর নতুন ফাইল নেওয়া হয় না।"},
    "err.required": {"en": "This is required.", "bn": "এটি পূরণ করা আবশ্যক।"},
    "err.full_name": {"en": "Please enter the full name.", "bn": "পুরো নাম লিখুন।"},
    "err.damage_type": {"en": "Please choose what happened.", "bn": "কী হয়েছে তা বেছে নিন।"},
    "err.phone": {"en": "Enter a 10-digit Indian mobile number, or leave it empty.",
                  "bn": "১০ অঙ্কের ভারতীয় মোবাইল নম্বর লিখুন, অথবা খালি রাখুন।"},
    "err.future": {"en": "The date cannot be in the future.", "bn": "তারিখটি ভবিষ্যতের হতে পারে না।"},
    "err.year": {"en": "Please check the year.", "bn": "সালটি আবার দেখে নিন।"},
    "err.date_format": {"en": "Use the date picker (YYYY-MM-DD).",
                        "bn": "তারিখ বেছে নেওয়ার ঘরটি ব্যবহার করুন (YYYY-MM-DD)।"},
    "err.time_format": {"en": "Use 24-hour time, for example 06:30.",
                        "bn": "২৪ ঘণ্টার হিসাবে সময় লিখুন, যেমন 06:30।"},
    "err.number_range": {"en": "Enter a number between {lo} and {hi}.",
                         "bn": "{lo} থেকে {hi}-এর মধ্যে একটি সংখ্যা লিখুন।"},
    "err.coordinates": {"en": "", "bn": "অক্ষাংশ ও দ্রাঘিমাংশ আবার দেখে নিন (যেমন 22.66 আর 87.72)।"},
    "err.consent": {"en": "Consent is needed before the report can be saved.",
                    "bn": "রিপোর্ট জমা দেওয়ার আগে সম্মতি দেওয়া দরকার।"},
    "err.file_empty": {"en": "'{name}' is empty and was not accepted.",
                       "bn": "‘{name}’ ফাইলটি খালি, তাই নেওয়া হয়নি।"},
    "err.file_too_large": {"en": "'{name}' is larger than {mb} MB.",
                           "bn": "‘{name}’ ফাইলটি {mb} MB-এর চেয়ে বড়।"},
    "err.file_type": {"en": "'{name}' is not an accepted {kind} file type.",
                      "bn": "‘{name}’ গ্রহণযোগ্য {kind} ফাইল নয়।"},
    "err.too_many_files": {"en": "Please upload at most {n} files at a time.",
                           "bn": "একবারে সর্বোচ্চ {n}টি ফাইল আপলোড করুন।"},

    # ------------------------------------------------------------ browser script
    "js.file_too_large": {"en": "{name} — too large ({size}), it will be rejected",
                          "bn": "{name} — খুব বড় ({size}), এটি নেওয়া হবে না"},
    "js.file_hashing": {"en": "{name} ({size}) — fingerprinting…",
                        "bn": "{name} ({size}) — ফিঙ্গারপ্রিন্ট নেওয়া হচ্ছে…"},
    "js.file_hashed": {"en": "{name} ({size}) — SHA-256 {hash}…", "bn": "{name} ({size}) — SHA-256 {hash}…"},
    "js.gps_unsupported": {"en": "This phone or browser cannot share its location. Type the numbers instead.",
                           "bn": "এই ফোন বা ব্রাউজার লোকেশন দিতে পারছে না। সংখ্যাগুলি নিজে লিখুন।"},
    "js.gps_finding": {"en": "Finding location… stand in or next to the field.",
                       "bn": "লোকেশন খোঁজা হচ্ছে… জমির মধ্যে বা পাশে দাঁড়ান।"},
    "js.gps_recorded": {"en": "Location recorded from the phone (accuracy about ±{m} m). Check it is the "
                              "affected field, not your home.",
                        "bn": "ফোন থেকে লোকেশন নেওয়া হয়েছে (নির্ভুলতা প্রায় ±{m} মিটার)। দেখে নিন এটি "
                              "ক্ষতিগ্রস্ত জমির লোকেশন, বাড়ির নয়।"},
    "js.gps_failed": {"en": "Could not get location ({err}). You can type it, or leave it empty.",
                      "bn": "লোকেশন পাওয়া যায়নি ({err})। নিজে লিখতে পারেন, বা খালি রাখতে পারেন।"},
    "js.draft_restored": {"en": "Restored a draft saved on this device. Photos must be chosen again.",
                          "bn": "এই ডিভাইসে রাখা খসড়া ফিরিয়ে আনা হয়েছে। ছবিগুলি আবার বেছে নিতে হবে।"},
    "js.draft_saved": {"en": "Draft saved on this device.", "bn": "খসড়া এই ডিভাইসে রাখা হয়েছে।"},
    "js.draft_cleared": {"en": "Draft cleared.", "bn": "খসড়া মুছে ফেলা হয়েছে।"},
    "js.window_ended": {"en": "window ended", "bn": "সময়সীমা শেষ"},
    "js.time_left": {"en": "{h}h {m}m {s}s left", "bn": "আর {h} ঘণ্টা {m} মিনিট {s} সেকেন্ড বাকি"},
}

# Keys whose English is intentionally empty: they only add Bengali-mode text.
BENGALI_ONLY = frozenset(k for k, v in STRINGS.items() if not v["en"])

# Bengali for option labels shown on farmer pages (English lives in pramaana_text.LABELS).
LABELS_BN: Dict[str, Dict[str, str]] = {
    "status": {
        "SUBMITTED": "জমা পড়েছে — পর্যালোচনার অপেক্ষায়",
        "UNDER_REVIEW": "পর্যালোচনা চলছে",
        "INFO_REQUESTED": "আরও তথ্য দরকার",
        "READY_FOR_SUBMISSION": "ডসিয়ার তৈরি — দাবিদারকে সরকারি মাধ্যমে জমা দিতে হবে",
        "REFERRED_FOR_LEGAL_AID": "আইনি সহায়তার পরামর্শের জন্য পাঠানো হয়েছে",
        "CLOSED": "বন্ধ",
        "ERASED": "ব্যক্তিগত তথ্য মুছে ফেলা হয়েছে",
    },
    "tenancy": {
        "owner": "নিজের জমি, নিজে চাষ (রায়ত)",
        "recorded_bargadar": "নথিভুক্ত বর্গাদার (আপনার দাবি অনুযায়ী)",
        "unrecorded_sharecropper": "ভাগচাষি, নথিভুক্ত নয় (আপনার দাবি অনুযায়ী)",
        "lessee": "ইজারা / অন্য ধরনের প্রজা (আপনার দাবি অনুযায়ী)",
        "unsure": "নিশ্চিত নই",
    },
    "damage_type": {
        "submergence": "বন্যার জলে ফসল ডুবে গেছে",
        "waterlogging": "অনেকদিন জল জমে আছে",
        "silt_sand": "জমিতে বালি / পলি জমেছে",
        "other": "অন্য কিছু",
    },
    "intimation_status": {
        "done": "হ্যাঁ, বিমা সংস্থা / কর্তৃপক্ষকে জানিয়েছি",
        "not_done": "না, এখনও জানাইনি",
        "unknown": "জানি না",
    },
    "scheme": {
        "PMFBY": "প্রধানমন্ত্রী ফসল বিমা যোজনা (PMFBY)",
        "BSB": "বাংলা শস্য বিমা (পশ্চিমবঙ্গ)",
        "OTHER": "অন্য প্রকল্প",
        "NOT_INSURED": "বিমা নেই",
        "UNKNOWN": "জানি না",
    },
    "evidence_kind": {
        "photo": "জমির ছবি",
        "document": "সহায়ক কাগজপত্র",
        "audio": "ভয়েস নোট",
        "satellite_rendering": "উপগ্রহ চিত্র",
        "synthetic_placeholder": "কাল্পনিক নমুনা ছবি",
    },
}


def normalise(lang: Any) -> str:
    return lang if lang in SUPPORTED else DEFAULT_LANG


def _params_for(lang: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """A parameter may itself be bilingual: {"en": ..., "bn": ...}."""
    return {k: (v[lang] if isinstance(v, dict) and set(v) == {"en", "bn"} else v) for k, v in params.items()}


def t(key: str, lang: str, **params: Any) -> str:
    """Text for `key` in `lang` (falls back to English). Raises KeyError for unknown keys."""
    entry = STRINGS[key]
    lang = normalise(lang)
    text = entry.get(lang) or entry["en"]
    return text.format(**_params_for(lang, params)) if params else text


class Bi(str):
    """Text held in both languages.

    It *is* the text in the language the page was rendered in, so code that
    treats it as a plain string keeps working; `en` and `bn` let the page switch
    language in place without a reload (see span() / attrs() and pramaana.js).
    """

    en: str
    bn: str
    html: bool

    def __new__(cls, en: str, bn: str, lang: str, html: bool = False) -> "Bi":
        obj = super().__new__(cls, (bn or en) if normalise(lang) == "bn" else en)
        obj.en, obj.bn, obj.html = en, bn or en, html
        return obj

    def as_dict(self) -> Dict[str, str]:
        return {"en": self.en, "bn": self.bn}

    @classmethod
    def from_dict(cls, d: Dict[str, str], lang: str) -> "Bi":
        return cls(d.get("en", ""), d.get("bn", ""), lang)


def both(key: str, lang: str, **params: Any) -> Bi:
    """`key` in both languages, shown in `lang`. Keys ending in _html carry trusted markup."""
    return Bi(t(key, "en", **params), t(key, "bn", **params), lang, html=key.endswith("_html"))


def span(text: Any, tag: str = "span") -> Markup:
    """Render bilingual text as an element the page can switch; plain text is just escaped."""
    if not isinstance(text, Bi):
        return Markup.escape(text)
    payload = json.dumps(text.as_dict(), ensure_ascii=False)
    if text.html:  # our own fixed markup (keys ending in _html), never user input
        return Markup('<{0} data-i18n-html="{1}">{2}</{0}>').format(Markup(tag), payload, Markup(str(text)))
    return Markup('<{0} data-i18n="{1}">{2}</{0}>').format(Markup(tag), payload, str(text))


def attrs(*mappings: Dict[str, Any]) -> Markup:
    """Attributes in the current language plus a data-i18n-attrs map to switch them.

    Several mappings are merged, so a macro can add its own attributes to a caller's.
    """
    mapping: Dict[str, Any] = {}
    for m in mappings:
        mapping.update(m or {})
    parts = [Markup('{}="{}"').format(Markup(name), str(value)) for name, value in mapping.items()]
    data = {name: (value.as_dict() if isinstance(value, Bi) else {"en": str(value), "bn": str(value)})
            for name, value in mapping.items()}
    parts.append(Markup('data-i18n-attrs="{}"').format(json.dumps(data, ensure_ascii=False)))
    return Markup(" ").join(parts)


def i18n_json(text: Bi) -> str:
    """The data-i18n payload for elements that cannot hold a <span> (option, title)."""
    return json.dumps(text.as_dict(), ensure_ascii=False)


def js_strings(lang: str) -> Dict[str, str]:
    """The browser script's strings for `lang`, keyed without the 'js.' prefix."""
    return {k[3:]: t(k, lang) for k in STRINGS if k.startswith("js.")}


def deadline_message_bn(d: Dict[str, Any]) -> str:
    """Bengali equivalent of the message pramaana_rules.assess_deadline builds in English."""
    state = d.get("state")
    unverified = t("dl.msg_unverified", "bn")
    if state == "no_rule":
        return t("dl.msg_no_rule", "bn", scheme=d.get("scheme_label", "")) + unverified
    if state == "no_incident_time":
        return t("dl.msg_no_incident", "bn")
    prefix = "" if d.get("verified") else t("dl.msg_provisional", "bn") + unverified + " "
    key = "dl.msg_open" if state == "open" else "dl.msg_passed"
    return prefix + t(key, "bn", hours=d.get("duration_hours"), when=d.get("deadline_ist", ""))
