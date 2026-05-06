# ABOUTME: Mock-based unit tests for docker/init_roles.ensure_analyst_role.
# ABOUTME: Verifies idempotency, SQL Lab perm filtering, and graceful fallback.
"""Tests for the Analyst role bootstrap helper."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make `docker/init_roles.py` importable without packaging it.
_DOCKER_DIR = Path(__file__).resolve().parent.parent / "docker"
sys.path.insert(0, str(_DOCKER_DIR))

import init_roles  # noqa: E402

# Constraining mocks with `spec=[...]` is intentional: it ensures that if
# the function tries to access an attribute outside this allowlist, the
# test fails. This catches the kind of API drift that previously slipped
# past us in prod (`sm.get_session` not existing on real SecurityManagers).
_SM_API = ["find_role", "add_role", "find_permission_view_menu"]
_SESSION_API = ["merge", "commit"]
_ROLE_API = ["permissions"]


def _perm(permission_name: str, view_menu_name: str) -> MagicMock:
    """Build a mock PermissionView with the given names."""
    pv = MagicMock()
    pv.permission.name = permission_name
    pv.view_menu.name = view_menu_name
    return pv


def _make_role() -> MagicMock:
    role = MagicMock(spec=_ROLE_API)
    role.permissions = []
    return role


def _make_session() -> MagicMock:
    return MagicMock(spec=_SESSION_API)


def _make_sm(
    *,
    existing_role: MagicMock | None = None,
    gamma_perms: list[MagicMock] | None = None,
    all_database_access_pv: MagicMock | None = None,
    all_datasource_access_pv: MagicMock | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Build a SecurityManager mock with controllable lookups.

    Returns (sm, new_role) so tests can assert on the role that
    ``add_role`` would have produced.
    """
    sm = MagicMock(spec=_SM_API)

    new_role = _make_role()
    sm.add_role.return_value = new_role

    def find_role(name):
        if name == "Analyst":
            return existing_role
        if name == "Gamma":
            if gamma_perms is None:
                return None
            gamma = _make_role()
            gamma.permissions = list(gamma_perms)
            return gamma
        return None

    sm.find_role.side_effect = find_role

    def find_pv(perm_name, view_menu_name):
        if perm_name == "all_database_access":
            return all_database_access_pv
        if perm_name == "all_datasource_access":
            return all_datasource_access_pv
        return None

    sm.find_permission_view_menu.side_effect = find_pv

    return sm, new_role


class TestEnsureAnalystRole:
    def test_creates_role_when_missing(self):
        sm, _ = _make_sm()
        init_roles.ensure_analyst_role(sm, _make_session())
        sm.add_role.assert_called_once_with("Analyst")

    def test_reuses_existing_role(self):
        existing = _make_role()
        sm, _ = _make_sm(existing_role=existing)
        init_roles.ensure_analyst_role(sm, _make_session())
        sm.add_role.assert_not_called()

    def test_excludes_sql_lab_view_menu_permissions(self):
        gamma_perms = [
            _perm("can_read", "Dashboard"),
            _perm("menu_access", "SQL Lab"),
            _perm("can_read", "Query Search"),
            _perm("can_read", "SavedQuery"),
            _perm("can_write", "Query"),
            _perm("can_write", "Chart"),
            # SQLLab (no space) is a separate Superset view-menu name used by
            # can_estimate_query_cost and can_format_sql — must also be stripped.
            _perm("can_estimate_query_cost", "SQLLab"),
            _perm("can_format_sql", "SQLLab"),
        ]
        sm, new_role = _make_sm(gamma_perms=gamma_perms)
        init_roles.ensure_analyst_role(sm, _make_session())
        view_menus = {pv.view_menu.name for pv in new_role.permissions}
        assert "SQL Lab" not in view_menus
        assert "SQLLab" not in view_menus
        assert "Query Search" not in view_menus
        assert "SavedQuery" not in view_menus
        assert "Query" not in view_menus
        assert "Dashboard" in view_menus
        assert "Chart" in view_menus

    def test_excludes_tag_write_and_apply(self):
        """Analysts can read tags but not create or apply them."""
        gamma_perms = [
            _perm("can_read", "Tag"),
            _perm("can_write", "Tag"),
            _perm("can_bulk_create", "Tag"),
            _perm("can_tag", "Chart"),
            _perm("can_tag", "Dashboard"),
            _perm("can_read", "Dashboard"),
        ]
        sm, new_role = _make_sm(gamma_perms=gamma_perms)
        init_roles.ensure_analyst_role(sm, _make_session())
        pairs = {(pv.permission.name, pv.view_menu.name) for pv in new_role.permissions}
        assert ("can_read", "Tag") in pairs  # kept
        assert ("can_read", "Dashboard") in pairs  # kept
        assert ("can_write", "Tag") not in pairs
        assert ("can_bulk_create", "Tag") not in pairs
        assert ("can_tag", "Chart") not in pairs
        assert ("can_tag", "Dashboard") not in pairs

    def test_excludes_theme_write_keeps_read_and_export(self):
        """Analysts can use existing themes but not edit shared ones."""
        gamma_perms = [
            _perm("can_read", "Theme"),
            _perm("can_export", "Theme"),
            _perm("can_write", "Theme"),
            _perm("menu_access", "Themes"),
        ]
        sm, new_role = _make_sm(gamma_perms=gamma_perms)
        init_roles.ensure_analyst_role(sm, _make_session())
        pairs = {(pv.permission.name, pv.view_menu.name) for pv in new_role.permissions}
        assert ("can_read", "Theme") in pairs
        assert ("can_export", "Theme") in pairs
        assert ("menu_access", "Themes") in pairs
        assert ("can_write", "Theme") not in pairs

    def test_excludes_user_registrations_endpoints(self):
        """Strip the entire UserRegistrationsRestAPI / View view-menus.

        FAB registers /api/v1/security/user_registrations/* when
        AUTH_USER_REGISTRATION=True (required for OAuth JIT). The OAuth flow
        bypasses this mechanism, so Analysts should not be able to call it.
        """
        gamma_perms = [
            _perm("can_add", "UserRegistrationsRestAPI"),
            _perm("can_delete", "UserRegistrationsRestAPI"),
            _perm("can_edit", "UserRegistrationsRestAPI"),
            _perm("can_list", "UserRegistrationsRestAPI"),
            _perm("can_show", "UserRegistrationsRestAPI"),
            _perm("can_list", "UserRegistrationsView"),
            _perm("can_read", "Dashboard"),
        ]
        sm, new_role = _make_sm(gamma_perms=gamma_perms)
        init_roles.ensure_analyst_role(sm, _make_session())
        view_menus = {pv.view_menu.name for pv in new_role.permissions}
        assert "UserRegistrationsRestAPI" not in view_menus
        assert "UserRegistrationsView" not in view_menus
        assert "Dashboard" in view_menus

    def test_excludes_cache_invalidation(self):
        gamma_perms = [
            _perm("can_invalidate", "CacheRestApi"),
            _perm("can_read", "Dashboard"),
        ]
        sm, new_role = _make_sm(gamma_perms=gamma_perms)
        init_roles.ensure_analyst_role(sm, _make_session())
        pairs = {(pv.permission.name, pv.view_menu.name) for pv in new_role.permissions}
        assert ("can_invalidate", "CacheRestApi") not in pairs

    def test_excludes_rls_read(self):
        """RLS rule clauses can leak filter logic — strip read access."""
        gamma_perms = [
            _perm("can_read", "RowLevelSecurity"),
            _perm("can_read", "Dashboard"),
        ]
        sm, new_role = _make_sm(gamma_perms=gamma_perms)
        init_roles.ensure_analyst_role(sm, _make_session())
        pairs = {(pv.permission.name, pv.view_menu.name) for pv in new_role.permissions}
        assert ("can_read", "RowLevelSecurity") not in pairs
        assert ("can_read", "Dashboard") in pairs

    def test_excludes_embedded_delete(self):
        gamma_perms = [
            _perm("can_delete_embedded", "Dashboard"),
            _perm("can_get_embedded", "Dashboard"),
            _perm("can_read", "Dashboard"),
        ]
        sm, new_role = _make_sm(gamma_perms=gamma_perms)
        init_roles.ensure_analyst_role(sm, _make_session())
        pairs = {(pv.permission.name, pv.view_menu.name) for pv in new_role.permissions}
        assert ("can_delete_embedded", "Dashboard") not in pairs
        # Read still works (Analysts can view embedded dashboards)
        assert ("can_get_embedded", "Dashboard") in pairs
        assert ("can_read", "Dashboard") in pairs

    def test_excludes_sql_lab_action_permissions(self):
        gamma_perms = [
            _perm("can_sqllab", "Superset"),
            _perm("can_sql_json", "Superset"),
            _perm("can_csv", "Superset"),  # Kept — also used by chart export
            _perm("can_read", "Dashboard"),
        ]
        sm, new_role = _make_sm(gamma_perms=gamma_perms)
        init_roles.ensure_analyst_role(sm, _make_session())
        perm_names = {pv.permission.name for pv in new_role.permissions}
        assert "can_sqllab" not in perm_names
        assert "can_sql_json" not in perm_names
        assert "can_csv" in perm_names
        assert "can_read" in perm_names

    def test_includes_all_database_and_datasource_access(self):
        db_pv = _perm("all_database_access", "all_database_access")
        ds_pv = _perm("all_datasource_access", "all_datasource_access")
        sm, new_role = _make_sm(
            gamma_perms=[],
            all_database_access_pv=db_pv,
            all_datasource_access_pv=ds_pv,
        )
        init_roles.ensure_analyst_role(sm, _make_session())
        assert db_pv in new_role.permissions
        assert ds_pv in new_role.permissions

    def test_handles_missing_all_access_perms_gracefully(self):
        sm, new_role = _make_sm(
            gamma_perms=[_perm("can_read", "Dashboard")],
            all_database_access_pv=None,
            all_datasource_access_pv=None,
        )
        init_roles.ensure_analyst_role(sm, _make_session())
        assert len(new_role.permissions) == 1

    def test_handles_missing_gamma_gracefully(self):
        db_pv = _perm("all_database_access", "all_database_access")
        sm, new_role = _make_sm(
            gamma_perms=None,
            all_database_access_pv=db_pv,
        )
        init_roles.ensure_analyst_role(sm, _make_session())
        assert db_pv in new_role.permissions

    def test_merges_and_commits_session(self):
        sm, new_role = _make_sm()
        session = _make_session()
        init_roles.ensure_analyst_role(sm, session)
        session.merge.assert_called_once_with(new_role)
        session.commit.assert_called_once()

    def test_custom_role_name(self):
        sm, _ = _make_sm()
        init_roles.ensure_analyst_role(sm, _make_session(), role_name="Viewer")
        sm.add_role.assert_called_once_with("Viewer")

    def test_does_not_duplicate_all_access_perms_when_in_gamma(self):
        db_pv = _perm("all_database_access", "all_database_access")
        ds_pv = _perm("all_datasource_access", "all_datasource_access")
        sm, new_role = _make_sm(
            gamma_perms=[db_pv, ds_pv, _perm("can_read", "Dashboard")],
            all_database_access_pv=db_pv,
            all_datasource_access_pv=ds_pv,
        )
        init_roles.ensure_analyst_role(sm, _make_session())
        # Each all_*_access perm appears exactly once
        assert sum(1 for p in new_role.permissions if p is db_pv) == 1
        assert sum(1 for p in new_role.permissions if p is ds_pv) == 1

    def test_session_must_provide_merge_and_commit(self):
        """A session that lacks merge() should fail loudly, not silently."""
        sm, _ = _make_sm()
        broken_session = MagicMock(spec=["commit"])  # no merge
        with pytest.raises(AttributeError):
            init_roles.ensure_analyst_role(sm, broken_session)

    def test_security_manager_must_have_expected_api(self):
        """If a future FAB version drops one of these methods, fail fast."""
        broken_sm = MagicMock(spec=["find_role"])  # missing add_role
        broken_sm.find_role.return_value = None
        with pytest.raises(AttributeError):
            init_roles.ensure_analyst_role(broken_sm, _make_session())
