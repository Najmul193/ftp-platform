"""Request and response models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.types import BranchCategory, ScopeLevel, Side


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ------------------------------------------------------------------ #

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool = False


class MeResponse(BaseModel):
    id: int
    username: str
    full_name: str
    scope_level: ScopeLevel
    scope_id: int | None
    scope_label: str
    roles: list[str]
    permissions: list[str]
    must_change_password: bool = False


# --- organisation ----------------------------------------------------------- #

class BranchOut(ORMModel):
    id: int
    branch_code: str
    branch_name: str
    division_id: int | None
    district_id: int
    category: BranchCategory
    opened_on: date | None
    is_active: bool
    udf: dict | None = None


class BranchCreate(BaseModel):
    branch_code: str = Field(min_length=1, max_length=10)
    branch_name: str = Field(min_length=1, max_length=120)
    district_code: str
    category: BranchCategory
    opened_on: date | None = None
    udf: dict | None = None


class BranchUpdate(BaseModel):
    branch_name: str | None = None
    district_code: str | None = None
    category: BranchCategory | None = None
    opened_on: date | None = None
    is_active: bool | None = None
    udf: dict | None = None


class BranchUsageOut(BaseModel):
    branch_code: str
    fact_rows: int
    bank_rows: int
    aggregate_rows: int
    deletable: bool
    note: str


class DivisionOut(ORMModel):
    id: int
    code: str
    name: str
    is_active: bool


class DistrictOut(ORMModel):
    id: int
    code: str
    name: str
    division_id: int
    is_active: bool


# --- product ----------------------------------------------------------------- #

class ProductOut(ORMModel):
    id: int
    product_code: str
    short_name: str
    details: str | None
    side: Side
    liability_nature: str | None
    is_active: bool
    udf: dict | None = None


class ProductRatesOut(BaseModel):
    product_code: str
    benchmark_rate: Decimal | None
    benchmark_source: str
    liquidity_cost: Decimal
    liquidity_source: str
    other_cost: Decimal
    other_source: str
    effective_on: date


# --- dashboard ---------------------------------------------------------------- #

class KpiResponse(BaseModel):
    asset_balance: Decimal
    liability_balance: Decimal
    total_balance: Decimal
    interest_receivable: Decimal
    interest_payable: Decimal
    asset_ftp_profit: Decimal
    liability_ftp_profit: Decimal
    net_ftp_profit: Decimal
    ftp_over_balance_pct: Decimal
    branch_count: int
    product_count: int
    account_count: int
    day_count: int
    negative_ftp_count: int
    as_of: date | None = None
    stale: bool = False


class SeriesPoint(BaseModel):
    label: str
    key: str | int | None = None
    #: The bare code behind the label, where the level has one. `label` is
    #: "<code> <name>", which is what a table wants; a chart axis has room for
    #: the code alone and nothing else.
    code: str | None = None
    #: The level above this one -- a district's division, a branch's district.
    parent_label: str | None = None
    asset_ftp_profit: Decimal = Decimal(0)
    liability_ftp_profit: Decimal = Decimal(0)
    net_ftp_profit: Decimal = Decimal(0)
    asset_balance: Decimal = Decimal(0)
    liability_balance: Decimal = Decimal(0)
    total_balance: Decimal = Decimal(0)
    account_count: int = 0
    negative_ftp_count: int = 0
    avg_ftp_rate: Decimal = Decimal(0)


class HeatCell(BaseModel):
    branch_code: str
    product_code: str
    net_ftp_profit: Decimal
    total_balance: Decimal


class AccountRow(BaseModel):
    business_date: date
    branch_code: str
    account_no: str
    product_code: str
    side: Side
    balance: Decimal
    normalized_roi: Decimal
    roi_source: str
    benchmark_rate: Decimal
    liquidity_cost: Decimal
    other_cost: Decimal
    ftp_rate: Decimal
    ftp_income: Decimal
    customer_interest: Decimal
    asset_ftp_profit: Decimal
    liability_ftp_profit: Decimal
    negative_ftp_flag: bool


class Page(BaseModel):
    items: list
    total: int
    limit: int
    offset: int


# --- ingestion ------------------------------------------------------------------ #

class UploadResult(BaseModel):
    batch_ref: str
    status: str
    total_rows: int
    accepted_rows: int
    warned_rows: int
    rejected_rows: int
    structural_rows: int
    business_dates: list[date] = []
    run_ref: str | None = None
    exceptions_by_rule: dict[str, int] = {}
    message: str | None = None


class BatchOut(ORMModel):
    id: int
    batch_ref: str
    business_date: date | None
    file_name: str
    status: str
    total_rows: int
    accepted_rows: int
    warned_rows: int
    rejected_rows: int
    is_current: bool
    supersedes_batch_id: int | None
    superseded_by_batch_id: int | None
    uploaded_at: datetime
    committed_at: datetime | None


class ExceptionOut(ORMModel):
    source_row_no: int | None
    origin: str | None
    severity: str
    rule_code: str
    field_name: str | None
    raw_value: str | None
    message: str
