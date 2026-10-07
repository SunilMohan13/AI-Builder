"""Promotion thresholds shared by the legacy trainers and the APAC plugins.

A gate is not lowered to let a model pass (AGENTS.md).
"""

#: Minimum detection F1 before an anomaly detector may serve. A detector that
#: almost never fires has excellent precision and is still useless.
MIN_DETECTION_F1 = 0.30

#: A hazard classifier must rank hazardous hours better than simply reading
#: the current concentration, which is a strong 24-hour predictor on its own.
#: Expressed as a required PR-AUC margin over that baseline rather than an
#: absolute floor, because the achievable PR-AUC depends on the base rate.
MIN_HAZARD_PR_AUC_MARGIN = 0.05
#: An alerting model that fires on more than this fraction of quiet hours will
#: be ignored by operators regardless of its recall (LLD §45).
MAX_HAZARD_FALSE_ALERT_RATE = 0.10
