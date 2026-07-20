class AnalyticalEngineError(Exception):
    status_code = 422


class InsufficientDataError(AnalyticalEngineError):
    pass


class MissingColumnError(AnalyticalEngineError):
    pass


class InvalidTargetError(AnalyticalEngineError):
    pass


class InvalidTimestampError(AnalyticalEngineError):
    pass


class MissingProbabilityError(AnalyticalEngineError):
    pass


class UnsupportedMetricError(AnalyticalEngineError):
    pass
