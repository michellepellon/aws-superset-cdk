# ABOUTME: Idempotent custom-role provisioning for Superset (e.g. "Analyst").
# ABOUTME: Invoked once per migration run after `superset init` seeds defaults.
"""Custom Superset role bootstrap.

Creates the "Analyst" role: read access to dashboards/charts, ability to
create personal dashboards/charts (DASHBOARD_RBAC enforces row-level
ownership), automatic access to all configured databases/datasources, but
no SQL Lab and no admin views.

The role is built by copying Gamma's permission set, filtering out SQL Lab
permissions, then adding `all_database_access` and `all_datasource_access`.
This is more resilient across Superset versions than hardcoding a perm list.
"""

import logging

# View menus that scope SQL Lab access. Permissions attached to these
# view menus are filtered out of the Analyst role.
_SQL_LAB_VIEW_MENUS = frozenset(
    {"SQL Lab", "Query Search", "SavedQuery", "Query"}
)

# Action-level permission names that gate raw SQL execution.
# `can_csv` is intentionally NOT included — it's also used for chart export.
_SQL_LAB_PERMISSIONS = frozenset({"can_sqllab", "can_sql_json"})


def _is_sql_lab_perm(pv) -> bool:
    """True if the given PermissionView gates SQL Lab functionality."""
    view_menu_name = getattr(pv.view_menu, "name", None)
    if view_menu_name in _SQL_LAB_VIEW_MENUS:
        return True
    permission_name = getattr(pv.permission, "name", None)
    if permission_name in _SQL_LAB_PERMISSIONS:
        return True
    return False


def ensure_analyst_role(
    security_manager,
    role_name: str = "Analyst",
    logger: logging.Logger | None = None,
) -> None:
    """Idempotently create or refresh the Analyst role.

    Args:
        security_manager: Superset's SecurityManager (typically
            ``app.appbuilder.sm``).
        role_name: Name of the role to create/refresh. Defaults to
            "Analyst".
        logger: Optional logger; falls back to the module logger.
    """
    log = logger or logging.getLogger(__name__)
    sm = security_manager

    role = sm.find_role(role_name)
    if role is None:
        log.info("Creating role %r", role_name)
        role = sm.add_role(role_name)
    else:
        log.info("Role %r already exists; refreshing permissions", role_name)

    # Start from Gamma's permissions (minus SQL Lab) for forward-compat.
    permissions: list = []
    gamma = sm.find_role("Gamma")
    if gamma is None:
        log.warning(
            "Gamma role not found; %r will only receive all_*_access perms",
            role_name,
        )
    else:
        for pv in gamma.permissions:
            if _is_sql_lab_perm(pv):
                continue
            permissions.append(pv)
        log.info(
            "Inherited %d non-SQL-Lab permissions from Gamma", len(permissions)
        )

    # Layer on broad data access so analysts see every configured DB/dataset.
    for perm_name in ("all_database_access", "all_datasource_access"):
        pv = sm.find_permission_view_menu(perm_name, perm_name)
        if pv is None:
            log.warning(
                "Permission %r not found; skipping (run `superset init` first)",
                perm_name,
            )
            continue
        if pv not in permissions:
            permissions.append(pv)

    role.permissions = permissions
    sm.get_session.commit()
    log.info(
        "Role %r persisted with %d permissions", role_name, len(permissions)
    )
