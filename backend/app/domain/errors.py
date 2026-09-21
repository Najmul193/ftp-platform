"""Domain-level errors.

These carry a machine-readable `code` matching the validation rule catalogue in
the system plan (§8.3), so an exception can be turned into an exception row
without a lookup table.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base for every error raised by the pure domain layer."""

    code: str = "E000"

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.code}] {self.message}"


class ValidationError(DomainError):
    """A record failed a validation rule."""

    def __init__(self, code: str, message: str, *, field: str | None = None) -> None:
        super().__init__(message, field=field)
        self.code = code


class ConfigMissingError(DomainError):
    """No approved rate configuration resolves for a product on a date.

    Raised rather than defaulting to zero. Silently treating a missing benchmark
    as 0 is defect L1 of the legacy workbook and inverts the sign of the spread.
    """

    code = "V006"

    def __init__(self, product_code: str, business_date: object, component: str) -> None:
        super().__init__(
            f"No approved {component} resolves for product {product_code!r} "
            f"on {business_date}",
            field=component,
        )
        self.product_code = product_code
        self.business_date = business_date
        self.component = component
