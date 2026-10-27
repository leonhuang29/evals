# Tau3 Equal-to-Learned Shrinkage Comparison

**Complete cases:** 80  
**Agent runs:** 3  
**Judge replays:** 2  
**Subsamples per case count:** 100  
**Learned weighting method:** `inverse_sqrt_step`

`Learned fraction` is the confidence term in
`applied = (1 - confidence) * equal + confidence * learned`.

| Cases | Learned fraction | Score SD | Held-out correlation | Delta from equal | Beats equal | Within guardrail |
|---:|---:|---:|---:|---:|---:|---:|
| 12 | 0.00 | 0.0391 | 0.1453 | 0.0000 | 0.0% | 100.0% |
| 12 | 0.25 | 0.0384 | 0.1392 | -0.0061 | 36.0% | 99.0% |
| 12 | 0.50 | 0.0384 | 0.1304 | -0.0149 | 35.0% | 81.0% |
| 12 | 0.75 | 0.0390 | 0.1191 | -0.0263 | 36.0% | 68.0% |
| 12 | 1.00 | 0.0401 | 0.1059 | -0.0395 | 37.0% | 59.0% |
| 20 | 0.00 | 0.0270 | 0.1483 | 0.0000 | 0.0% | 100.0% |
| 20 | 0.25 | 0.0260 | 0.1436 | -0.0047 | 37.0% | 100.0% |
| 20 | 0.50 | 0.0256 | 0.1368 | -0.0115 | 33.0% | 91.0% |
| 20 | 0.75 | 0.0256 | 0.1278 | -0.0205 | 30.0% | 80.0% |
| 20 | 1.00 | 0.0262 | 0.1170 | -0.0313 | 27.0% | 68.0% |
| 40 | 0.00 | 0.0134 | 0.1337 | 0.0000 | 0.0% | 100.0% |
| 40 | 0.25 | 0.0131 | 0.1283 | -0.0054 | 27.0% | 100.0% |
| 40 | 0.50 | 0.0134 | 0.1214 | -0.0124 | 20.0% | 100.0% |
| 40 | 0.75 | 0.0143 | 0.1129 | -0.0208 | 18.0% | 90.0% |
| 40 | 1.00 | 0.0155 | 0.1031 | -0.0307 | 16.0% | 71.0% |
| 80 | 0.00 | 0.0036 | 0.1388 | 0.0000 | 0.0% | 100.0% |
| 80 | 0.25 | 0.0033 | 0.1330 | -0.0058 | 0.0% | 100.0% |
| 80 | 0.50 | 0.0030 | 0.1257 | -0.0130 | 0.0% | 100.0% |
| 80 | 0.75 | 0.0028 | 0.1171 | -0.0217 | 0.0% | 100.0% |
| 80 | 1.00 | 0.0028 | 0.1071 | -0.0317 | 0.0% | 100.0% |

## Interpretation

For the complete design, the learned fraction with the strongest mean held-out correlation was `0.00`. The largest learned fraction remaining within the provisional held-out guardrail for at least 95% of subsamples was `1.0`.

These values characterize the Tau3 experiment only. Held-out reward is used to compare the tradeoff, so the selected fraction must not be shipped as a universal default.
