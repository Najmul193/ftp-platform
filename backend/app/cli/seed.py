"""Seed reference data and the configuration matching FTP1.xlsm.

Idempotent: safe to re-run. Run with

    python -m app.cli.seed

The organisation seeded here follows the national structure of Bangladesh:
8 divisions and 64 districts. Branches come from branch_mapping.csv (the bank's
70 branches) and products from PRODUCTS below (the bank's 20 products, from the
Product Master of its one-day position file). Rows that already exist are never
changed, so re-running on a live database only fills in what is missing.
"""

from __future__ import annotations

import csv
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.db import session_scope
from app.core.permissions import PERMISSIONS, ROLES
from app.core.config import settings
from app.core.security import hash_password
from app.domain.types import BranchCategory, LiabilityNature, ScopeLevel, Side
from app.models import (
    Branch, ColumnMappingProfile, District, Division, GlobalRateConfig,
    Permission, Product, ProductRateConfig, Role, RolePermission, SourceSystem,
    SystemSetting, User, UserRole,
)

EFFECTIVE_FROM = date(2026, 1, 1)

#: Bootstrap credentials. The admin account is flagged `must_change_password`,
#: so the first sign-in has to replace it. The demo accounts exist only to make
#: scope enforcement visible and are not created when ENVIRONMENT=production.
DEFAULT_ADMIN_PASSWORD = "ChangeMe!2026"
ADMIN_PASSWORD = os.environ.get("FTP_ADMIN_PASSWORD") or DEFAULT_ADMIN_PASSWORD
DEMO_PASSWORD = "Passw0rd!2026x"

#: The organisation hierarchy lives in editable CSVs rather than in code, so the
#: bank can drop in its real divisions, districts and branches without a
#: deployment. Comment lines start "#".
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DIVISIONS_CSV = DATA_DIR / "divisions.csv"
DISTRICTS_CSV = DATA_DIR / "districts.csv"
BRANCH_MAPPING_CSV = DATA_DIR / "branch_mapping.csv"


def load_csv(path: Path) -> list[dict[str, str]]:
    """Read a seed CSV, skipping comment lines."""
    if not path.exists():
        raise FileNotFoundError(f"seed data not found at {path}")
    with path.open() as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    return list(csv.DictReader(lines))

# Product codes are exactly the strings the bank feed carries. Each carries its
# own benchmark, liquidity cost and other cost, as the bank's Product Master does.
# (code, short name, side, liability nature, benchmark, liquidity, other, details)
PRODUCTS = [
    ("CAIBC", "CURRENT ACCOUNT", Side.LIABILITY, LiabilityNature.DEMAND,
     "4.00", "0.15", "0.05", "CURRENT ACCOUNT"),
    ("CDIBC", "CURRENT DEPOSIT - CORPORATE", Side.LIABILITY, LiabilityNature.DEMAND,
     "2.00", "0.15", "0.05", "CURRENT DEPOSIT - CORPORATE"),
    ("DPSCH", "DEPOSIT PENSION SCHEME (DPS)", Side.LIABILITY, LiabilityNature.TIME,
     "8.50", "0.30", "0.05", "DEPOSIT PENSION SCHEME (DPS)"),
    ("SVSND", "SAVINGS ACCOUNT - STANDARD", Side.LIABILITY, LiabilityNature.DEMAND,
     "3.80", "0.25", "0.05", "SAVINGS ACCOUNT - STANDARD"),
    ("SVSND2", "SPECIAL SAVINGS (NOTICE)", Side.LIABILITY, LiabilityNature.DEMAND,
     "3.60", "0.25", "0.05", "SPECIAL SAVINGS (NOTICE)"),
    ("SVSPR", "SAVINGS ACCOUNT - PREMIUM", Side.LIABILITY, LiabilityNature.DEMAND,
     "4.50", "0.25", "0.05", "SAVINGS ACCOUNT - PREMIUM"),
    ("TDR03", "TERM DEPOSIT - 3 MONTHS", Side.LIABILITY, LiabilityNature.TIME,
     "7.50", "0.30", "0.05", "TERM DEPOSIT - 3 MONTHS"),
    ("TDR06", "TERM DEPOSIT - 6 MONTHS", Side.LIABILITY, LiabilityNature.TIME,
     "8.00", "0.30", "0.05", "TERM DEPOSIT - 6 MONTHS"),
    ("TDR12", "TERM DEPOSIT - 1 YEAR", Side.LIABILITY, LiabilityNature.TIME,
     "8.50", "0.35", "0.05", "TERM DEPOSIT - 1 YEAR"),
    ("TDR36", "TERM DEPOSIT - 3 YEARS", Side.LIABILITY, LiabilityNature.TIME,
     "9.20", "0.35", "0.05", "TERM DEPOSIT - 3 YEARS"),
    ("6101", "CORPORATE TIME LOAN REVOLVING", Side.ASSET, None,
     "8.00", "0.30", "0.05", "CORPORATE TIME LOAN REVOLVING"),
    ("6102", "TERM LOAN", Side.ASSET, None,
     "8.20", "0.30", "0.05", "TERM LOAN"),
    ("6312", "SME TIME LOAN REVOLVING", Side.ASSET, None,
     "8.30", "0.30", "0.05", "SME TIME LOAN REVOLVING"),
    ("6313", "TERM LOAN - SME", Side.ASSET, None,
     "8.50", "0.30", "0.05", "TERM LOAN - SME"),
    ("CARLN", "AUTO LOAN", Side.ASSET, None,
     "7.80", "0.30", "0.08", "AUTO LOAN"),
    ("CCLN1", "CONSUMER CREDIT - PERSONAL LOAN", Side.ASSET, None,
     "9.00", "0.35", "0.10", "CONSUMER CREDIT - PERSONAL LOAN"),
    ("COROD", "CORPORATE OVERDRAFT", Side.ASSET, None,
     "8.60", "0.35", "0.05", "CORPORATE OVERDRAFT"),
    ("HMLN5", "HOME LOAN - 5 YEARS", Side.ASSET, None,
     "7.50", "0.30", "0.05", "HOME LOAN - 5 YEARS"),
    ("LN01", "LOAN AGAINST TRUST RECEIPT (LATR)", Side.ASSET, None,
     "7.80", "0.30", "0.05", "LOAN AGAINST TRUST RECEIPT (LATR)"),
    ("MTR1", "MURABAHA TRUST RECEIPT", Side.ASSET, None,
     "8.00", "0.30", "0.05", "MURABAHA TRUST RECEIPT"),
]

def _get_or_create(s, model, defaults=None, **lookup):
    obj = s.scalar(select(model).filter_by(**lookup))
    if obj:
        return obj, False
    obj = model(**lookup, **(defaults or {}))
    s.add(obj)
    s.flush()
    return obj, True


def seed() -> None:
    with session_scope() as s:
        # --- permissions and roles ------------------------------------- #
        perms: dict[str, Permission] = {}
        for code, (module, desc) in PERMISSIONS.items():
            perms[code], _ = _get_or_create(
                s, Permission, {"module": module, "description": desc}, code=code
            )

        for code, spec in ROLES.items():
            role, _ = _get_or_create(
                s, Role,
                {"name": spec["name"], "description": spec.get("description"),
                 "is_admin": spec.get("is_admin", False)},
                code=code,
            )
            existing = {
                rp.permission_id
                for rp in s.scalars(select(RolePermission).filter_by(role_id=role.id))
            }
            for pcode in spec["permissions"]:
                pid = perms[pcode].id
                if pid not in existing:
                    s.add(RolePermission(role_id=role.id, permission_id=pid))

        # --- organisation, driven by the editable CSVs --------------------- #
        divs: dict[str, Division] = {}
        dists: dict[str, District] = {}

        for row in load_csv(DIVISIONS_CSV):
            dv = row["division_code"].strip()
            divs[dv], _ = _get_or_create(
                s, Division, {"name": row["division_name"].strip()}, code=dv
            )

        for row in load_csv(DISTRICTS_CSV):
            dt = row["district_code"].strip()
            dists[dt], _ = _get_or_create(
                s, District,
                {"name": row["district_name"].strip(),
                 "division_id": divs[row["division_code"].strip()].id},
                code=dt,
            )

        for row in load_csv(BRANCH_MAPPING_CSV):
            opened = row.get("opened_on", "").strip()
            _get_or_create(
                s, Branch,
                {"branch_name": row["branch_name"].strip(),
                 "district_id": dists[row["district_code"].strip()].id,
                 "category": BranchCategory(row["category"].strip()),
                 "opened_on": date.fromisoformat(opened) if opened else None},
                branch_code=row["branch_code"].strip(),
            )

        # --- products ------------------------------------------------------ #
        products = {}
        for code, short, side, nature, _bm, _liq, _oth, details in PRODUCTS:
            products[code], _ = _get_or_create(
                s, Product,
                {"short_name": short, "side": side, "liability_nature": nature,
                 "details": details},
                product_code=code,
            )

        # --- rate configuration -------------------------------------------- #
        # benchmark_rate is deliberately NULL. A product without an override is
        # then a hard ConfigMissingError rather than a silent zero -- the fix
        # for the workbook's most dangerous defect.
        if not s.scalar(select(GlobalRateConfig).filter_by(version=1)):
            s.add(GlobalRateConfig(
                version=1,
                benchmark_rate=None,
                liquidity_cost=Decimal("0.30"),
                other_cost=Decimal("0.05"),
                effective_from=EFFECTIVE_FROM,
                status="APPROVED",
                note="Initial configuration.",
            ))

        for code, _short, _side, _nature, benchmark, liquidity, other, _details in PRODUCTS:
            pid = products[code].id
            if not s.scalar(select(ProductRateConfig).filter_by(product_id=pid, version=1)):
                s.add(ProductRateConfig(
                    product_id=pid,
                    version=1,
                    benchmark_rate=Decimal(benchmark),
                    liquidity_cost=Decimal(liquidity),
                    other_cost=Decimal(other),
                    effective_from=EFFECTIVE_FROM,
                    status="APPROVED",
                    note="Seeded from the bank's Product Master.",
                ))

        # --- ingestion configuration ---------------------------------------- #
        src, _ = _get_or_create(
            s, SourceSystem,
            {"name": "Excel Upload", "adapter_type": "EXCEL"},
            code="EXCEL_UPLOAD",
        )
        _get_or_create(
            s, ColumnMappingProfile,
            {"source_system_id": src.id,
             "mapping": {"profile": "LEGACY_WORKBOOK_MAPPING"}},
            name="Legacy FTP Workbook (FTP1.xlsm)", version=1,
        )

        # --- operational settings --------------------------------------------- #
        for key, value, desc in [
            ("roi_band", {"min": "0", "max": "25"}, "V012 warning band for ROI"),
            ("interest_tolerance",
             {"absolute_floor": "0.01", "relative_bps": "1"},
             "V013 reconciliation tolerance"),
            ("balance_change_pct", {"value": "50"}, "V016 day-on-day move threshold"),
            ("branch_count_tolerance_pct", {"value": "10"}, "V017 row-count threshold"),
        ]:
            _get_or_create(s, SystemSetting, {"value": value, "description": desc}, key=key)

        # --- demo accounts, one per scope level -------------------------------- #
        # Their whole purpose is to make scope enforcement visible: sign in as
        # each and the same dashboard returns a different slice. They are
        # created only outside production.
        def make_user(username, full_name, level, scope_id, roles, password):
            if s.scalar(select(User).filter_by(username=username)):
                return
            u = User(
                username=username, full_name=full_name,
                password_hash=hash_password(password),
                scope_level=level, scope_id=scope_id,
                must_change_password=False,
            )
            s.add(u)
            s.flush()
            for rcode in roles:
                role = s.scalar(select(Role).filter_by(code=rcode))
                if role:
                    s.add(UserRole(user_id=u.id, role_id=role.id))

        # --- bootstrap HO administrator ---------------------------------------- #
        admin = s.scalar(select(User).filter_by(username="admin"))
        if not admin:
            # Checked here, not at import: this is the only moment the password
            # is used. A deployment that has already bootstrapped re-runs this
            # seed on every boot and must not need the variable still to be
            # present -- withdrawing it once the account exists is the correct
            # end state, not a misconfiguration.
            if settings.is_production and ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD:
                raise SystemExit(
                    "refusing to create the admin account: set "
                    "FTP_ADMIN_PASSWORD when ENVIRONMENT=production. The "
                    "fallback is published in this file, so using it on a "
                    "reachable deployment is a live exposure."
                )
            admin = User(
                username="admin",
                full_name="HO Administrator",
                email="admin@bank.local",
                password_hash=hash_password(ADMIN_PASSWORD),
                scope_level=ScopeLevel.HO,
                scope_id=None,
                must_change_password=True,
            )
            s.add(admin)
            s.flush()
            for rcode in ("ADMIN", "FTP_MANAGER", "DATA_OPERATOR", "ANALYST"):
                role = s.scalar(select(Role).filter_by(code=rcode))
                s.add(UserRole(user_id=admin.id, role_id=role.id))

        if not settings.is_production:
            first_branch = s.scalar(
                select(Branch).order_by(Branch.branch_code).limit(1)
            )
            first_district = (
                s.get(District, first_branch.district_id) if first_branch else None
            )
            first_division = s.scalar(
                select(Division).order_by(Division.code).limit(1)
            )
            make_user("operator", "Data Operator", ScopeLevel.HO, None,
                      ("DATA_OPERATOR",), DEMO_PASSWORD)
            if first_division:
                make_user("division_user", f"{first_division.name} user",
                          ScopeLevel.DIVISION, first_division.id,
                          ("ANALYST",), DEMO_PASSWORD)
            if first_district:
                make_user("district_user", f"{first_district.name} district user",
                          ScopeLevel.DISTRICT, first_district.id,
                          ("ANALYST",), DEMO_PASSWORD)
            if first_branch:
                make_user("branch_user",
                          f"Branch {first_branch.branch_code} user",
                          ScopeLevel.BRANCH, first_branch.id,
                          ("VIEWER",), DEMO_PASSWORD)

    print("seed complete")


if __name__ == "__main__":
    seed()
