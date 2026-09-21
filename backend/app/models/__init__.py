"""SQLAlchemy ORM models.

Import order matters for mapper configuration; importing this package registers
every model against the shared `Base.metadata`, which is what Alembic
autogenerate reflects against.
"""

from app.models.base import Base
from app.models.org import Division, District, Branch
from app.models.master import Product, UdfDefinition
from app.models.config import GlobalRateConfig, ProductRateConfig, SystemSetting
from app.models.security import (
    User, Role, Permission, RolePermission, UserRole, RefreshToken, LoginAudit,
)
from app.models.ingestion import (
    SourceSystem, ColumnMappingProfile, UploadBatch, StagingAccountData,
    BankDailyAccountData, UploadException,
)
from app.models.calculation import (
    CalculationRun, FtpCalculationResult,
    AggDailyBranch, AggDailyProduct, AggDailyBranchProduct,
    AggDailyDivision, AggDailyDistrict, AggDailyCategory,
)
from app.models.governance import AuditLog, ApprovalRequest, ReportDownload

__all__ = [
    "Base",
    "Division", "District", "Branch",
    "Product", "UdfDefinition",
    "GlobalRateConfig", "ProductRateConfig", "SystemSetting",
    "User", "Role", "Permission", "RolePermission", "UserRole",
    "RefreshToken", "LoginAudit",
    "SourceSystem", "ColumnMappingProfile", "UploadBatch", "StagingAccountData",
    "BankDailyAccountData", "UploadException",
    "CalculationRun", "FtpCalculationResult",
    "AggDailyBranch", "AggDailyProduct", "AggDailyBranchProduct",
    "AggDailyDivision", "AggDailyDistrict", "AggDailyCategory",
    "AuditLog", "ApprovalRequest", "ReportDownload",
]
