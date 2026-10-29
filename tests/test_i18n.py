"""Tests for the English / Bengali switch on farmer pages."""

from __future__ import annotations

import html as html_lib
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

    @staticmethod
    def visible(html: str) -> str:
        """Visible text only: drops scripts, hidden alternate-language blocks, and tag attributes."""
        body = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S)
        body = re.sub(r"<(div|p)\b[^>]*\bdata-lang-only=\"[^\"]+\"[^>]*\bhidden\b[^>]*>.*?</\1>", "", body, flags=re.S)
        return re.sub(r"<[^>]+>", "", body)

    def test_switch_sets_cookie_and_redirects_only_within_site(self):
        resp = self.farmer.get("/lang/bn?next=/report")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.location.endswith("/report"))
        cookie = resp.headers["Set-Cookie"]
        self.assertIn("pramaana_lang=bn", cookie)
        self.assertNotIn("HttpOnly", cookie)  # readable/writable by pramaana.js for in-place switching
        self.assertIn("SameSite=Lax", cookie)
        for bad in ("//evil.example", "https://evil.example", "/\\evil.example", ""):
            resp = self.farmer.get("/lang/en", query_string={"next": bad})
            self.assertEqual(resp.location.rstrip("/").split("localhost")[-1] or "/", "/", bad)
        self.assertEqual(self.farmer.get("/lang/fr").status_code, 404)

    def test_default_is_english_and_bengali_changes_the_page(self):
        html = self.farmer.get("/").get_data(as_text=True)
        self.assertIn('<html lang="en">', html)
        self.assertIn("Organise evidence of flood damage to your crop", self.visible(html))
        self.assertNotIn("বন্যায় ফসলের ক্ষতির প্রমাণ গুছিয়ে রাখুন", self.visible(html))
        self.assertIn('data-lang-only="bn" hidden', html)
        self.bengali()
        html = self.farmer.get("/").get_data(as_text=True)
        self.assertIn('<html lang="bn">', html)
        self.assertIn("বন্যায় ফসলের ক্ষতির প্রমাণ গুছিয়ে রাখুন", self.visible(html))
        self.assertNotIn("Organise evidence of flood damage", self.visible(html))
        self.assertIn("Organise evidence of flood damage to your crop", html)  # kept in data-i18n for in-place toggle
        self.assertIn('data-lang-only="en" hidden', html)
        self.assertIn('aria-current="true">বাংলা', html)

    def test_every_farmer_page_renders_in_bengali(self):
        self.bengali()
        for path, phrase in (("/", "ক্ষতির খবর দিন"), ("/report", "বন্যায় ফসলের সম্ভাব্য ক্ষতির খবর দিন"),
                             ("/track", "কেস খুলুন"), ("/verify", "ফাইল যাচাই করুন")):
            resp = self.farmer.get(path)
            html = resp.get_data(as_text=True)
            self.assertEqual(resp.status_code, 200, path)
            self.assertIn(phrase, self.visible(html), path)
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
        self.assertIn(text.CONSENT_TEXT_BN[0], self.visible(html))
        self.assertIn(text.CONSENT_TEXT[0], html)  # English original in details box + hidden en block
        self.assertIn('<div data-lang-only="en" hidden>', html)
        self.assertIn('name="consent_lang" value="bn"', html)
        if not text.CONSENT_BN_REVIEWED:
            self.assertIn("খসড়া অনুবাদ", self.visible(html))
        data = re.search(r'<script type="application/json" id="i18n-data">(.*?)</script>', html, re.S)
        strings = json.loads(data.group(1))
        self.assertEqual(set(strings), {"en", "bn"})
        self.assertEqual(strings["bn"]["gps_finding"], i18n.t("js.gps_finding", "bn"))
        self.assertEqual(strings["en"]["gps_finding"], i18n.t("js.gps_finding", "en"))
        expected_keys = {k[3:] for k in i18n.STRINGS if k.startswith("js.")}
        self.assertEqual(set(strings["bn"]), expected_keys)
        self.assertEqual(set(strings["en"]), expected_keys)

    def test_validation_errors_in_bengali(self):
        self.bengali()
        resp = self.report(claimant_name=None, consent=None, latitude="95", longitude="87")
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("এটি পূরণ করা আবশ্যক।", self.visible(html))
        self.assertIn("রিপোর্ট জমা দেওয়ার আগে সম্মতি দেওয়া দরকার।", self.visible(html))
        self.assertIn("অক্ষাংশ ও দ্রাঘিমাংশ আবার দেখে নিন", self.visible(html))

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
        self.assertIn("এই দুটি কোড যত্ন করে রাখুন", self.visible(done))
        page = self.farmer.get(f"/track/{case_id}").get_data(as_text=True)
        self.assertIn(text.FARMER_STATUS["SUBMITTED"]["bn"], self.visible(page))
        self.assertIn(text.FARMER_STATUS["SUBMITTED"]["next_bn"], self.visible(page))
        self.assertIn("কোনো সময়সীমা ঠিক করা নেই", self.visible(page))  # scheme not known -> no deadline rule
        self.assertNotIn(text.FARMER_STATUS["SUBMITTED"]["en"], self.visible(page))
        self.assertIn(text.FARMER_STATUS["SUBMITTED"]["en"], page)  # carried in data-i18n for in-place switch

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

    def test_in_place_bilingual_dom_payloads_and_flashed_messages(self):
        for lang_code in ("en", "bn"):
            other_code = "bn" if lang_code == "en" else "en"
            self.farmer.get(f"/lang/{lang_code}?next=/")
            for path in ("/", "/report", "/track", "/verify"):
                html = self.farmer.get(path).get_data(as_text=True)
                self.assertIn(f'data-set-lang="{lang_code}" aria-current="true"', html)
                self.assertNotIn(f'data-set-lang="{other_code}" aria-current="true"', html)
                self.assertIn('data-lang-cookie="pramaana_lang"', html)
                i18n_spans = re.findall(r'data-i18n="([^"]+)">([^<]*)<', html)
                self.assertTrue(i18n_spans, (lang_code, path))
                for raw_json, rendered in i18n_spans:
                    pair = json.loads(html_lib.unescape(raw_json))
                    self.assertEqual(set(pair), {"en", "bn"})
                    self.assertEqual(html_lib.unescape(rendered), pair[lang_code])
        # Verify multi-step report form (Steps 1-5), select options, radio cards, and consent_lang switchable attrs
        report_html = self.farmer.get("/report").get_data(as_text=True)
        unescaped_report = html_lib.unescape(report_html)
        for step_key in ("report.step_you", "report.step_field", "report.step_crop", "report.step_photos",
                         "report.step_check", "report.s1", "report.s2", "report.s3", "report.s4", "report.s5"):
            self.assertIn(i18n.t(step_key, "en"), unescaped_report)
            self.assertIn(i18n.t(step_key, "bn"), unescaped_report)
        opts = re.findall(r'<option value="([^"]+)" data-i18n="([^"]+)"', report_html)
        self.assertEqual(len(opts), len(text.LABELS["tenancy"]) + len(text.LABELS["scheme"])
                         + len(text.LABELS["intimation_status"]))
        radios = re.findall(r'<input type="radio"[^>]+data-i18n-attrs="([^"]+)"', report_html)
        self.assertEqual(len(radios), 2 + len(text.LABELS["damage_type"]))
        self.assertIn('name="consent_lang" value="bn" data-i18n-attrs=', report_html)
        # Flashed messages survive redirect with both languages so in-place toggle switches them too
        case_id = self.new_case(consent_lang="bn")
        page = self.farmer.get(f"/track/{case_id}").get_data(as_text=True)
        tok = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        resp = self.farmer.post(f"/track/{case_id}/evidence", data={"csrf_token": tok}, follow_redirects=True)
        flash_html = resp.get_data(as_text=True)
        self.assertIn(i18n.t("case.choose_file", "bn"), flash_html)
        self.assertIn(i18n.t("case.choose_file", "en"), flash_html)
        # Reviewer dashboard and case detail stay English even when pramaana_lang=bn cookie is set
        rev, _ = self.reviewer()
        self.bengali(rev)
        for rpath in ("/reviewer", f"/reviewer/case/{case_id}", "/reviewer/audit"):
            rresp = rev.get(rpath)
            self.assertEqual(rresp.status_code, 200, rpath)
            rhtml = rresp.get_data(as_text=True)
            self.assertIn('<html lang="en">', rhtml, rpath)
            self.assertNotIn('class="lang-switch"', rhtml, rpath)


if __name__ == "__main__":
    unittest.main()
