"""Unit tests for alerts API endpoints."""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models import Alert, Rule


class TestListAlerts:
    """Tests for GET /api/v1/alerts endpoint."""

    @pytest.mark.asyncio
    async def test_list_alerts_empty(self, client: AsyncClient):
        """Test listing alerts when database is empty."""
        response = await client.get("/api/v1/alerts")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["has_next"] is False
        assert data["has_prev"] is False

    @pytest.mark.asyncio
    async def test_list_alerts_with_data(self, client: AsyncClient, sample_alert: Alert):
        """Test listing alerts with data."""
        response = await client.get("/api/v1/alerts")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_list_alerts_pagination(self, client: AsyncClient, multiple_alerts: list[Alert]):
        """Test alerts pagination."""
        # Page 1, size 2
        response = await client.get("/api/v1/alerts?page=1&page_size=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["has_next"] is True
        assert data["has_prev"] is False

        # Page 2, size 2
        response = await client.get("/api/v1/alerts?page=2&page_size=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["has_next"] is True
        assert data["has_prev"] is True

        # Page 3, size 2
        response = await client.get("/api/v1/alerts?page=3&page_size=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["has_next"] is False
        assert data["has_prev"] is True

    @pytest.mark.asyncio
    async def test_list_alerts_filter_by_symbol(
        self, client: AsyncClient, multiple_alerts: list[Alert]
    ):
        """Test filtering alerts by symbol."""
        response = await client.get("/api/v1/alerts?symbol=AAPL")
        assert response.status_code == 200
        data = response.json()
        assert all(item["symbol"] == "AAPL" for item in data["items"])

    @pytest.mark.asyncio
    async def test_list_alerts_filter_by_symbol_case_insensitive(
        self, client: AsyncClient, multiple_alerts: list[Alert]
    ):
        """Test symbol filter is case insensitive."""
        response = await client.get("/api/v1/alerts?symbol=aapl")
        assert response.status_code == 200
        data = response.json()
        assert all(item["symbol"] == "AAPL" for item in data["items"])

    @pytest.mark.asyncio
    async def test_list_alerts_filter_by_setup_type(
        self, client: AsyncClient, multiple_alerts: list[Alert]
    ):
        """Test filtering alerts by setup type."""
        response = await client.get("/api/v1/alerts?setup_type=breakout")
        assert response.status_code == 200
        data = response.json()
        assert all(item["setup_type"] == "breakout" for item in data["items"])

    @pytest.mark.asyncio
    async def test_list_alerts_filter_by_read_status(
        self, client: AsyncClient, multiple_alerts: list[Alert]
    ):
        """Test filtering alerts by read status."""
        # Filter for read alerts
        response = await client.get("/api/v1/alerts?is_read=true")
        assert response.status_code == 200
        data = response.json()
        assert all(item["is_read"] is True for item in data["items"])

        # Filter for unread alerts
        response = await client.get("/api/v1/alerts?is_read=false")
        assert response.status_code == 200
        data = response.json()
        assert all(item["is_read"] is False for item in data["items"])


class TestGetAlertStats:
    """Tests for GET /api/v1/alerts/stats endpoint."""

    @pytest.mark.asyncio
    async def test_stats_empty(self, client: AsyncClient):
        """Test stats when no alerts exist."""
        response = await client.get("/api/v1/alerts/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_alerts"] == 0
        assert data["alerts_today"] == 0
        assert data["unread_count"] == 0
        assert data["by_setup_type"] == {}
        assert data["by_symbol"] == {}

    @pytest.mark.asyncio
    async def test_stats_with_alerts(self, client: AsyncClient, multiple_alerts: list[Alert]):
        """Test stats with multiple alerts."""
        response = await client.get("/api/v1/alerts/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_alerts"] == 5
        assert data["alerts_today"] == 5  # All alerts created today
        assert data["unread_count"] > 0
        assert "breakout" in data["by_setup_type"]
        assert "AAPL" in data["by_symbol"]


class TestGetAlert:
    """Tests for GET /api/v1/alerts/{alert_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_alert_success(self, client: AsyncClient, sample_alert: Alert):
        """Test getting a specific alert."""
        response = await client.get(f"/api/v1/alerts/{sample_alert.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_alert.id
        assert data["symbol"] == "AAPL"
        assert data["setup_type"] == "breakout"
        assert data["entry_price"] == 150.50
        assert data["stop_loss"] == 145.99
        assert data["target_price"] == 160.00
        assert data["confidence_score"] == 0.85
        assert data["is_read"] is False

    @pytest.mark.asyncio
    async def test_get_alert_not_found(self, client: AsyncClient):
        """Test getting non-existent alert returns 404."""
        response = await client.get("/api/v1/alerts/99999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_alert_with_rule_name(self, client: AsyncClient, sample_alert: Alert):
        """Test alert includes associated rule name."""
        response = await client.get(f"/api/v1/alerts/{sample_alert.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["rule_name"] == "Test Breakout Rule"


class TestUpdateAlert:
    """Tests for PATCH /api/v1/alerts/{alert_id} endpoint."""

    @pytest.mark.asyncio
    async def test_update_alert_mark_as_read(self, client: AsyncClient, sample_alert: Alert):
        """Test marking an alert as read."""
        assert sample_alert.is_read is False

        response = await client.patch(
            f"/api/v1/alerts/{sample_alert.id}",
            json={"is_read": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_read"] is True

    @pytest.mark.asyncio
    async def test_update_alert_mark_as_unread(self, client: AsyncClient, sample_alert: Alert):
        """Test marking an alert as unread."""
        # First mark as read
        await client.patch(
            f"/api/v1/alerts/{sample_alert.id}",
            json={"is_read": True},
        )

        # Then mark as unread
        response = await client.patch(
            f"/api/v1/alerts/{sample_alert.id}",
            json={"is_read": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_read"] is False

    @pytest.mark.asyncio
    async def test_update_alert_not_found(self, client: AsyncClient):
        """Test updating non-existent alert returns 404."""
        response = await client.patch(
            "/api/v1/alerts/99999",
            json={"is_read": True},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_alert_empty_body(self, client: AsyncClient, sample_alert: Alert):
        """Test update with empty body doesn't change anything."""
        original_response = await client.get(f"/api/v1/alerts/{sample_alert.id}")
        original_data = original_response.json()

        response = await client.patch(
            f"/api/v1/alerts/{sample_alert.id}",
            json={},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_read"] == original_data["is_read"]
