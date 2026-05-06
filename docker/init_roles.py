# ABOUTME: Idempotent custom-role provisioning for Superset (e.g. "Analyst").
# ABOUTME: Invoked once per migration run after `superset init` seeds defaults.
"""Custom Superset role bootstrap.

Creates the "Analyst" role: read access to dashboards/charts, ability to
create personal dashboards/charts (DASHBOARD_RBAC enforces row-level
ownership), automatic access to all configured databases/datasources, but
no SQL Lab access and no write access to org-wide resources (tags, themes).

The role is built by copying Gamma's permission set, filtering out a curated
set of dangerous permissions, then adding `all_database_access` and
`all_datasource_access`. This is more resilient across Superset versions
than hardcoding a perm list.
"""

import logging

# View-menu names whose permissions are stripped entirely. These cover SQL
# Lab access (Superset uses both "SQL Lab" with a space and "SQLLab" without
# in different perms) plus query-related sub-menus.
_EXCLUDED_VIEW_MENUS = frozenset(
    {"SQL Lab", "SQLLab", "Query Search", "SavedQuery", "Query"}
)

# Action-level permission names that gate raw SQL execution regardless of
# their view menu. `can_csv` is intentionally NOT included — it's also used
# for chart export.
_EXCLUDED_PERMISSIONS = frozenset({"can_sqllab", "can_sql_json"})

# Specific (permission_name, view_menu_name) pairs to strip. These let
# Analysts read/use shared resources but not modify them in ways that
# affect other users.
_EXCLUDED_PERM_PAIRS = frozenset({
    # Tag write/apply — Analysts shouldn't re-tag or untag org-wide content.
    # Read access to existing tags is preserved.
    ("can_write", "Tag"),
    ("can_bulk_create", "Tag"),
    ("can_tag", "Chart"),
    ("can_tag", "Dashboard"),
    # Theme write — Analysts shouldn't edit shared dashboard themes.
    # Read/export access to existing themes is preserved.
    ("can_write", "Theme"),
})


def _is_excluded(pv) -> bool:
    """True if the given PermissionView should be stripped from Analyst."""
    perm_name = getattr(pv.permission, "name", None)
    view_menu_name = getattr(pv.view_menu, "name", None)
    if view_menu_name in _EXCLUDED_VIEW_MENUS:
        return True
    if perm_name in _EXCLUDED_PERMISSIONS:
        return True
    if (perm_name, view_menu_name) in _EXCLUDED_PERM_PAIRS:
        return True
    return False


def ensure_analyst_role(
    security_manager,
    session,
    role_name: str = "Analyst",
    logger: logging.Logger | None = None,
) -> None:
    """Idempotently create or refresh the Analyst role.

    Args:
        security_manager: Superset's SecurityManager (typically
            ``app.appbuilder.sm``).
        session: SQLAlchemy session for committing the permission
            assignment (typically ``superset.db.session``). Passed
            explicitly because ``BaseSecurityManager.get_session`` was
            removed in newer Flask-AppBuilder versions.
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

    # Start from Gamma's permissions (minus excluded ones) for forward-compat.
    permissions: list = []
    gamma = sm.find_role("Gamma")
    if gamma is None:
        log.warning(
            "Gamma role not found; %r will only receive all_*_access perms",
            role_name,
        )
    else:
        for pv in gamma.permissions:
            if _is_excluded(pv):
                continue
            permissions.append(pv)
        log.info(
            "Inherited %d filtered permissions from Gamma", len(permissions)
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
    # merge() reattaches the role if `add_role` ended its transaction,
    # so the permission assignment actually persists.
    session.merge(role)
    session.commit()
    log.info(
        "Role %r persisted with %d permissions", role_name, len(permissions)
    )
