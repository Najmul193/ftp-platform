"""The permission catalogue and the role -> permission map (plan §5.3, §5.2)."""

from __future__ import annotations

PERMISSIONS: dict[str, tuple[str, str]] = {
    # code: (module, description)
    "MASTER_ORG_VIEW": ("master", "View divisions and districts"),
    "MASTER_ORG_EDIT": ("master", "Maintain divisions and districts"),
    "MASTER_BRANCH_VIEW": ("master", "View branch master"),
    "MASTER_BRANCH_EDIT": ("master", "Maintain branch master"),
    "MASTER_PRODUCT_VIEW": ("master", "View product master"),
    "MASTER_PRODUCT_EDIT": ("master", "Maintain product master"),
    "CONFIG_RATE_VIEW": ("config", "View rate configuration"),
    "CONFIG_RATE_EDIT": ("config", "Propose rate configuration changes"),
    "CONFIG_APPROVE": ("config", "Approve or reject pending changes"),
    "UPLOAD_VIEW": ("ingestion", "View uploads and exceptions"),
    "UPLOAD_CREATE": ("ingestion", "Upload a data file"),
    "UPLOAD_COMMIT": ("ingestion", "Commit a validated batch"),
    "CALC_RUN": ("calculation", "Run a calculation"),
    "CALC_RECALC_HISTORY": ("calculation", "Recalculate historical dates"),
    "DASH_VIEW": ("dashboard", "View dashboards"),
    "ACCOUNT_DRILLDOWN": ("dashboard", "Drill to account level"),
    "REPORT_VIEW": ("reports", "View reports"),
    "REPORT_EXPORT": ("reports", "Export reports"),
    "SCENARIO_VIEW": ("scenario", "View scenarios"),
    "SCENARIO_RUN": ("scenario", "Run a scenario simulation"),
    "USER_VIEW": ("admin", "View users"),
    "USER_CREATE": ("admin", "Create users at or below own scope"),
    "USER_EDIT": ("admin", "Edit users at or below own scope"),
    "USER_DISABLE": ("admin", "Disable users at or below own scope"),
    "ROLE_GRANT": ("admin", "Grant roles, limited to own permissions"),
    "AUDIT_VIEW": ("governance", "View the audit trail"),
}

_VIEWER = {"DASH_VIEW", "REPORT_VIEW", "MASTER_BRANCH_VIEW", "MASTER_PRODUCT_VIEW"}
_ANALYST = _VIEWER | {
    "ACCOUNT_DRILLDOWN", "REPORT_EXPORT", "SCENARIO_VIEW", "SCENARIO_RUN",
    "CONFIG_RATE_VIEW", "UPLOAD_VIEW",
}

ROLES: dict[str, dict] = {
    "ADMIN": {
        "name": "Administrator",
        "is_admin": True,
        "description": "Creates and maintains users at or below own scope",
        # Deliberately NOT granted CONFIG_APPROVE: creating users and approving
        # rate changes are different duties and should not collapse into one role.
        "permissions": _ANALYST | {
            "USER_VIEW", "USER_CREATE", "USER_EDIT", "USER_DISABLE", "ROLE_GRANT",
            "AUDIT_VIEW", "MASTER_ORG_VIEW",
        },
    },
    "FTP_MANAGER": {
        "name": "FTP Manager",
        "description": "Maintains product master and rate configuration (maker)",
        "permissions": _ANALYST | {
            "MASTER_PRODUCT_EDIT", "CONFIG_RATE_EDIT", "MASTER_BRANCH_EDIT",
            "MASTER_ORG_VIEW", "CALC_RUN",
        },
    },
    "FTP_APPROVER": {
        "name": "FTP Approver",
        "description": "Approves configuration changes (checker)",
        "permissions": _ANALYST | {"CONFIG_APPROVE", "AUDIT_VIEW", "CALC_RECALC_HISTORY"},
    },
    "DATA_OPERATOR": {
        "name": "Data Operator",
        "description": "Uploads files, reviews exceptions, commits batches",
        "permissions": _VIEWER | {
            "UPLOAD_VIEW", "UPLOAD_CREATE", "UPLOAD_COMMIT", "CALC_RUN",
            "ACCOUNT_DRILLDOWN",
        },
    },
    "ANALYST": {
        "name": "Analyst",
        "description": "Dashboards, drilldown, reports, scenarios",
        "permissions": _ANALYST,
    },
    "VIEWER": {
        "name": "Viewer",
        "description": "Read-only dashboards and reports",
        "permissions": _VIEWER,
    },
    "AUDITOR": {
        "name": "Auditor",
        "description": "Read-only across data, configuration and audit; mutates nothing",
        "permissions": _ANALYST | {"AUDIT_VIEW", "USER_VIEW", "MASTER_ORG_VIEW"},
    },
}


def permissions_for_roles(role_codes: set[str]) -> frozenset[str]:
    out: set[str] = set()
    for code in role_codes:
        out |= set(ROLES.get(code, {}).get("permissions", set()))
    return frozenset(out)
