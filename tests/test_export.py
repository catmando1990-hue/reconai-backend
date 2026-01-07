def test_export(client, mock_db):
    # Set fetchall to return a valid row with the correct structure for mvp_transactions
    # Columns: tx_date, amount, description, merchant, original_category, classification, reason, upload_id
    mock_db.__enter__.return_value.execute.return_value.fetchall.return_value = [
        ("2023-01-01", 100.0, "Description", "Merchant", "Category", "business", "Test reason", "upload1")
    ]
    response = client.get("/export", headers={"X-Organization-ID": "test_org"})

    assert response.status_code == 200
    # MVP export endpoint returns "export.csv" when no upload_id is specified (mvp.py:321)
    assert response.headers["Content-Disposition"] == "attachment; filename=export.csv"
    # Check CSV header matches the MVP export format (mvp.py:306)
    assert response.text.startswith("date,amount,description,merchant,original_category,classification,reason,upload_id")
