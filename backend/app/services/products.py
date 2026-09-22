"""Product master maintenance (HO admin).

Creating a product is two things at once: the product itself, and the rate
configuration that lets it be priced. A product with no resolvable benchmark is
worse than no product at all -- its rows pass the "product exists" check and
then fail on rate resolution, which reads as a different problem entirely. So
`create` takes the benchmark and writes both, in one transaction.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.types import LiabilityNature, Side
from app.models import (
    BankDailyAccountData, FtpCalculationResult, Product, ProductRateConfig,
)
from app.services import audit
from app.services.config import GlobalConfigService


class ProductError(Exception):
    """Invalid product operation."""


class ProductInUse(ProductError):
    def __init__(self, code: str, counts: dict[str, int]) -> None:
        detail = ", ".join(f"{v:,} {k}" for k, v in counts.items() if v)
        super().__init__(
            f"product {code} cannot be deleted because it is referenced by "
            f"{detail}. Deactivate it instead to retain history."
        )
        self.counts = counts


def _snapshot(p: Product) -> dict[str, Any]:
    return {
        "product_code": p.product_code, "short_name": p.short_name,
        "details": p.details, "side": p.side.value if p.side else None,
        "liability_nature": p.liability_nature.value if p.liability_nature else None,
        "is_active": p.is_active, "udf": p.udf,
    }


class ProductService:
    def __init__(self, session: Session, *, actor_id: int | None = None,
                 actor_username: str | None = None) -> None:
        self.s = session
        self.actor_id = actor_id
        self.actor_username = actor_username

    def get(self, code: str) -> Product:
        p = self.s.scalar(select(Product).filter_by(product_code=code))
        if p is None:
            raise ProductError(f"product {code!r} does not exist")
        return p

    def usage(self, product: Product) -> dict[str, int]:
        return {
            "calculated fact rows": self.s.scalar(
                select(func.count()).select_from(FtpCalculationResult)
                .where(FtpCalculationResult.product_id == product.id)) or 0,
            "raw bank rows": self.s.scalar(
                select(func.count()).select_from(BankDailyAccountData)
                .where(BankDailyAccountData.product_code == product.product_code)) or 0,
        }

    def create(
        self, *, product_code: str, short_name: str, side: Side | str,
        benchmark_rate: Decimal | str | None = None,
        liability_nature: LiabilityNature | str | None = None,
        details: str | None = None,
        liquidity_cost: Decimal | str | None = None,
        other_cost: Decimal | str | None = None,
        effective_from: date | None = None,
        udf: dict | None = None,
    ) -> Product:
        code = product_code.strip()
        if not code:
            raise ProductError("product_code is required")
        if self.s.scalar(select(Product).filter_by(product_code=code)):
            raise ProductError(f"product {code!r} already exists")

        side = Side(side) if isinstance(side, str) else side
        if side is Side.LIABILITY:
            if liability_nature is None:
                raise ProductError(
                    "a liability product needs liability_nature (DEMAND or TIME)"
                )
            nature = (LiabilityNature(liability_nature)
                      if isinstance(liability_nature, str) else liability_nature)
        else:
            if liability_nature:
                raise ProductError("an asset product cannot have liability_nature")
            nature = None

        # A product benchmark always overrides the global one. Where the global
        # layer supplies none, the product's own is therefore the only source
        # and is mandatory -- checked here rather than left to fail at the
        # first calculation, which presents as an unrelated problem.
        if benchmark_rate is None:
            global_cfg = GlobalConfigService(self.s).in_force(
                effective_from or date.today())
            if global_cfg is None or global_cfg.benchmark_rate is None:
                raise ProductError(
                    "a benchmark rate is required: the global configuration "
                    "does not supply one, so this product would not be priceable"
                )

        product = Product(
            product_code=code, short_name=short_name.strip(), details=details,
            side=side, liability_nature=nature, udf=udf or {},
            created_by=self.actor_id,
        )
        self.s.add(product)
        self.s.flush()

        # Without a benchmark the product resolves to ConfigMissingError at
        # validation time, so the rate row is written with the product.
        if benchmark_rate is not None:
            self.s.add(ProductRateConfig(
                product_id=product.id, version=1,
                benchmark_rate=Decimal(str(benchmark_rate)),
                liquidity_cost=(Decimal(str(liquidity_cost))
                                if liquidity_cost is not None else None),
                other_cost=(Decimal(str(other_cost))
                            if other_cost is not None else None),
                effective_from=effective_from or date(2000, 1, 1),
                status="APPROVED",
                maker_id=self.actor_id,
                note="Created with the product.",
            ))
            self.s.flush()

        audit.record(
            self.s, action="CREATE", entity_type="product", entity_id=code,
            after={**_snapshot(product),
                   "benchmark_rate": str(benchmark_rate) if benchmark_rate else None},
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return product

    def update(self, code: str, **changes: Any) -> Product:
        product = self.get(code)
        before = _snapshot(product)

        for field in ("short_name", "details"):
            if field in changes and changes[field] is not None:
                setattr(product, field, changes[field])
        if "is_active" in changes:
            product.is_active = bool(changes["is_active"])
        if "udf" in changes:
            product.udf = changes["udf"]
        if "liability_nature" in changes and product.side is Side.LIABILITY:
            product.liability_nature = LiabilityNature(changes["liability_nature"])

        # `side` is immutable once priced: it decides the sign of the spread, so
        # flipping it would silently restate every figure the product appears in.
        if "side" in changes and changes["side"] and \
                Side(changes["side"]) is not product.side:
            if sum(self.usage(product).values()):
                raise ProductError(
                    "side cannot change once the product has history: it "
                    "determines the sign of the FTP spread"
                )
            product.side = Side(changes["side"])

        product.updated_by = self.actor_id
        self.s.flush()
        audit.record(
            self.s, action="UPDATE", entity_type="product", entity_id=code,
            before=before, after=_snapshot(product),
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return product

    def set_rate(self, code: str, *, benchmark_rate: Decimal | str,
                 liquidity_cost: Decimal | str | None = None,
                 other_cost: Decimal | str | None = None,
                 effective_from: date | None = None) -> ProductRateConfig:
        """Add a new effective-dated rate version, closing the previous one.

        Closing the open period rather than overwriting it is what keeps every
        historical figure explainable: the row that priced last month still
        points at the version that was in force then.
        """
        product = self.get(code)
        start = effective_from or date.today()

        current = self.s.scalar(
            select(ProductRateConfig)
            .where(ProductRateConfig.product_id == product.id)
            .where(ProductRateConfig.status == "APPROVED")
            .where(ProductRateConfig.effective_to.is_(None))
            .order_by(ProductRateConfig.version.desc())
        )
        version = 1
        if current:
            if current.effective_from >= start:
                raise ProductError(
                    f"a rate already applies from {current.effective_from}; "
                    f"the new one must start after that"
                )
            current.effective_to = start
            version = current.version + 1

        cfg = ProductRateConfig(
            product_id=product.id, version=version,
            benchmark_rate=Decimal(str(benchmark_rate)),
            liquidity_cost=(Decimal(str(liquidity_cost))
                            if liquidity_cost is not None else None),
            other_cost=(Decimal(str(other_cost)) if other_cost is not None else None),
            effective_from=start, status="APPROVED", maker_id=self.actor_id,
        )
        self.s.add(cfg)
        self.s.flush()
        audit.record(
            self.s, action="UPDATE", entity_type="product_rate_config",
            entity_id=f"{code}#v{version}",
            after={"benchmark_rate": str(benchmark_rate),
                   "effective_from": start.isoformat(), "version": version},
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return cfg

    def deactivate(self, code: str) -> Product:
        return self.update(code, is_active=False)

    def delete(self, code: str) -> dict:
        product = self.get(code)
        usage = self.usage(product)
        if sum(usage.values()):
            raise ProductInUse(code, usage)
        before = _snapshot(product)
        self.s.execute(
            ProductRateConfig.__table__.delete()
            .where(ProductRateConfig.product_id == product.id)
        )
        self.s.delete(product)
        self.s.flush()
        audit.record(
            self.s, action="DELETE", entity_type="product", entity_id=code,
            before=before,
            actor_user_id=self.actor_id, actor_username=self.actor_username,
        )
        return {"product_code": code, "deleted": True}
