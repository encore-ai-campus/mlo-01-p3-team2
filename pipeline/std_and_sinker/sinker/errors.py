class DataError(Exception):
    """Safe data error: details contain field names, never source values."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ResultConflict(RuntimeError):
    """Same parser version produced a different result; preserve the old result."""
