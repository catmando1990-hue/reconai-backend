import pytest
from unittest.mock import MagicMock
from io import BytesIO


@pytest.fixture
def mock_analyze(mocker):
    """Mock the analyze_transactions function with proper return structure."""
    mock_response = MagicMock()
    mock_response.business_expenses = []
    mock_response.personal_expenses = []
    mock_response.transfers = []
    mock_response.uncertain = []
    # Patch where it's used in MVP router (imported as analyze_transactions)
    return mocker.patch("app.routers.mvp.analyze_transactions", return_value=mock_response)


def test_upload(client, mock_db, mock_analyze):
    """Test the MVP /upload endpoint."""
    file_data = BytesIO(b"some,csv,data")
    file_data.name = "test.csv"

    response = client.post("/upload", files={"file": ("test.csv", file_data, "text/csv")})

    assert response.status_code == 200
    assert "upload_id" in response.json()
    assert "organization_id" in response.json()
    assert "total_transactions" in response.json()

    # Verify the analyze function was called
    mock_analyze.assert_called_once()

    # Verify database commit was called
    mock_db.__enter__.return_value.commit.assert_called_once()
