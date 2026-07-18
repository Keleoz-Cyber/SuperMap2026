class GeoModelingError(Exception):
    pass


class BlockingValidationError(GeoModelingError):
    def __init__(self, message: str, issues=None):
        super().__init__(message)
        self.issues = list(issues or [])
