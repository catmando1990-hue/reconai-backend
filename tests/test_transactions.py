def test_transactions(client, mock_db):
    # Set up mock data for mvp_transactions query
    mock_db._mvp_transactions_data = [
        {
            "id": "tx1",
            "upload_id": "upload1",
            "organization_id": "test_org",
            "user_id": "test_user",
            "tx_date": "2023-01-01",
            "amount": 100.0,
            "description": "Description",
            "merchant": "Test Merchant",
            "original_category": "Category",
            "classification": "business",
            "reason": "Business expense",
            "created_at": "2023-01-01T00:00:00"
        }
    ]

    response = client.get("/transactions", headers={"X-Organization-ID": "test_org"})

    assert response.status_code == 200
    # MVP endpoint returns dict with organization_id, upload_id, and transactions list (mvp.py:214-218)
    assert "transactions" in response.json()
    assert len(response.json()["transactions"]) == 1
    assert response.json()["transactions"][0]["description"] == "Description"
    assert response.json()["transactions"][0]["amount"] == 100.0
    assert response.json()["transactions"][0]["classification"] == "business"
