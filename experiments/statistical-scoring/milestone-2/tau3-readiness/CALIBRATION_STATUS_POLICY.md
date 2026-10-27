# Provisional Calibration Status Policy

## Decision

The first product procedure should not automatically blend equal and learned
weights. The Tau3 shrinkage experiment showed a continuous tradeoff:

- increasing the learned fraction reduced score variation across replay
  subsamples; and
- increasing the learned fraction consistently reduced correlation with the
  held-out Tau3 reward.

No tested fraction improved both measurements. A confidence-to-shrinkage
mapping would therefore encode a product preference that this experiment
cannot justify.

P0 should use a discrete policy:

1. use equal weights before calibration;
2. retain equal weights when calibration evidence is insufficient; and
3. apply the selected learned rule only after experiment-specific readiness
   criteria pass.

The equal-weight score should remain visible after calibration so customers can
inspect the effect of the learned profile.

## Scoring status

`CalibrationStatus` describes how the reported composite was produced.

| Status | Meaning | Applied weights |
|---|---|---|
| `uncalibrated` | No calibration fit or compatible profile is available. | Equal |
| `equal_weight_fallback` | A fit was attempted, but no usable reliability signal exists or the experiment-specific readiness criteria did not pass. | Equal |
| `calibrated` | A compatible profile passed the configured readiness criteria. | Profile weights |

The readiness criteria are configuration-specific. The Tau3 thresholds and
80-case budget are research findings, not library defaults.

`equal_weight_fallback` should eventually include a machine-readable reason,
such as:

- `no_reliability_signal`;
- `insufficient_evidence`;
- `profile_stale`; or
- `profile_incompatible`.

Adding a fallback reason is a follow-up API change. The current status value
already distinguishes a completed fallback fit from a cold start.

## Profile compatibility

Profile compatibility is separate from scoring status:

| Compatibility | Meaning | Behavior |
|---|---|---|
| `compatible` | The profile matches the dataset, evaluators, step sizes, schema, and algorithm runtime. | It may be applied if its readiness decision is still valid. |
| `stale` | The profile was created by an older supported algorithm. | Do not apply silently; recommend recalibration and use equal weighting. |
| `incompatible` | The profile or experiment configuration cannot be safely matched. | Reject the profile and use equal weighting only if the caller explicitly permits fallback. |

A profile must never be reported as `calibrated` merely because it can be
deserialized. Compatibility and statistical readiness must both pass.

## Customer-visible result

A calibrated report should expose:

- scoring status;
- weighting method;
- profile ID;
- learned-weight score;
- equal-weight baseline score;
- uncertainty interval; and
- fallback reason when equal weighting was retained.

This makes calibration inspectable without requiring customers to interpret
variance components or bootstrap distributions.

## Tau3 evidence

For the 80-case, 3-run, 2-replay design:

| Learned fraction | Score SD | Held-out correlation | Delta from equal |
|---:|---:|---:|---:|
| 0.00 | 0.0036 | 0.139 | 0.000 |
| 0.25 | 0.0033 | 0.133 | -0.006 |
| 0.50 | 0.0030 | 0.126 | -0.013 |
| 0.75 | 0.0028 | 0.117 | -0.022 |
| 1.00 | 0.0028 | 0.107 | -0.032 |

Full learned weighting remained inside the provisional -0.05 held-out
guardrail, but equal weighting had the strongest held-out association in every
complete-design subsample. This supports retaining the equal score as a
baseline, not selecting a universal shrinkage fraction.
