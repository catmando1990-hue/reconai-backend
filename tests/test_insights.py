def test_insights(client, mock_db):
    # The insights endpoint makes TWO queries (mvp.py:238 and mvp.py:252)
    # We need to mock both: totals query (fetchall) and overall query (fetchone)
    # PLUS the organization_members query from _resolve_mvp_org_id dependency

    # Mock data for the two MVP queries
    totals_result = [
        {"classification": "business", "count": 2, "outflow": 125.0, "inflow": 0},
        {"classification": "personal", "count": 1, "outflow": 30.0, "inflow": 0},
    ]

    overall_result = {"total_transactions": 3, "total_outflow": 155.0, "total_inflow": 0}

    # Track which MVP query we're on
    mvp_call_count = [0]

    # Create a custom side_effect that handles both org lookup and MVP queries
    from unittest.mock import MagicMock

    def custom_execute(query, _params=None):
        cursor = MagicMock()

        # Organization member lookup query (from conftest side_effect)
        if "FROM organization_members" in query:
            cursor.fetchone.return_value = {
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
            cursor.fetchall.return_value = []
            return cursor

        # MVP transactions queries
        elif "FROM mvp_transactions" in query:
            if mvp_call_count[0] == 0:
                # First MVP query: totals (fetchall)
                cursor.fetchall.return_value = totals_result
                mvp_call_count[0] += 1
            else:
                # Second MVP query: overall (fetchone)
                cursor.fetchone.return_value = overall_result
            return cursor

        # Default
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        return cursor

    # Replace the side_effect
    mock_db.__enter__.return_value.execute.side_effect = custom_execute

    response = client.get("/insights", headers={"X-Organization-ID": "test_org"})

    assert response.status_code == 200
    # Check the actual MVP insights response structure (mvp.py:268-276)
    assert response.json()["total_outflow"] == 155.0
    assert response.json()["total_transactions"] == 3
    assert response.json()["by_classification"]["business"]["count"] == 2
    assert response.json()["by_classification"]["business"]["outflow"] == 125.0
