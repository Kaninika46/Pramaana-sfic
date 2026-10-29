"""Tests for the English / Bengali switch on farmer pages."""

from __future__ import annotations

import json
import re
import string
import unittest

from test_workflow import A, Base  # sets up the temporary database before importing the app

import pramaana_i18n as i18n
import pramaana_text as text

ALLOWED_TAGS = {"strong", "/strong", "span", "/span", "a", "/a"}


def placeholders(s: str) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(s) if name}


class StringTableTests(unittest.TestCase):
    def test_every_key_has_both_languages_and_matching_placeholders(self):
        for key, entry in i18n.STRINGS.items():
            self.assertEqual(set(entry), {"en", "bn"}, key)
            self.assertTrue(entry["bn"], f"{key}: Bengali missing")
            if key in i18n.BENGALI_ONLY:
                continue
            self.assertTrue(entry["en"], f"{key}: English missing")
            self.assertEqual(placeholders(entry["en"]), placeholders(entry["bn"]), key)

    def test_markup_only_in_html_keys_and_only_simple_tags(self):
        for key, entry in i18n.STRINGS.items():
            for lang, value in entry.items():
                tags = {m.split()[0] for m in re.findall(r"<([^>]+)>", value)}
                if key.endswith("_html"):
                    self.assertLessEqual(tags, ALLOWED_TAGS, (key, lang))
                else:
                    self.assertFalse(tags, f"{key} ({lang}) has markup but is escaped")

    def test_labels_fields_statuses_and_consent_are_complete(self):
        for group, bn in i18n.LABELS_BN.items():
            self.assertEqual(set(bn), set(text.LABELS[group]), group)
        for name, (en, bn) in text.FIELD.items():
            self.assertTrue(en and bn, name)
        for state, entry in text.FARMER_STATUS.items():
            self.assertTrue(entry["bn"] and entry["next_bn"], state)
        self.assertEqual(len(text.CONSENT_TEXT), len(text.CONSENT_TEXT_BN))
        self.assertNotEqual(text.CONSENT_VERSION, text.CONSENT_VERSION_BN)
        if not text.CONSENT_BN_REVIEWED:
            self.assertTrue(text.CONSENT_VERSION_BN.endswith("-draft"))

    def test_unknown_key_is_an_error_and_unknown_language_falls_back(self):
        with self.assertRaises(KeyError):
            i18n.t("no.such.key", "bn")
        self.assertEqual(i18n.t("nav.report", "xx"), "Report a loss")

    def test_bengali_deadline_messages(self):
        base = {"verified": False, "duration_hours": 72, "deadline_ist": "01 Nov 2026, 06:00 IST"}
        self.assertIn("72 ঘণ্টার", i18n.deadline_message_bn(dict(base, state="open")))
        self.assertIn("অস্থায়ী", i18n.deadline_message_bn(dict(base, state="passed")))
        self.assertNotIn("অস্থায়ী", i18n.deadline_message_bn(dict(base, state="open", verified=True)))
        self.assertIn("তারিখ না থাকায়", i18n.deadline_message_bn({"state": "no_incident_time"}))
        self.assertIn("‘BSB’", i18n.deadline_message_bn({"state": "no_rule", "scheme_label": "BSB"}))


class SwitchTests(Base):
    def bengali(self, client=None):
        (client or self.farmer).get("/lang/bn?next=/")

    def test_switch_sets_cookie_and_redirects_only_within_site(self):
        resp = self.farmer.get("/lang/bn?next=/report")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.location.endswith("/report"))
        cookie = resp.headers["Set-Cookie"]
        self.assertIn("pramaana_lang=bn", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        for bad in ("//evil.example", "https://evil.example", "/\\evil.example", ""):
            resp = self.farmer.get("/lang/en", query_string={"next": bad})
            self.assertEqual(resp.location.rstrip("/").split("localhost")[-1] or "/", "/", bad)
        self.assertEqual(self.farmer.get("/lang/fr").status_code, 404)

    def test_default_is_english_and_bengali_changes_the_page(self):
        html = self.farmer.get("/").get_data(as_text=True)
        self.assertIn('<html lang="en">', html)
        self.assertIn("Organise evidence of flood damage to your crop", html)
        self.bengali()
        html = self.farmer.get("/").get_data(as_text=True)
        self.assertIn('<html lang="bn">', html)
        self.assertIn("বন্যায় ফসলের ক্ষতির প্রমাণ গুছিয়ে রাখুন", html)
        self.assertNotIn("Organise evidence of flood damage", html)
        self.assertIn('aria-current="true">বাংলা', html)

    def test_every_farmer_page_renders_in_bengali(self):
        self.bengali()
        for path, phrase in (("/", "ক্ষতির খবর দিন"), ("/report", "বন্যায় ফসলের সম্ভাব্য ক্ষতির খবর দিন"),
                             ("/track", "কেস খুলুন"), ("/verify", "ফাইল যাচাই করুন")):
            resp = self.farmer.get(path)
            html = resp.get_data(as_text=True)
            self.assertEqual(resp.status_code, 200, path)
            self.assertIn(phrase, html, path)
            self.assertIn('class="lang-switch"', html, path)

    def test_reviewer_and_about_pages_stay_english(self):
        self.bengali()
        for path in ("/reviewer/login", "/about"):
            html = self.farmer.get(path).get_data(as_text=True)
            self.assertIn('<html lang="en">', html, path)
            self.assertNotIn('class="lang-switch"', html, path)

    def test_bengali_report_page_has_draft_consent_and_script_text(self):
        self.bengali()
        html = self.farmer.get("/report").get_data(as_text=True)
        self.assertIn(text.CONSENT_TEXT_BN[0], html)
        self.assertIn(text.CONSENT_TEXT[0], html)  # English original in a details box
        self.assertIn('name="consent_lang" value="bn"', html)
        if not text.CONSENT_BN_REVIEWED:
            self.assertIn("খসড়া অনুবাদ", html)
        data = re.search(r'<script type="application/json" id="i18n-data">(.*?)</script>', html, re.S)
        strings = json.loads(data.group(1))
        self.assertEqual(strings["gps_finding"], i18n.t("js.gps_finding", "bn"))
        self.assertEqual(set(strings), {k[3:] for k in i18n.STRINGS if k.startswith("js.")})

    def test_validation_errors_in_bengali(self):
        self.bengali()
        resp = self.report(claimant_name=None, consent=None, latitude="95", longitude="87")
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("এটি পূরণ করা আবশ্যক।", html)
        self.assertIn("রিপোর্ট জমা দেওয়ার আগে সম্মতি দেওয়া দরকার।", html)
        self.assertIn("অক্ষাংশ ও দ্রাঘিমাংশ আবার দেখে নিন", html)

    def test_consent_version_follows_the_language_shown(self):
        en_case = self.new_case(consent_lang="en")
        bn_case = self.new_case(consent_lang="bn")
        odd_case = self.new_case(consent_lang="xx")
        self.assertEqual(A.store.get_case(en_case)["consent_version"], text.CONSENT_VERSION)
        self.assertEqual(A.store.get_case(bn_case)["consent_version"], text.CONSENT_VERSION_BN)
        self.assertEqual(A.store.get_case(odd_case)["consent_version"], text.CONSENT_VERSION)
        notes = [a["note"] for a in A.store.list_audit(bn_case) if a["action"] == "CONSENT_RECORDED"]
        self.assertEqual(notes, [text.CONSENT_VERSION_BN])

    def test_tracking_flow_in_bengali(self):
        self.bengali()
        case_id = self.new_case(consent_lang="bn")
        done = self.farmer.get(f"/report/done/{case_id}").get_data(as_text=True)
        self.assertIn("এই দুটি কোড যত্ন করে রাখুন", done)
        page = self.farmer.get(f"/track/{case_id}").get_data(as_text=True)
        self.assertIn(text.FARMER_STATUS["SUBMITTED"]["bn"], page)
        self.assertIn(text.FARMER_STATUS["SUBMITTED"]["next_bn"], page)
        self.assertIn("কোনো সময়সীমা ঠিক করা নেই", page)  # scheme not known -> no deadline rule
        self.assertNotIn(text.FARMER_STATUS["SUBMITTED"]["en"], page)

    def test_errors_and_messages_in_bengali(self):
        self.bengali()
        other = A.app.test_client()
        self.bengali(other)
        resp = other.get("/track/PRM-2026-NOPE00")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("ট্র্যাকিং কোড দিয়ে কেসটি খুলুন", resp.get_data(as_text=True))
        tok = re.search(r'name="csrf_token" value="([^"]+)"',
                        other.get("/track").get_data(as_text=True)).group(1)
        resp = other.post("/track", data={"csrf_token": tok, "case_id": "X", "tracking_code": "Y"})
        self.assertIn("কেস আইডি বা ট্র্যাকিং কোড ঠিক নয়।", resp.get_data(as_text=True))
        resp = other.post("/verify", data={"csrf_token": tok}, content_type="multipart/form-data")
        self.assertIn("যাচাই করার জন্য একটি ফাইল বেছে নিন।", resp.get_data(as_text=True))
        resp = other.get("/no-such-page")
        self.assertEqual(resp.status_code, 404)
        self.assertIn('<html lang="en">', resp.get_data(as_text=True))  # not a farmer page


if __name__ == "__main__":
    unittest.main()
