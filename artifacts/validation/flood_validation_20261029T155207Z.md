# Pramaana flood model validation

Generated 2026-10-29T15:52:07Z · model pramaana-flood-0.3.0

Region: 22.6654, 87.7218 (radius 15000 m)  
Pairs used: 24 · samples: 42317 (calibration 24871, held-out test 17446)

Reference: cloud-free Sentinel-2 MNDWI (independent optical proxy, not field survey). Samples are class-balanced, so overall accuracy is not area-weighted.

## Held-out test accuracy

| Model | Coverage | Overall acc. | Flood precision | Flood recall | Flood F1 | Kappa | F1 if abstentions = errors |
|---|---|---|---|---|---|---|---|
| Legacy rule (-18 dB fixed) | 94.5% | 64.8% | 100.0% | 5.4% | 10.3% | 0.067 | 8.9% |
| v0.3 default (uncalibrated) | 90.3% | 65.6% | 99.7% | 6.3% | 11.8% | 0.078 | 9.2% |
| v0.3 calibrated | 95.6% | 69.6% | 89.9% | 27.2% | 41.7% | 0.284 | 38.4% |

## Calibrated parameters

```json
{
  "threshold_mode": "fixed",
  "default_threshold_db": -14.0,
  "margin_db": 0.0,
  "change_db": 0.0,
  "otsu_min_db": -23.0,
  "otsu_max_db": -14.0,
  "otsu_min_separation_db": 3.0,
  "otsu_min_class_fraction": 0.02,
  "threshold_region_m": 5000,
  "permanent_water_occurrence": 80,
  "max_hand_m": 15.0,
  "max_slope_deg": 5.0
}
```

## Pairs

| S1 date | S2 date | Orbit | S2 clear | Threshold | Water / dry samples |
|---|---|---|---|---|---|
| 2019-11-21 | 2019-11-21 | 12 ASCENDING | 100.0% | -18.0 dB (fixed) | 1000 / 1000 |
| 2021-11-25 | 2021-11-25 | 48 DESCENDING | 100.0% | -18.0 dB (fixed) | 1000 / 1000 |
| 2023-09-01 | 2023-09-01 | 12 ASCENDING | 100.0% | -18.0 dB (fixed) | 1000 / 1000 |
| 2022-11-10 | 2022-11-10 | 85 ASCENDING | 99.3% | -18.0 dB (fixed) | 31 / 1000 |
| 2020-11-15 | 2020-11-15 | 12 ASCENDING | 99.2% | -18.0 dB (fixed) | 1000 / 1000 |
| 2023-10-31 | 2023-10-31 | 12 ASCENDING | 98.0% | -18.0 dB (fixed) | 463 / 1000 |
| 2021-11-10 | 2021-11-10 | 12 ASCENDING | 97.8% | -18.0 dB (fixed) | 187 / 1000 |
| 2022-11-05 | 2022-11-05 | 12 ASCENDING | 96.6% | -18.0 dB (fixed) | 924 / 1000 |
| 2024-11-09 | 2024-11-09 | 48 DESCENDING | 93.6% | -18.0 dB (fixed) | 354 / 1000 |
| 2023-11-05 | 2023-11-05 | 85 ASCENDING | 81.0% | -18.0 dB (fixed) | 1000 / 1000 |
| 2020-06-03 | 2020-06-03 | 48 DESCENDING | 74.3% | -18.0 dB (fixed) | 1000 / 1000 |
| 2022-11-20 | 2022-11-20 | 48 DESCENDING | 62.0% | -18.0 dB (fixed) | 1000 / 1000 |
| 2022-07-13 | 2022-07-13 | 85 ASCENDING | 57.6% | -18.0 dB (fixed) | 1000 / 1000 |
| 2024-10-30 | 2024-10-30 | 85 ASCENDING | 56.8% | -16.8 dB (otsu) | 1000 / 1000 |
| 2019-09-22 | 2019-09-22 | 12 ASCENDING | 52.8% | -18.0 dB (fixed) | 1000 / 1000 |
| 2023-07-18 | 2023-07-18 | 48 DESCENDING | 42.4% | -18.0 dB (fixed) | 1000 / 1000 |
| 2021-07-13 | 2021-07-13 | 12 ASCENDING | 37.8% | -18.0 dB (fixed) | 1000 / 1000 |
| 2023-09-16 | 2023-09-16 | 48 DESCENDING | 37.8% | -18.0 dB (fixed) | 1000 / 1000 |
| 2020-11-20 | 2020-11-20 | 85 ASCENDING | 36.2% | -18.0 dB (fixed) | 1000 / 1000 |
| 2023-11-24 | 2023-11-25 | 12 ASCENDING | 100.0% | -18.0 dB (fixed) | 1000 / 1000 |
| 2024-11-18 | 2024-11-19 | 12 ASCENDING | 100.0% | -18.0 dB (fixed) | 32 / 1000 |
| 2023-06-02 | 2023-06-03 | 85 ASCENDING | 99.9% | -18.0 dB (fixed) | 829 / 1000 |
| 2020-10-25 | 2020-10-26 | 48 DESCENDING | 99.4% | -18.0 dB (fixed) | 340 / 1000 |
| 2020-10-27 | 2020-10-26 | 85 ASCENDING | 99.4% | -18.0 dB (fixed) | 157 / 1000 |

## Limitations

- Reference is Sentinel-2 optical water, not field observation; it misses water under crop canopy and can mislabel turbid floodwater or wet soil.
- Sentinel-1 and Sentinel-2 passes can differ by up to the stated gap; water levels change.
- Samples are class-balanced; real-world flood prevalence differs, so precision on actual claims may be lower than shown.
- Pairs are limited to dates with cloud-free optical data, which are rare at flood peak.
- Accuracy is specific to this region and period; re-validate before use elsewhere.
