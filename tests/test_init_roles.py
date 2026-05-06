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


def _perm(permission_name: str, view_menu_name: str) -> MagicMock:
    """Build a mock PermissionView with the given names."""
    pv = MagicMock()
    pv.permission.name = permission_name
    pv.view_menu.name = view_menu_name
    return pv


def _make_sm(
    *,
    existing_role: MagicMock | None = None,
    gamma_perms: list[MagicMock] | None = None,
    all_database_access_pv: MagicMock | None = None,
    all_datasource_access_pv: MagicMock | None = None,
) -> MagicMock:
    """Build a SecurityManager mock with controllable lookups."""
    sm = MagicMock()

    new_role = MagicMock()
    new_role.permissions = []
    sm.add_role.return_value = new_role

    def find_role(name):
        if name == "Analyst":
            return existing_role
        if name == "Gamma":
            if gamma_perms is None:
                return None
            gamma = MagicMock()
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

    return sm


class TestEnsureAnalystRole:
    def test_creates_role_when_missing(self):
        sm = _make_sm()
        init_roles.ensure_analyst_role(sm)
        sm.add_role.assert_called_once_with("Analyst")

    def test_reuses_existing_role(self):
        existing = MagicMock()
        existing.permissions = []
        sm = _make_sm(existing_role=existing)
        init_roles.ensure_analyst_role(sm)
        sm.add_role.assert_not_called()

    def test_excludes_sql_lab_view_menu_permissions(self):
        gamma_perms = [
            _perm("can_read", "Dashboard"),
            _perm("menu_access", "SQL Lab"),
            _perm("can_read", "Query Search"),
            _perm("can_read", "SavedQuery"),
            _perm("can_write", "Query"),
            _perm("can_write", "Chart"),
        ]
        sm = _make_sm(gamma_perms=gamma_perms)
        init_roles.ensure_analyst_role(sm)
        view_menus = {
            pv.view_menu.name for pv in sm.add_role.return_value.permissions
        }
        assert "SQL Lab" not in view_menus
        assert "Query Search" not in view_menus
        assert "SavedQuery" not in view_menus
        assert "Query" not in view_menus
        assert "Dashboard" in view_menus
        assert "Chart" in view_menus

    def test_excludes_sql_lab_action_permissions(self):
        gamma_perms = [
            _perm("can_sqllab", "Superset"),
            _perm("can_sql_json", "Superset"),
            _perm("can_csv", "Superset"),  # Kept — also used by chart export
            _perm("can_read", "Dashboard"),
        ]
        sm = _make_sm(gamma_perms=gamma_perms)
        init_roles.ensure_analyst_role(sm)
        perm_names = {
            pv.permission.name for pv in sm.add_role.return_value.permissions
        }
        assert "can_sqllab" not in perm_names
        assert "can_sql_json" not in perm_names
        assert "can_csv" in perm_names
        assert "can_read" in perm_names

    def test_includes_all_database_and_datasource_access(self):
        db_pv = _perm("all_database_access", "all_database_access")
        ds_pv = _perm("all_datasource_access", "all_datasource_access")
        sm = _make_sm(
            gamma_perms=[],
            all_database_access_pv=db_pv,
            all_datasource_access_pv=ds_pv,
        )
        init_roles.ensure_analyst_role(sm)
        permissions = sm.add_role.return_value.permissions
        assert db_pv in permissions
        assert ds_pv in permissions

    def test_handles_missing_all_access_perms_gracefully(self):
        sm = _make_sm(
            gamma_perms=[_perm("can_read", "Dashboard")],
            all_database_access_pv=None,
            all_datasource_access_pv=None,
        )
        init_roles.ensure_analyst_role(sm)
        permissions = sm.add_role.return_value.permissions
        assert len(permissions) == 1

    def test_handles_missing_gamma_gracefully(self):
        db_pv = _perm("all_database_access", "all_database_access")
        sm = _make_sm(
            gamma_perms=None,
            all_database_access_pv=db_pv,
        )
        init_roles.ensure_analyst_role(sm)
        permissions = sm.add_role.return_value.permissions
        assert db_pv in permissions

    def test_commits_session(self):
        sm = _make_sm()
        init_roles.ensure_analyst_role(sm)
        sm.get_session.commit.assert_called_once()

    def test_custom_role_name(self):
        sm = _make_sm()
        init_roles.ensure_analyst_role(sm, role_name="Viewer")
        sm.add_role.assert_called_once_with("Viewer")

    def test_does_not_duplicate_all_access_perms_when_in_gamma(self):
        db_pv = _perm("all_database_access", "all_database_access")
        ds_pv = _perm("all_datasource_access", "all_datasource_access")
        sm = _make_sm(
            gamma_perms=[db_pv, ds_pv, _perm("can_read", "Dashboard")],
            all_database_access_pv=db_pv,
            all_datasource_access_pv=ds_pv,
        )
        init_roles.ensure_analyst_role(sm)
        permissions = sm.add_role.return_value.permissions
        # Each all_*_access perm appears exactly once
        assert sum(1 for p in permissions if p is db_pv) == 1
        assert sum(1 for p in permissions if p is ds_pv) == 1


@pytest.fixture(autouse=True)
def _reset_role_state():
    """Each test gets a fresh mock, but ensure_analyst_role mutates role.permissions —
    so make sure tests don't accidentally share state via class-level fixtures."""
    yield
