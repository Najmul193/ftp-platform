"""Product master and effective rate preview."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbDep, require
from app.api.schemas import ProductOut, ProductRatesOut
from app.domain.errors import ConfigMissingError
from app.models import Product
from app.repositories.rates import RateBook

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductOut],
            dependencies=[Depends(require("MASTER_PRODUCT_VIEW"))])
def list_products(db: DbDep, include_inactive: bool = False):
    stmt = select(Product).order_by(Product.product_code)
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    return list(db.scalars(stmt))


@router.get("/{product_code}/rates", response_model=ProductRatesOut,
            dependencies=[Depends(require("CONFIG_RATE_VIEW"))])
def effective_rates(product_code: str, db: DbDep, on: date | None = None):
    """Show what the engine would use, and which layer each component came from.

    This is the screen that makes the override model legible: a user can see at
    a glance that the benchmark is the product's own while liquidity is
    inherited from the global default.
    """
    on = on or date.today()
    try:
        resolved = RateBook(db, on).resolve(product_code)
    except ConfigMissingError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return ProductRatesOut(
        product_code=product_code,
        benchmark_rate=resolved.benchmark.value,
        benchmark_source=resolved.benchmark.source.value,
        liquidity_cost=resolved.liquidity.value,
        liquidity_source=resolved.liquidity.source.value,
        other_cost=resolved.other.value,
        other_source=resolved.other.source.value,
        effective_on=on,
    )
