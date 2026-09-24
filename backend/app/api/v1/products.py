"""Product master and effective rate preview."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DbDep, UserDep, require
from app.api.schemas import ProductOut, ProductRatesOut
from app.domain.errors import ConfigMissingError
from app.domain.types import LiabilityNature, Side
from app.models import Product
from app.repositories.rates import RateBook
from app.services.products import ProductError, ProductInUse, ProductService

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


class ProductCreate(BaseModel):
    product_code: str = Field(min_length=1, max_length=40)
    short_name: str = Field(min_length=1, max_length=60)
    side: Side
    benchmark_rate: Decimal | None = None
    liability_nature: LiabilityNature | None = None
    details: str | None = None
    liquidity_cost: Decimal | None = None
    other_cost: Decimal | None = None
    effective_from: date | None = None


class ProductUpdate(BaseModel):
    short_name: str | None = None
    details: str | None = None
    liability_nature: LiabilityNature | None = None
    is_active: bool | None = None


class RateUpdate(BaseModel):
    benchmark_rate: Decimal
    liquidity_cost: Decimal | None = None
    other_cost: Decimal | None = None
    effective_from: date | None = None
    note: str | None = Field(default=None, max_length=500)


class ProductRateVersionOut(BaseModel):
    product_code: str
    short_name: str
    version: int
    benchmark_rate: Decimal | None
    #: None means the component inherits the global default.
    liquidity_cost: Decimal | None
    other_cost: Decimal | None
    effective_from: date
    effective_to: date | None
    status: str
    changed_by: str | None
    changed_at: datetime | None
    note: str | None
    rows_priced: int


def _svc(db, user: UserDep) -> ProductService:
    return ProductService(db, actor_id=user.id, actor_username=user.username)


@router.get("/rates/history", response_model=list[ProductRateVersionOut],
            dependencies=[Depends(require("CONFIG_RATE_VIEW"))])
def all_rate_history(db: DbDep, limit: int = 500):
    """Every product rate version, including superseded ones."""
    return ProductService(db).rate_history(limit=limit)


@router.get("/{product_code}/rates/history",
            response_model=list[ProductRateVersionOut],
            dependencies=[Depends(require("CONFIG_RATE_VIEW"))])
def product_rate_history(product_code: str, db: DbDep, limit: int = 500):
    """One product's rate versions, newest first."""
    try:
        return ProductService(db).rate_history(product_code, limit=limit)
    except ProductError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require("MASTER_PRODUCT_EDIT"))])
def create_product(body: ProductCreate, db: DbDep, user: UserDep):
    """Register a product, with the benchmark that makes it priceable.

    Supplying the benchmark here matters: a product that exists but has no
    resolvable rate passes the "product exists" check and then fails on rate
    resolution, which presents as an unrelated problem.
    """
    try:
        return _svc(db, user).create(**body.model_dump())
    except ProductError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.patch("/{product_code}", response_model=ProductOut,
              dependencies=[Depends(require("MASTER_PRODUCT_EDIT"))])
def update_product(product_code: str, body: ProductUpdate, db: DbDep, user: UserDep):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no changes supplied")
    try:
        return _svc(db, user).update(product_code, **changes)
    except ProductError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/{product_code}/rates",
             dependencies=[Depends(require("CONFIG_RATE_EDIT"))])
def set_product_rate(product_code: str, body: RateUpdate, db: DbDep, user: UserDep):
    """Add a new effective-dated rate version, closing the open one."""
    try:
        cfg = _svc(db, user).set_rate(product_code, **body.model_dump())
    except ProductError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"product_code": product_code, "version": cfg.version,
            "benchmark_rate": cfg.benchmark_rate,
            "effective_from": cfg.effective_from}


@router.delete("/{product_code}",
               dependencies=[Depends(require("MASTER_PRODUCT_EDIT"))])
def delete_product(product_code: str, db: DbDep, user: UserDep):
    """Remove a product that has no history; otherwise 409 with the counts."""
    try:
        return _svc(db, user).delete(product_code)
    except ProductInUse as exc:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"message": str(exc), "counts": exc.counts,
                             "alternative": f"PATCH /products/{product_code} "
                                            "with is_active=false"}) from exc
    except ProductError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
