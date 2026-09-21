"""Rate resolution: global default with per-component product override.

Plan decision D3. Each of the three components -- benchmark, liquidity, other --
is resolved independently, so a product may override the benchmark while still
inheriting the global liquidity cost. That is exactly the shape of the legacy
workbook, where liquidity (0.30) and other (0.05) were uniform across all five
products and only the benchmark varied.

`None` on a product component means INHERIT. `Decimal("0")` means an explicit
zero and is honoured as an override. Keeping those distinct is what stops a
missing benchmark silently becoming a zero spread.

This module is pure: callers fetch the effective-dated config rows and pass them
in. Choosing *which* rows are effective for a date is a repository concern.
"""

from __future__ import annotations

from datetime import date

from app.domain.errors import ConfigMissingError
from app.domain.types import (
    GlobalRates,
    ProductRates,
    RateComponent,
    RateSource,
    ResolvedRates,
)

_COMPONENTS = ("benchmark_rate", "liquidity_cost", "other_cost")


def resolve_rates(
    product_code: str,
    business_date: date,
    global_rates: GlobalRates,
    product_rates: ProductRates | None = None,
) -> ResolvedRates:
    """Resolve the three rate components for a product on a business date.

    Args:
        product_code: Product being priced, used only for error messages.
        business_date: The business date, used only for error messages. The
            caller has already selected effective-dated rows for this date.
        global_rates: The approved global configuration in force.
        product_rates: The product's approved overrides, if any.

    Returns:
        Each component with its value, which layer supplied it, and the version
        of the configuration row that did. All three are persisted onto the fact
        row so a published number can be explained later.

    Raises:
        ConfigMissingError: A component resolves to neither an override nor a
            global default. Never defaults to zero -- see defect L1.
    """
    resolved: dict[str, RateComponent] = {}

    for component in _COMPONENTS:
        override = getattr(product_rates, component, None) if product_rates else None

        if override is not None:
            resolved[component] = RateComponent(
                value=override,
                source=RateSource.PRODUCT_OVERRIDE,
                config_version=product_rates.version,  # type: ignore[union-attr]
            )
            continue

        default = getattr(global_rates, component)
        if default is None:
            raise ConfigMissingError(product_code, business_date, component)

        resolved[component] = RateComponent(
            value=default,
            source=RateSource.GLOBAL_DEFAULT,
            config_version=global_rates.version,
        )

    return ResolvedRates(
        benchmark=resolved["benchmark_rate"],
        liquidity=resolved["liquidity_cost"],
        other=resolved["other_cost"],
    )
