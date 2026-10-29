# Random-forest flood model (VV + VH) — validation results

Model in use by the app: `data/flood_rf_model.json` (`pramaana-flood-rf-0.1.0`, 40 trees,
uncertain when flood probability is within 0.1 of 0.5), trained by `scripts/train_flood_rf.py`.

Reference: cloud-free Sentinel-2 water (MNDWI), "new water" = dry before and water after;
an optical proxy, **not a field survey**. Region: Ghatal, 15 km radius. 24 same-day
Sentinel-1/Sentinel-2 pairs, 2019–2024, 42,317 samples. Samples are class-balanced, so
precision on real claims may be lower than shown. Coverage = share of samples the model
decided (the rest were marked uncertain).

## Run 1 — held-out map squares (`flood_rf_20261029T164353Z.json`)

Split: checkerboard of 0.02° (~2 km) squares; trained on 22,481 samples, tested on 19,836
from squares never used in training.

### Open (non-vegetated) new water vs dry — 16,131 test samples

| Model | Coverage | Overall acc. | Flood precision | Flood recall | Flood F1 | Kappa |
|---|---|---|---|---|---|---|
| Old rule (−18 dB) | 95.7 % | 79.8 % | 100.0 % | 9.3 % | 17.0 % | 0.137 |
| Calibrated VV rule | 85.2 % | 83.5 % | 82.5 % | 42.0 % | 55.6 % | 0.468 |
| **Random forest VV+VH** | **90.4 %** | **91.8 %** | **85.3 %** | **81.1 %** | **83.2 %** | **0.777** |

### All new water incl. flooded crops vs dry — 19,836 test samples

| Model | Coverage | Overall acc. | Flood precision | Flood recall | Flood F1 | Kappa |
|---|---|---|---|---|---|---|
| Old rule (−18 dB) | 96.0 % | 64.7 % | 100.0 % | 4.5 % | 8.7 % | 0.056 |
| Calibrated VV rule | 83.8 % | 72.3 % | 86.7 % | 31.4 % | 46.1 % | 0.326 |
| **Random forest VV+VH** | **89.2 %** | **84.3 %** | **89.8 %** | **66.4 %** | **76.4 %** | **0.650** |

## Run 2 — held-out map squares AND unseen dates (`flood_rf_20261029T164021Z.json`)

Stricter: trained on even-numbered date pairs in training squares (11,069 samples), tested on
odd-numbered date pairs in test squares (9,992). This mimics live use, where every date is new.
This run's model was for testing only; the app uses Run 1's model.

### Open new water vs dry — 8,078 test samples

| Model | Coverage | Overall acc. | Flood precision | Flood recall | Flood F1 | Kappa |
|---|---|---|---|---|---|---|
| Old rule (−18 dB) | 95.7 % | 79.9 % | 100.0 % | 13.3 % | 23.4 % | 0.190 |
| Calibrated VV rule | 82.5 % | 84.3 % | 87.9 % | 40.8 % | 55.7 % | 0.477 |
| **Random forest VV+VH** | **81.8 %** | **90.5 %** | **80.1 %** | **86.9 %** | **83.4 %** | **0.767** |

### All new water incl. flooded crops vs dry — 9,992 test samples

| Model | Coverage | Overall acc. | Flood precision | Flood recall | Flood F1 | Kappa |
|---|---|---|---|---|---|---|
| Old rule (−18 dB) | 96.1 % | 64.3 % | 100.0 % | 6.5 % | 12.2 % | 0.079 |
| Calibrated VV rule | 80.9 % | 71.1 % | 89.7 % | 26.1 % | 40.4 % | 0.282 |
| **Random forest VV+VH** | **80.3 %** | **84.6 %** | **85.9 %** | **73.9 %** | **79.4 %** | **0.672** |

## Related checks

- Documented Ghatal floods (Ahammad et al. 2026): `documented_floods_results_20261029T175702Z.md`
  and the Sentinel-2 follow-up `documented_floods_optical_20261029T181711Z.md`
  (2 of 3 pre-registered criteria failed narrowly; see those files).
- Area monitor: harvest false alarm on 2026-10-25 caught by optical cross-check; Sept 2024
  flood replay confirmed (`artifacts/monitor/log.jsonl`).

## Limitations

- Reference is optical, not field data; it can mislabel turbid water or wet soil and is limited
  to cloud-free days, which are rare at flood peak.
- Trained and tested only around Ghatal; accuracy elsewhere in Paschim Medinipur is unmeasured.
- Harvested or ploughed paddy can look like new water on radar (seen on 2026-10-25).
- `flood_rf_20261029T163636Z.json` is an earlier run of Run 1 with the same settings, superseded
  by `flood_rf_20261029T164353Z.json`, which produced the saved model.
