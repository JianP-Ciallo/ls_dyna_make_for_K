"""Public exception hierarchy for assessment contract and schema failures."""


class AssessmentError(Exception):
    """Base class for errors intentionally exposed by the package."""


class ContractError(AssessmentError, ValueError):
    """Raised when input violates a closed public contract."""


class UnsupportedSchemaError(ContractError):
    """Raised when a document uses a schema version this package cannot read."""
