# Pramaana flood model validation

Generated 2026-10-29T15:41:57Z · model pramaana-flood-0.3.0

Region: 22.6654, 87.7218 (radius 15000 m)  
Pairs used: 12 · samples: 24000 (calibration 13981, held-out test 10019)

Reference: cloud-free Sentinel-2 MNDWI (independent optical proxy, not field survey). Samples are class-balanced, so overall accuracy is not area-weighted.

## Held-out test accuracy

| Model | Coverage | Overall acc. | Flood precision | Flood recall | Flood F1 | Kappa | F1 if abstentions = errors |
|---|---|---|---|---|---|---|---|
| Legacy rule (-18 dB fixed) | 92.8% | 58.6% | 100.0% | 6.4% | 12.0% | 0.070 | 10.3% |
| v0.3 default (uncalibrated) | 88.2% | 60.1% | 100.0% | 9.4% | 17.2% | 0.104 | 13.5% |
| v0.3 calibrated | 94.9% | 60.9% | 97.6% | 18.8% | 31.6% | 0.190 | 28.9% |

## Calibrated parameters

```json
{
  "threshold_mode": "otsu",
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
| 2023-09-01 | 2023-09-01 | 12 ASCENDING | 100.0% | -18.0 dB (fixed) | 1000 / 1000 |
| 2021-11-25 | 2021-11-25 | 48 DESCENDING | 100.0% | -18.0 dB (fixed) | 1000 / 1000 |
| 2023-10-31 | 2023-10-31 | 12 ASCENDING | 98.0% | -18.0 dB (fixed) | 1000 / 1000 |
| 2021-11-10 | 2021-11-10 | 12 ASCENDING | 97.8% | -18.0 dB (fixed) | 1000 / 1000 |
| 2024-11-09 | 2024-11-09 | 48 DESCENDING | 93.6% | -18.0 dB (fixed) | 1000 / 1000 |
| 2023-11-05 | 2023-11-05 | 85 ASCENDING | 81.0% | -18.0 dB (fixed) | 1000 / 1000 |
| 2024-10-30 | 2024-10-30 | 85 ASCENDING | 56.8% | -16.8 dB (otsu) | 1000 / 1000 |
| 2023-07-18 | 2023-07-18 | 48 DESCENDING | 42.4% | -18.0 dB (fixed) | 1000 / 1000 |
| 2023-09-16 | 2023-09-16 | 48 DESCENDING | 37.8% | -18.0 dB (fixed) | 1000 / 1000 |
| 2021-07-13 | 2021-07-13 | 12 ASCENDING | 37.8% | -18.0 dB (fixed) | 1000 / 1000 |
| 2024-11-18 | 2024-11-19 | 12 ASCENDING | 100.0% | -18.0 dB (fixed) | 1000 / 1000 |
| 2023-11-24 | 2023-11-25 | 12 ASCENDING | 100.0% | -18.0 dB (fixed) | 1000 / 1000 |

## Limitations

- Reference is Sentinel-2 optical water, not field observation; it misses water under crop canopy and can mislabel turbid floodwater or wet soil.
- Sentinel-1 and Sentinel-2 passes can differ by up to the stated gap; water levels change.
- Samples are class-balanced; real-world flood prevalence differs, so precision on actual claims may be lower than shown.
- Pairs are limited to dates with cloud-free optical data, which are rare at flood peak.
- Accuracy is specific to this region and period; re-validate before use elsewhere.
