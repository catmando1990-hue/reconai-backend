import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
import types
from app.main import app
from app.auth_context import get_current_identity, get_org_service

@pytest.fixture
def client():
    app.dependency_overrides = {}
    app.dependency_overrides[get_current_identity] = lambda: {
        "user_id": "test_user",
        "email": "test@example.com",
        "default_org_id": "test_org"
    }
    # Patch get_org_service to return a mock with get_organization_member returning a dict with a valid role
    app.dependency_overrides[get_org_service] = lambda: types.SimpleNamespace(
        get_organization_member=lambda org_id, user_id: {"role": "admin"}
    )
    return TestClient(app)

@pytest.fixture
def mock_db(mocker):
    mock_conn = MagicMock()
    org_member_row = {
        "id": "member-1",
        "organization_id": "test_org",
        "user_id": "test_user",
        "role": "admin",
        "permissions": "{}",
        "invited_by": None,
        "invited_at": None,
        "joined_at": "2023-01-01T00:00:00",
        "is_active": 1
    }

    # Storage for test-customizable mock data
    mock_conn._mvp_transactions_data = []
    mock_conn._mvp_uploads_data = []

    def execute_side_effect(query, params=None):
        # Return org_member_row for organization_members query
        if "FROM organization_members" in query:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = org_member_row
            mock_cursor.fetchall.return_value = [org_member_row]
            return mock_cursor
        # For mvp_transactions queries, return test-customizable data
        elif "FROM mvp_transactions" in query:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = mock_conn._mvp_transactions_data[0] if mock_conn._mvp_transactions_data else None
            mock_cursor.fetchall.return_value = mock_conn._mvp_transactions_data
            return mock_cursor
        # For mvp_uploads queries, return test-customizable data
        elif "FROM mvp_uploads" in query:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = mock_conn._mvp_uploads_data[0] if mock_conn._mvp_uploads_data else None
            mock_cursor.fetchall.return_value = mock_conn._mvp_uploads_data
            return mock_cursor
        # Return empty for other queries by default
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.fetchall.return_value = []
        return mock_cursor

    mock_conn.__enter__.return_value.execute.side_effect = execute_side_effect
    # Patch sqlite3.connect globally (used by MVP router's local import)
    mocker.patch("sqlite3.connect", return_value=mock_conn)
    # Also patch app.db for other tests
    mocker.patch("app.db.sqlite3.connect", return_value=mock_conn)
    return mock_conn
