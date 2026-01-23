# Test x-request-id middleware behavior
# Verifies header is present on all response types: 200, HTTPException, unhandled exceptions

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def test_client():
    """Minimal test client without auth overrides."""
    return TestClient(app, raise_server_exceptions=False)


class TestRequestIdMiddleware:
    """Test x-request-id header on all response types."""

    def test_200_response_has_request_id(self, test_client):
        """200 OK responses include x-request-id header."""
        response = test_client.get("/")
        assert response.status_code == 200
        assert "x-request-id" in response.headers
        assert len(response.headers["x-request-id"]) == 36  # UUID format

    def test_200_echoes_provided_request_id(self, test_client):
        """Server echoes back the client-provided x-request-id."""
        custom_id = "test-request-id-12345"
        response = test_client.get("/", headers={"x-request-id": custom_id})
        assert response.status_code == 200
        assert response.headers["x-request-id"] == custom_id

    def test_404_response_has_request_id(self, test_client):
        """404 Not Found responses include x-request-id header."""
        response = test_client.get("/nonexistent-endpoint-xyz")
        assert response.status_code == 404
        assert "x-request-id" in response.headers

    def test_401_response_has_request_id(self, test_client):
        """401 Unauthorized responses include x-request-id header."""
        # Try an auth-protected endpoint without auth
        response = test_client.get("/api/me")
        # Should be 401 or 403
        assert response.status_code in (401, 403, 422)
        assert "x-request-id" in response.headers

    def test_422_validation_error_has_request_id(self, test_client):
        """422 Validation Error responses include x-request-id header."""
        # POST to an endpoint that requires body validation
        response = test_client.post("/api/contact", json={})
        assert response.status_code == 422
        assert "x-request-id" in response.headers
        # Verify request_id in body matches header
        body = response.json()
        if "error" in body and "request_id" in body["error"]:
            assert body["error"]["request_id"] == response.headers["x-request-id"]

    def test_options_preflight_has_request_id(self, test_client):
        """CORS preflight OPTIONS responses include x-request-id header."""
        response = test_client.options(
            "/api/me",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            }
        )
        # OPTIONS should succeed (200 or 204)
        assert response.status_code in (200, 204)
        assert "x-request-id" in response.headers

    def test_health_endpoint_has_request_id(self, test_client):
        """Health check endpoint includes x-request-id header."""
        response = test_client.get("/health")
        assert response.status_code == 200
        assert "x-request-id" in response.headers
