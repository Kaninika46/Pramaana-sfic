# Field usability test protocol (Gahira)

Status: **planned — not yet carried out.** Nothing here is a result.

Gahira, Paschim Medinipur, is the planned *test* location (exact place to be confirmed on the
day). Ghatal is the intended *deployment region*. Record them separately and never substitute
one for the other. The flood model was trained and validated only around Ghatal, so a satellite
check at Gahira is a single illustrative case, not a measure of accuracy.

## Purpose

An initial usability / feasibility check with one volunteer farmer: can the guided form be
completed on a basic smartphone, are the words understood, does GPS and photo upload work in
the field? One test cannot show that the system is effective in general.

## Before the visit

1. Start the app on a laptop: `$env:PRAMAANA_HOST="0.0.0.0"; python app.py`; join the phone to the
   laptop's hotspot and open `http://<laptop-ip>:5000`. (Plain HTTP on a LAN: the page uses its
   built-in SHA-256 fallback.)
2. Prepare a printed copy of the consent points and explain them in Bengali.
3. Agree with the participant whether this is a real loss or only a trial. Use **"Field test of
   this app"** unless it is a genuine claim the participant wants prepared.

## During the visit

- Ask for consent orally and in the form. The participant can stop at any time.
- Collect only what the form needs; do not record Aadhaar or bank numbers.
- Let the participant (or the helper) fill the form; observe, do not lead.
- Note: time per step, words not understood, GPS accuracy shown, upload success on the
  available network, any errors.

## Remote, operator-assisted variant (planned for Gahira)

The farmer does not use the form. They send photos and details by WhatsApp, and a team member
submits the case as field operator. This tests the operator-assisted workflow; it does **not**
test whether a farmer can use the form, so never describe it that way.

Before anything is sent:

1. Send the consent message (below) in Bengali and wait for a clear "yes". Save that reply.
2. Say it is a test of the app: it files no claim, guarantees no compensation, and data can be
   deleted on request.

Ask the farmer to send:

- Photos of the land **as a Document** (attach → Document), not as Photo. WhatsApp compresses
  photos and removes the date taken and GPS location; a document keeps the original file.
- Their **current location while standing in the field** (attach → Location → current location).
- Incident date (and time if known), crop, rough area, water depth and how long it stayed, and
  their insurance scheme if any (PMFBY, Bangla Shasya Bima, none). No Aadhaar or bank numbers.

When submitting:

- Fill "Helper / field operator name" with the team member's name.
- Enter the shared field coordinates and choose the **manual** location option, never device GPS
  (the operator's phone is not in the field).
- Upload the files exactly as received. Note in the case how they arrived, e.g. "received via
  WhatsApp as document on <date>". Fingerprints are of the received copies.
- If a flood date applies, the satellite check for that field and date is one illustrative case
  outside the validated area (see above), not a measure of accuracy.

## Afterwards — record (fill in only what actually happened)

| Item | Observation |
|---|---|
| Date / approximate place (village level) | |
| Phone model / network | |
| Completed without help? Which steps needed help? | |
| GPS accuracy reported (m) | |
| Upload problems | |
| Confusing words / labels | |
| Participant's own comments | |
| Case ID (TEST-…) | |
| Remote variant: consent reply saved (date) | |
| Remote variant: photos sent as document or photo? Date taken / GPS present in files? | |
| Remote variant: field location shared? | |
| Remote variant: satellite check (flood date, result) if applicable | |
| Follow-up: participant wants data kept / deleted | |

Do not publish identifying details, photos or coordinates from the test without separate consent.

## Consent message for the remote variant

Fill in the brackets. A Bengali-speaking team member reviews the wording before sending and may
make it more natural for the participant, keeping the meaning unchanged.

**বাংলা**

নমস্কার, আমি [নাম], [কলেজের নাম]-এর ছাত্র/ছাত্রী। আমরা "প্রমাণ" নামে একটি অ্যাপ পরীক্ষা করছি। অ্যাপটি বন্যায় ফসলের ক্ষতির প্রমাণ — ছবি, তারিখ, জমির জায়গা আর উপগ্রহের তথ্য — একসঙ্গে গুছিয়ে রাখতে সাহায্য করে।

এটা শুধু অ্যাপের একটা পরীক্ষা। এর মাধ্যমে কোনো বিমা দাবি জমা হবে না, আর কোনো ক্ষতিপূরণের নিশ্চয়তাও নেই। আমরা কোনো সরকারি দপ্তর বা বিমা সংস্থার সঙ্গে যুক্ত নই।

আপনি রাজি থাকলে আপনার পাঠানো ছবি, জমির লোকেশন আর নিচের তথ্যগুলো আমরা শুধু এই পরীক্ষার জন্য রাখব। আপনার আলাদা অনুমতি ছাড়া আপনার নাম, ছবি বা জমির সঠিক জায়গা কোথাও প্রকাশ করব না। আপনি যেকোনো সময় বললে আমরা সব তথ্য মুছে দেব। দয়া করে আধার বা ব্যাঙ্কের নম্বর পাঠাবেন না।

রাজি থাকলে "হ্যাঁ" লিখে উত্তর দিন। তারপর এগুলো পাঠান:

১. জমির ছবি — "ফটো" হিসেবে নয়, "ডকুমেন্ট" হিসেবে পাঠান (সংযুক্তি 📎 → ডকুমেন্ট), যাতে ছবির আসল তারিখ আর জায়গা থেকে যায়।
২. জমিতে দাঁড়িয়ে আপনার বর্তমান লোকেশন (সংযুক্তি 📎 → লোকেশন → বর্তমান লোকেশন পাঠান)।
৩. বন্যা কবে হয়েছিল (তারিখ, জানা থাকলে সময়)।
৪. কোন ফসল ছিল আর আনুমানিক কতটা জমি।
৫. জল কতটা উঠেছিল আর কতদিন ছিল।
৬. কোনো ফসল বিমা আছে কি না (প্রধানমন্ত্রী ফসল বিমা যোজনা, বাংলা শস্য বিমা, নাকি নেই)।

ধন্যবাদ।

**English (meaning of the Bengali)**

Hello, I am [name], a student at [college name]. We are testing an app called "Pramaana". It helps keep evidence of flood damage to crops together: photos, date, the field's location and satellite information.

This is only a test of the app. No insurance claim will be filed through it, and no compensation is guaranteed. We are not connected to any government office or insurance company.

If you agree, we will keep the photos, field location and the details below only for this test. We will not publish your name, photos or your field's exact location without your separate permission. Whenever you ask, we will delete all of it. Please do not send Aadhaar or bank numbers.

If you agree, reply "yes". Then please send:

1. Photos of the field — as a "Document", not as a "Photo" (attach 📎 → Document), so the original date and location stay in the picture.
2. Your current location while standing in the field (attach 📎 → Location → send current location).
3. When the flood happened (date, and time if you know it).
4. Which crop it was and roughly how much land.
5. How high the water rose and how long it stayed.
6. Whether you have crop insurance (PMFBY, Bangla Shasya Bima, or none).

Thank you.
