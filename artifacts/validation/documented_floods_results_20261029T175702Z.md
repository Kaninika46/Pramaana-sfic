# Documented-flood check (Ahammad et al. 2026) — results

Run 2026-10-29T17:57Z · protocol `documented_floods_protocol.json` (written before the run) ·
raw rows `documented_floods_results_20261029T175702Z.json` · model files unchanged (fingerprints matched) ·
model used for every row: random forest VV+VH (`pramaana-flood-rf-0.1.0`). Read-only; no app code changed.

## Pre-registered criteria

| Criterion | Result | Required | Outcome |
|---|---|---|---|
| C1 Flood detected at flood-zone points, 2017/2021/2023/2024 | 14 / 30 = 46.7 % | ≥ 50 % | **FAIL** |
| C2 No flood detected on dry years (all points) | 34 / 40 = 85.0 % | ≥ 90 % | **FAIL** |
| C3 No flood detected at high-ground points, flood years | 23 / 23 = 100 % | ≥ 80 % | PASS |
| 2016 (no criterion) flood-zone detection | 3 / 6 = 50 % | — | — |

"Detected" = flood ≥ 20 % of the 250 m area around a point. 1 of 100 checks had no data
(2016-08-23 HG3: no valid VV pixels) and is excluded from C3's denominator.

## Flood % per point and date

| Date | Kind | FZ1 | FZ2 | FZ3 | FZ4 | FZ5 | FZ6 | HG1 | HG2 | HG3 | HG4 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2016-08-23 | flood | 33.5 | 5.6 | 56.3 | 7.4 | 29.8 | 10.1 | 0.0 | 0.2 | no data | 1.0 |
| 2017-07-25 | flood | 32.8 | 50.1 | 39.5 | 76.6 | 44.3 | 20.8 | 0.0 | 7.0 | 4.6 | 0.9 |
| 2021-07-28 | flood | 8.3 | 52.4 | 0.7 | 76.5 | 19.1 | 9.2 | 1.8 | 12.8 | 6.9 | 1.3 |
| 2021-08-06 | flood | 27.9 | 49.1 | 74.2 | 80.6 | 51.1 | 8.6 | 1.2 | 4.1 | 0.3 | 1.2 |
| 2023-10-07 | flood | 10.0 | 3.9 | 12.8 | 0.8 | 14.4 | 8.6 | 0.0 | 0.1 | 0.0 | 0.3 |
| 2024-09-19 | flood | 12.0 | 4.3 | 79.0 | 0.7 | 8.1 | 9.8 | 0.2 | 0.6 | 0.0 | 0.8 |
| 2018-09-03 | dry | 5.7 | 2.8 | **50.0** | 2.6 | 0.0 | 7.9 | 0.2 | 0.0 | 0.0 | 1.5 |
| 2019-09-01 | dry | **28.7** | 14.9 | **26.8** | 9.0 | 1.7 | 10.0 | 0.0 | 0.2 | 0.0 | 1.0 |
| 2020-09-04 | dry | 0.9 | 2.1 | 0.2 | 2.4 | 0.8 | 8.1 | 0.0 | 0.4 | 0.0 | 0.8 |
| 2022-09-06 | dry | 2.9 | **22.2** | **29.2** | **27.9** | 0.1 | 8.7 | 0.0 | 0.2 | 0.0 | 0.7 |

Bold = dry-year false alarm under the 20 % rule (6 of 40).

## Notes (written after seeing results; criteria and settings were not changed)

- All 6 dry-year false alarms are at low-lying flood-zone points; none on high ground.
  The paper's "dry" means river gauges stayed below danger level. Local rain-fed
  waterlogging in September paddy may still occur. Whether these were real water is
  unverified; a Sentinel-2 check of those six cases would settle it.
- Flood-zone points come from a terrain rule (HAND ≤ 2 m), not from the paper's mapped
  extent. The paper maps only 66–156 km² of 962 km² (7–16 %) as flooded even in big
  years, so not every low-lying point is expected to flood on every date. C1 therefore
  tests overlap with a terrain proxy, not with the paper's flood map.
- 2023-10-07 and 2024-09-19, the paper's two largest events, show the weakest point
  detection (1 of 12 flood-zone point-dates ≥ 20 %). This is not explained by the data
  above and should be checked against the paper's maps (supplementary material).
- FZ4 has high uncertain shares (33–68 %) on several dates; the model often abstains there.
