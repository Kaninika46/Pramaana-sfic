# Pramaana (প্রমাণ)

AI-assisted agricultural flood evidence & claim-preparation system — a student public-interest
technology prototype for the Ghatal subdivision, Paschim Medinipur, West Bengal.

Pramaana is **not** a court, government body, insurer or legal-aid authority, is **not connected**
to any of them, and never files claims or intimations. See `/about` in the running app.

## Workflow

Farmer / field operator reports a suspected loss (`/report`) → files stored byte-for-byte and
SHA-256 fingerprinted → location + its source recorded → signed-in reviewer runs satellite analysis
(only when Earth Engine is genuinely configured) → re-checks every file hash → generates a labelled,
versioned dossier PDF whose hash is recorded → records a review decision in a hash-chained audit log.
Claimants follow progress at `/track` with their case ID and tracking code. Anyone can check a file
against recorded hashes at `/verify`.

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask app: routes, validation, uploads, auth, CSRF, CLI commands |
| `pramaana_store.py` | SQLite schema/migrations, cases, evidence, analyses, documents, audit chain |
| `pramaana_rules.py` | Deadline assessment and missing-information checklist |
| `pramaana_dossier.py` | Case dossier PDF generator |
| `pramaana_text.py` | Display labels, bilingual field labels, consent text (English and Bengali) |
| `pramaana_i18n.py` | English / Bengali text for farmer-facing pages |
| `gee_fetcher.py` | Earth Engine init, per-case Sentinel-1/Sentinel-2 analysis (+ legacy bundle code) |
| `pramaana_engine.py` | Legacy PDF generator and `legal_rules.json` loader |
| `legal_rules.json` | Legal references, deadline rules, engineering-audit flags |
| `templates/`, `static/` | UI (no external assets; strict CSP) |
| `tests/` | `unittest` suites |

## Windows PowerShell

```powershell
cd C:\Users\KANINIKA\OneDrive\Desktop\pramaan-sfic
python -m venv .venv                       # optional
.\.venv\Scripts\Activate.ps1               # optional
pip install -r requirements.txt

# Optional configuration (the app starts without any of these)
$env:PRAMAANA_SECRET_KEY = "<long random string>"   # else one is generated in instance\secret_key
$env:GEE_PROJECT_ID      = "<your-gcp-project>"     # enables satellite analysis
# $env:GEE_SERVICE_ACCOUNT  = "<sa>@<project>.iam.gserviceaccount.com"
# $env:GEE_PRIVATE_KEY_JSON = "C:\path\to\key.json"  # never commit this file
# (or run `earthengine authenticate` once instead of a service account)

# Database: created/migrated automatically on start (pramaana_audit.db). Create a reviewer:
flask --app app create-reviewer your_name --role admin     # prompts for a password (min 10 chars)

python app.py                              # http://127.0.0.1:5000
# For phones on the same Wi-Fi (field testing):  $env:PRAMAANA_HOST = "0.0.0.0"; python app.py

flask --app app seed-demo                  # optional: one SYNTHETIC demonstration case
flask --app app verify-audit               # check the audit hash chain

python -m unittest discover -s tests -v    # run tests
```

Other variables: `PRAMAANA_DB` (database path), `PRAMAANA_STORAGE_DIR` (where `uploads/` and
`dossiers/` live), `PRAMAANA_HTTPS_ONLY=1` (secure cookies behind HTTPS), `PORT`,
`PRAMAANA_REVIEWER_USER` / `PRAMAANA_REVIEWER_PASS` (one-time bootstrap of an admin account; no
default exists).

## Honest status

- Earth Engine analysis has been run live (project configured via `GEE_PROJECT_ID`). The flood model has now been validated
  against Sentinel-2 (see below) and the per-case analysis has been run live; it still needs field validation.
- Legal references need professional verification — see `software_audit_flags` in `legal_rules.json`.
- No field test has been carried out yet — see `docs/FIELD_TESTING.md` (planned: Gahira, Paschim Medinipur).
- Farmer pages can be switched between English and Bengali. The Bengali text, including the
  Bengali consent text (marked as a draft), needs review by a native speaker and the legal lead.
- Not production-ready: single-process rate limiting, SQLite, no backups, no HTTPS termination.

## Language (English / বাংলা)

Farmer-facing pages (home, report, report received, track, case page, verify, errors) have an
English | বাংলা switch in the header; the choice is kept in a cookie. Reviewer pages, the About page
and the dossier PDF stay English. All farmer-page text is in `pramaana_i18n.py` (one place to
review); field labels, statuses and the consent text are in `pramaana_text.py`. The Bengali consent
is shown as a draft, with the English original beside it, until `CONSENT_BN_REVIEWED = True`;
each case records which consent version (English or Bengali) was shown.

## Flood model accuracy

The app classifies Sentinel-1 radar with a **random forest on VV + VH**
(`data/flood_rf_model.json`, trained by `scripts/train_flood_rf.py`). It falls back to the
calibrated VV rule (`data/flood_model_calibration.json`) when a pass has no VH band. Pixels the
model cannot decide are marked `uncertain`. Permanent water (JRC) is reported separately.

Held-out accuracy (Ghatal, 15 km radius, 24 Sentinel-1/Sentinel-2 same-day pairs, 2019-2024):

| Model | Open-water F1 | Incl. flooded crops F1 | Test on unseen dates (open water) |
|---|---|---|---|
| Old rule (-18 dB) | 0.17 | 0.09 | 0.23 |
| Calibrated VV rule | 0.56 | 0.46 | 0.56 |
| Random forest VV+VH | **0.83** | **0.76** | **0.83** |

Reference is cloud-free Sentinel-2 water (MNDWI), dry before and water after: an optical
proxy, not a field survey. Samples are class-balanced, so precision on real claims can be lower.
**Known blind spot:** harvested or ploughed paddy also drops radar backscatter and can look
like new water; the area monitor checks every alert against Sentinel-2 for this reason.

```powershell
$env:GEE_PROJECT_ID = "<your-gcp-project>"
python scripts/validate_flood_model.py --write-calibration   # rule calibration
python scripts/train_flood_rf.py --write-model               # random forest (writes only if it beats the rule)
python scripts/train_flood_rf.py --rows artifacts/validation/rf_samples_latest.json --hold-out-dates
```

## Area flood monitor

`scripts/monitor_flood.py` checks the newest Sentinel-1 pass over an area (default: Ghatal,
10 km radius), runs the same model, cross-checks flood pixels with any clear Sentinel-2 image
within 2 days, and writes `artifacts/monitor/log.jsonl` plus a PNG map. Each alert is marked
`confirmed`, `contradicted` (suppressed) or `unconfirmed` (cloudy). Exit code 3 means alert.
Run it daily (Sentinel-1 revisits every few days); passes already processed are skipped.

```powershell
python scripts/monitor_flood.py
python scripts/monitor_flood.py --as-of 2024-09-20 --name replay --force   # replay a past date
```
