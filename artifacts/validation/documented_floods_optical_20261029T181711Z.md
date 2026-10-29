# Documented-flood check — Sentinel-2 follow-up and paper supplement

Read-only. Rule fixed in `doc_flood_optical_check.py` before running. Raw rows:
`documented_floods_optical_20261029T181711Z.json`. The pass/fail results in
`documented_floods_results_20261029T175702Z.md` are unchanged; this file only explains them.

## A. The 6 dry-year false alarms

| Date | Point | Model flood % | Sentinel-2 within ±3 days | Verdict |
|---|---|---|---|---|
| 2018-09-03 | FZ3 | 50.0 | none | no clear view |
| 2019-09-01 | FZ1 | 28.7 | 2019-09-02, but no flood pixel visible through cloud | no clear view |
| 2019-09-01 | FZ3 | 26.8 | 2019-09-02, 5 flood pixels visible (2 dry, 0 water) | no clear view (< 100 px) |
| 2022-09-06 | FZ2 | 22.2 | 2022-09-06, fully clouded | no clear view |
| 2022-09-06 | FZ3 | 29.2 | 2022-09-06, fully clouded | no clear view |
| 2022-09-06 | FZ4 | 27.9 | 2022-09-06, fully clouded | no clear view |

**Unresolved.** September cloud hid every case; none could be confirmed as water or as a false alarm.

## B. Weak detections in the paper's largest floods (flood-zone points)

| Date | Point | Model flood % (whole area) | Optical water % (clear part) | Model flood % (same clear part) | Verdict |
|---|---|---|---|---|---|
| 2024-09-19 | FZ1 | 12.0 | 3.0 | 12.0 | agrees |
| 2024-09-19 | FZ2 | 4.3 | 4.2 | 4.3 | agrees |
| 2024-09-19 | FZ3 | 79.0 | 78.7 | 79.0 | agrees |
| 2024-09-19 | FZ4 | 0.7 | 0.8 | 0.7 | agrees |
| 2024-09-19 | FZ5 | 8.1 | 6.2 | 6.3 | agrees |
| 2024-09-19 | FZ6 | 9.8 | — | — | no clear view |
| 2023-10-07 | FZ1 | 10.0 | 0.0 | 0.1 | agrees |
| 2023-10-07 | FZ3 | 12.8 | 0.0 | 8.0 | agrees |
| 2023-10-07 | FZ5 | 14.4 | 0.0 | 3.8 | agrees |
| 2023-10-07 | FZ2, FZ4, FZ6 | 3.9 / 0.8 / 8.6 | — | — | no clear view |

Optical scenes: 2024-09-20 (one day after the radar pass) and 2023-10-06 (one day before).
In every case with a clear view (8 of 12), the model agrees with Sentinel-2. The 2024 rows
match especially closely: FZ3 shows 79.0 % model flood against 78.7 % optical water. The low
2023/2024 detection rates in criterion C1 come from where the points lie: those fields were
not under water on those dates. The model did not miss water that was there.

## Paper supplementary material (ESM1, Springer)

- Fig. I gives the paper's Otsu thresholds, applied to **VV change (post − pre, dB)**:
  **−4.11 dB (2023)** and **−6.48 dB (2024)**. These are change thresholds, not absolute VV;
  the main text's "−15 to −17 dB" describes water backscatter in general.
- Fig. II shows Otsu flood maps for 2016–2024 as images without coordinates, so they cannot be
  scored pixel by pixel. By eye, 2023/2024 flooding lies in a band along the subdivision's
  south-western (Silai) and eastern (Rupnarayan) edges. FZ3 (87.796 E, 22.708 N) is the only
  flood-zone point near that band. This is a visual reading, not a measurement.

## Implication for the pre-registered criteria

C1 failed mainly because the terrain rule placed most flood-zone points outside the areas that
flooded on those dates, as optical data shows for 2024 and 2023. A fair re-test needs points
chosen from the paper's mapped flood extent (georeferenced) or from an independent map, fixed
before running. C2 (dry-year false alarms) remains open: the 6 cases could not be verified.
