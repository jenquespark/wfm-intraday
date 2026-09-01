"""Legacy import shim — all models now live in ``reforecast.domain.models``.

This file is kept so existing imports from ``reforecast.models`` continue to
work.  New code should import from ``reforecast.domain.models`` directly.
"""

from reforecast.domain.models import (  # noqa: F401
    AccuracyMetrics,
    ACTUALS_COLUMNS,
    AnalysisResult,
    BASE_KEY_COLUMNS,
    FORECAST_COLUMNS,
    IntervalRecord,
    ReconciliationReport,
    RedistributionRecommendation,
    ReforecastResult,
    SCHEDULE_COLUMNS,
    StaffingGap,
    StaffingRequirement,
    validate_columns,
)