# ID Front Field ROI A/B Report

This report contains aggregate accuracy and latency only. No document values are included.

| Configuration | Samples | Successful | Exact all-fields rate | P50 | P95 | Name ROI attempted/recovered | Birthday ROI attempted/recovered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| roi_off | 400 | 400 | 96.5% | 0.1777s | 0.3418s | 0/0 | 0/0 |

## roi_off Field Accuracy

| Field | Correct | Total | Accuracy |
| --- | ---: | ---: | ---: |
| name | 390 | 400 | 97.5% |
| gender | 400 | 400 | 100.0% |
| nation | 400 | 400 | 100.0% |
| birthday | 396 | 400 | 99.0% |
| address | 400 | 400 | 100.0% |
| id_number | 400 | 400 | 100.0% |
| roi_on | 400 | 400 | 96.5% | 0.1818s | 0.303s | 5/2 | 0/0 |

## roi_on Field Accuracy

| Field | Correct | Total | Accuracy |
| --- | ---: | ---: | ---: |
| name | 390 | 400 | 97.5% |
| gender | 400 | 400 | 100.0% |
| nation | 400 | 400 | 100.0% |
| birthday | 396 | 400 | 99.0% |
| address | 400 | 400 | 100.0% |
| id_number | 400 | 400 | 100.0% |
