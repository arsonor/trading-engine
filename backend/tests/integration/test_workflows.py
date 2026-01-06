"""Integration tests for key application workflows.

These tests verify that multiple components work together correctly,
including database interactions, API endpoints, and business logic.
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, Rule, Watchlist
from app.engine.rule_engine import (
    RuleEngine,
    RuleDefinition,
    RuleCondition,
    RuleFilters,
    RuleTargets,
    RuleConfidence,
    OperatorType,
)


# ============== Fixtures for Integration Tests ==============


@pytest_asyncio.fixture
async def workflow_rule(db_session: AsyncSession) -> Rule:
    """Create a rule for workflow testing."""
    rule = Rule(
        name="Workflow Test Rule",
        description="Rule for workflow integration tests",
        rule_type="price",
        config_yaml="""
conditions:
  - field: price
    operator: ">"
    value: 100
filters:
  min_price: 5.0
targets:
  stop_loss_percent: -3.0
confidence:
  base_score: 0.75
""",
        is_active=True,
        priority=10,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    return rule


@pytest_asyncio.fixture
async def workflow_alert(db_session: AsyncSession, workflow_rule: Rule) -> Alert:
    """Create an alert for workflow testing."""
    alert = Alert(
        rule_id=workflow_rule.id,
        symbol="AAPL",
        timestamp=datetime.utcnow(),
        setup_type="breakout",
        entry_price=155.50,
        stop_loss=150.84,
        target_price=165.00,
        confidence_score=0.82,
        market_data_json={"price": 155.50, "volume": 1500000},
        is_read=False,
    )
    db_session.add(alert)
    await db_session.commit()
    await db_session.refresh(alert)
    return alert


@pytest_asyncio.fixture
async def multiple_workflow_alerts(
    db_session: AsyncSession, workflow_rule: Rule
) -> list[Alert]:
    """Create multiple alerts for workflow testing."""
    alerts = []
    test_data = [
        {"symbol": "AAPL", "setup_type": "breakout", "entry_price": 150.0, "is_read": False},
        {"symbol": "AAPL", "setup_type": "momentum", "entry_price": 152.0, "is_read": True},
        {"symbol": "GOOGL", "setup_type": "volume_spike", "entry_price": 140.0, "is_read": False},
        {"symbol": "MSFT", "setup_type": "breakout", "entry_price": 380.0, "is_read": True},
        {"symbol": "TSLA", "setup_type": "gap_up", "entry_price": 250.0, "is_read": False},
    ]

    for i, data in enumerate(test_data):
        alert = Alert(
            rule_id=workflow_rule.id,
            symbol=data["symbol"],
            timestamp=datetime.utcnow() - timedelta(minutes=i),
            setup_type=data["setup_type"],
            entry_price=data["entry_price"],
            confidence_score=0.7 + i * 0.05,
            is_read=data["is_read"],
        )
        db_session.add(alert)
        alerts.append(alert)

    await db_session.commit()
    for alert in alerts:
        await db_session.refresh(alert)
    return alerts


@pytest_asyncio.fixture
async def cascade_test_rule(db_session: AsyncSession) -> Rule:
    """Create a rule with alerts for cascade testing."""
    rule = Rule(
        name="Cascade Test Rule",
        description="Rule for testing cascade deletes",
        rule_type="price",
        config_yaml="conditions: []",
        is_active=True,
        priority=15,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    return rule


@pytest_asyncio.fixture
async def cascade_test_alerts(
    db_session: AsyncSession, cascade_test_rule: Rule
) -> list[Alert]:
    """Create alerts for cascade testing."""
    alerts = []
    for i, symbol in enumerate(["AAPL", "GOOGL", "MSFT"]):
        alert = Alert(
            rule_id=cascade_test_rule.id,
            symbol=symbol,
            timestamp=datetime.utcnow(),
            setup_type="breakout",
            entry_price=100.0 + i * 10,
            is_read=False,
        )
        db_session.add(alert)
        alerts.append(alert)

    await db_session.commit()
    for alert in alerts:
        await db_session.refresh(alert)
    return alerts


# ============== Test Classes ==============


class TestAlertLifecycleWorkflow:
    """Test complete alert lifecycle from creation to consumption."""

    @pytest.mark.asyncio
    async def test_full_alert_lifecycle(
        self, client: AsyncClient, workflow_rule: Rule, workflow_alert: Alert
    ):
        """Test: Read alert -> Mark as read -> Verify stats."""
        # Step 1: Verify alert appears in list
        list_response = await client.get("/api/v1/alerts")
        assert list_response.status_code == 200
        alerts_data = list_response.json()
        assert alerts_data["total"] == 1
        assert alerts_data["items"][0]["symbol"] == "AAPL"
        assert alerts_data["items"][0]["rule_name"] == "Workflow Test Rule"

        # Step 2: Get single alert with full details
        get_response = await client.get(f"/api/v1/alerts/{workflow_alert.id}")
        assert get_response.status_code == 200
        alert_data = get_response.json()
        assert alert_data["entry_price"] == 155.50
        assert alert_data["confidence_score"] == 0.82
        assert alert_data["is_read"] is False

        # Step 3: Check stats show unread alert
        stats_response = await client.get("/api/v1/alerts/stats")
        assert stats_response.status_code == 200
        stats = stats_response.json()
        assert stats["total_alerts"] == 1
        assert stats["unread_count"] == 1
        assert stats["by_symbol"]["AAPL"] == 1
        assert stats["by_setup_type"]["breakout"] == 1

        # Step 4: Mark alert as read
        update_response = await client.patch(
            f"/api/v1/alerts/{workflow_alert.id}",
            json={"is_read": True},
        )
        assert update_response.status_code == 200
        assert update_response.json()["is_read"] is True

        # Step 5: Verify stats updated
        stats_response = await client.get("/api/v1/alerts/stats")
        stats = stats_response.json()
        assert stats["unread_count"] == 0

    @pytest.mark.asyncio
    async def test_multiple_alerts_filtering_workflow(
        self, client: AsyncClient, multiple_workflow_alerts: list[Alert]
    ):
        """Test filtering multiple alerts."""
        # Test: Filter by symbol
        response = await client.get("/api/v1/alerts?symbol=AAPL")
        data = response.json()
        assert data["total"] == 2
        assert all(item["symbol"] == "AAPL" for item in data["items"])

        # Test: Filter by setup type
        response = await client.get("/api/v1/alerts?setup_type=breakout")
        data = response.json()
        assert data["total"] == 2
        assert all(item["setup_type"] == "breakout" for item in data["items"])

        # Test: Filter by read status
        response = await client.get("/api/v1/alerts?is_read=false")
        data = response.json()
        assert all(item["is_read"] is False for item in data["items"])

        # Test: Combined filters
        response = await client.get("/api/v1/alerts?symbol=AAPL&setup_type=breakout")
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["symbol"] == "AAPL"
        assert data["items"][0]["setup_type"] == "breakout"

        # Test: Pagination
        response = await client.get("/api/v1/alerts?page=1&page_size=2")
        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["has_next"] is True


class TestRuleManagementWorkflow:
    """Test rule CRUD operations with cascade effects on alerts."""

    @pytest.mark.asyncio
    async def test_rule_crud_with_alert_cascade(
        self,
        client: AsyncClient,
        cascade_test_rule: Rule,
        cascade_test_alerts: list[Alert],
    ):
        """Test: Verify alerts -> Update rule -> Delete rule -> Verify cascade."""
        rule_id = cascade_test_rule.id

        # Verify alerts are created
        alerts_response = await client.get("/api/v1/alerts")
        assert alerts_response.json()["total"] == 3

        # Verify rule shows correct alert count
        rule_response = await client.get(f"/api/v1/rules/{rule_id}")
        assert rule_response.json()["alerts_triggered"] == 3

        # Update the rule
        update_response = await client.put(
            f"/api/v1/rules/{rule_id}",
            json={
                "name": "Updated Cascade Rule",
                "description": "Updated description",
                "priority": 20,
            },
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Updated Cascade Rule"
        assert update_response.json()["priority"] == 20

        # Verify alerts still exist and reference the updated rule
        alerts_response = await client.get("/api/v1/alerts")
        assert alerts_response.json()["total"] == 3
        assert all(
            item["rule_name"] == "Updated Cascade Rule"
            for item in alerts_response.json()["items"]
        )

        # Delete the rule
        delete_response = await client.delete(f"/api/v1/rules/{rule_id}")
        assert delete_response.status_code == 204

        # Verify cascade - alerts should be deleted
        alerts_response = await client.get("/api/v1/alerts")
        assert alerts_response.json()["total"] == 0

        # Verify rule is gone
        rule_response = await client.get(f"/api/v1/rules/{rule_id}")
        assert rule_response.status_code == 404

    @pytest.mark.asyncio
    async def test_rule_toggle_workflow(self, client: AsyncClient):
        """Test toggling rules on and off."""
        # Create an active rule
        create_response = await client.post(
            "/api/v1/rules",
            json={
                "name": "Toggle Test Rule",
                "rule_type": "volume",
                "config_yaml": "conditions: []",
                "is_active": True,
            },
        )
        rule_id = create_response.json()["id"]
        assert create_response.json()["is_active"] is True

        # Toggle to inactive
        toggle_response = await client.post(f"/api/v1/rules/{rule_id}/toggle")
        assert toggle_response.status_code == 200
        assert toggle_response.json()["is_active"] is False

        # Verify via GET
        get_response = await client.get(f"/api/v1/rules/{rule_id}")
        assert get_response.json()["is_active"] is False

        # Toggle back to active
        toggle_response = await client.post(f"/api/v1/rules/{rule_id}/toggle")
        assert toggle_response.json()["is_active"] is True

    @pytest.mark.asyncio
    async def test_multiple_rules_priority_ordering(self, client: AsyncClient):
        """Test that rules are returned sorted by priority."""
        # Create rules with different priorities
        rules_data = [
            {"name": "Low Priority", "rule_type": "price", "config_yaml": "{}", "priority": 1},
            {"name": "High Priority", "rule_type": "volume", "config_yaml": "{}", "priority": 100},
            {"name": "Medium Priority", "rule_type": "gap", "config_yaml": "{}", "priority": 50},
        ]

        for data in rules_data:
            await client.post("/api/v1/rules", json=data)

        # Get all rules
        response = await client.get("/api/v1/rules")
        rules = response.json()

        # Verify sorted by priority descending
        assert rules[0]["name"] == "High Priority"
        assert rules[1]["name"] == "Medium Priority"
        assert rules[2]["name"] == "Low Priority"


class TestRuleEngineIntegration:
    """Test rule engine evaluation logic."""

    @pytest.mark.asyncio
    async def test_rule_engine_evaluation_triggers_correctly(self):
        """Test that rule engine correctly evaluates conditions."""
        # Create a RuleDefinition
        rule_def = RuleDefinition(
            name="Volume Spike Detector",
            type="volume",
            enabled=True,
            priority=10,
            conditions=[
                RuleCondition(field="volume_ratio", operator=OperatorType.GTE, value=2.0),
                RuleCondition(field="price", operator=OperatorType.GT, value=10),
            ],
            filters=RuleFilters(min_price=5.0, min_volume=100000),
            targets=RuleTargets(stop_loss_percent=-5.0, target_percent=10.0),
            confidence=RuleConfidence(base_score=0.7),
        )

        engine = RuleEngine()
        engine.add_rule(rule_def)

        # Market data that should trigger the rule
        market_data = {
            "symbol": "NVDA",
            "price": 450.00,
            "volume": 5000000,
            "volume_ratio": 3.5,
        }

        # Evaluate rules
        results = engine.evaluate_all_rules(market_data)

        # Should have one triggered rule
        assert len(results) == 1
        result = results[0]
        assert result.rule_name == "Volume Spike Detector"
        assert result.triggered is True
        assert result.confidence == 0.7
        assert result.stop_loss is not None
        assert result.target_price is not None

    @pytest.mark.asyncio
    async def test_rule_engine_filters_block_evaluation(self):
        """Test that rule filters correctly block evaluation."""
        # Create RuleDefinition with strict filters
        rule_def = RuleDefinition(
            name="Filtered Rule",
            type="price",
            enabled=True,
            conditions=[
                RuleCondition(field="price", operator=OperatorType.GT, value=0),
            ],
            filters=RuleFilters(min_price=50.0, max_price=200.0, min_volume=1000000),
        )

        engine = RuleEngine()
        engine.add_rule(rule_def)

        # Market data that fails min_price filter
        low_price_data = {"symbol": "PENNY", "price": 2.50, "volume": 5000000}
        results = engine.evaluate_all_rules(low_price_data)
        assert len(results) == 0  # Filtered out

        # Market data that fails max_price filter
        high_price_data = {"symbol": "EXPENSIVE", "price": 500.00, "volume": 5000000}
        results = engine.evaluate_all_rules(high_price_data)
        assert len(results) == 0  # Filtered out

        # Market data that fails volume filter
        low_volume_data = {"symbol": "ILLIQUID", "price": 100.00, "volume": 50000}
        results = engine.evaluate_all_rules(low_volume_data)
        assert len(results) == 0  # Filtered out

        # Market data that passes all filters
        valid_data = {"symbol": "VALID", "price": 100.00, "volume": 2000000}
        results = engine.evaluate_all_rules(valid_data)
        assert len(results) == 1
        assert results[0].triggered is True

    @pytest.mark.asyncio
    async def test_rule_engine_with_api_created_rule(self, client: AsyncClient):
        """Test rule engine with configuration from API."""
        # Create a rule via API
        rule_response = await client.post(
            "/api/v1/rules",
            json={
                "name": "API Created Rule",
                "rule_type": "volume",
                "config_yaml": """
conditions:
  - field: volume_ratio
    operator: ">="
    value: 2.0
filters:
  min_price: 5.0
targets:
  stop_loss_percent: -5.0
confidence:
  base_score: 0.7
""",
                "is_active": True,
                "priority": 10,
            },
        )
        assert rule_response.status_code == 201
        db_rule = rule_response.json()

        # Manually create a matching RuleDefinition for engine testing
        rule_def = RuleDefinition(
            name=db_rule["name"],
            type=db_rule["rule_type"],
            enabled=db_rule["is_active"],
            priority=db_rule["priority"],
            conditions=[
                RuleCondition(field="volume_ratio", operator=OperatorType.GTE, value=2.0),
            ],
            filters=RuleFilters(min_price=5.0),
            targets=RuleTargets(stop_loss_percent=-5.0),
            confidence=RuleConfidence(base_score=0.7),
        )

        engine = RuleEngine()
        engine.add_rule(rule_def)

        # Evaluate with market data
        market_data = {"symbol": "TEST", "price": 100.00, "volume": 1000000, "volume_ratio": 2.5}
        results = engine.evaluate_all_rules(market_data)

        assert len(results) == 1
        assert results[0].rule_name == "API Created Rule"
        assert results[0].triggered is True


class TestWatchlistWorkflow:
    """Test watchlist management workflows."""

    @pytest.mark.asyncio
    async def test_watchlist_crud_workflow(self, client: AsyncClient):
        """Test complete watchlist CRUD operations."""
        # Add symbols to watchlist
        symbols = ["AAPL", "GOOGL", "MSFT", "TSLA"]
        for symbol in symbols:
            response = await client.post(
                "/api/v1/watchlist",
                json={"symbol": symbol, "notes": f"Watching {symbol}"},
            )
            assert response.status_code == 201

        # Verify watchlist
        watchlist_response = await client.get("/api/v1/watchlist")
        assert len(watchlist_response.json()) == 4

        # Remove a symbol
        await client.delete("/api/v1/watchlist/AAPL")

        # Verify removal
        watchlist_response = await client.get("/api/v1/watchlist")
        current_symbols = {item["symbol"] for item in watchlist_response.json()}
        assert "AAPL" not in current_symbols
        assert len(current_symbols) == 3

    @pytest.mark.asyncio
    async def test_watchlist_duplicate_handling(self, client: AsyncClient):
        """Test watchlist correctly handles duplicates and re-adds."""
        # Add symbol
        response = await client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
        assert response.status_code == 201

        # Try to add duplicate
        response = await client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
        assert response.status_code == 409

        # Try with different case
        response = await client.post("/api/v1/watchlist", json={"symbol": "aapl"})
        assert response.status_code == 409

        # Remove and re-add should work
        await client.delete("/api/v1/watchlist/AAPL")
        response = await client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_watchlist_with_alerts_correlation(
        self, client: AsyncClient, workflow_rule: Rule, workflow_alert: Alert
    ):
        """Test that watchlist symbols can be correlated with alerts."""
        # Add the alert's symbol to watchlist
        await client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
        await client.post("/api/v1/watchlist", json={"symbol": "GOOGL"})

        # Query alerts
        alerts_response = await client.get("/api/v1/alerts")
        alert_symbols = {item["symbol"] for item in alerts_response.json()["items"]}

        # Query watchlist
        watchlist_response = await client.get("/api/v1/watchlist")
        watchlist_symbols = {item["symbol"] for item in watchlist_response.json()}

        # Alert symbol should be in watchlist
        assert "AAPL" in alert_symbols
        assert "AAPL" in watchlist_symbols


class TestCrossComponentWorkflow:
    """Test workflows that span multiple components."""

    @pytest.mark.asyncio
    async def test_complete_trading_alert_workflow(
        self, client: AsyncClient, workflow_rule: Rule, workflow_alert: Alert
    ):
        """
        Test complete workflow:
        1. Verify watchlist and rule exist
        2. Verify alert appears with rule reference
        3. User marks alert as read
        4. Stats reflect the changes
        """
        # 1. Add to watchlist
        await client.post(
            "/api/v1/watchlist",
            json={"symbol": "AAPL", "notes": "High momentum stock"},
        )

        # 2. Verify alert in API with rule reference
        alert_response = await client.get(f"/api/v1/alerts/{workflow_alert.id}")
        assert alert_response.status_code == 200
        alert_data = alert_response.json()
        assert alert_data["symbol"] == "AAPL"
        assert alert_data["rule_name"] == "Workflow Test Rule"
        assert alert_data["is_read"] is False

        # 3. Mark as read
        await client.patch(
            f"/api/v1/alerts/{workflow_alert.id}", json={"is_read": True}
        )

        # 4. Check stats
        stats_response = await client.get("/api/v1/alerts/stats")
        stats = stats_response.json()
        assert stats["total_alerts"] == 1
        assert stats["unread_count"] == 0
        assert "AAPL" in stats["by_symbol"]

        # Verify watchlist still has the symbol
        watchlist_response = await client.get("/api/v1/watchlist")
        symbols = [item["symbol"] for item in watchlist_response.json()]
        assert "AAPL" in symbols

    @pytest.mark.asyncio
    async def test_stats_accuracy_workflow(
        self, client: AsyncClient, multiple_workflow_alerts: list[Alert]
    ):
        """Test that stats accurately reflect alert state."""
        # Check initial stats
        stats_response = await client.get("/api/v1/alerts/stats")
        stats = stats_response.json()
        assert stats["total_alerts"] == 5
        # 3 unread alerts (indices 0, 2, 4 have is_read=False)
        assert stats["unread_count"] == 3

        # Mark one as read
        unread_alerts = [
            a for a in multiple_workflow_alerts if not a.is_read
        ]
        if unread_alerts:
            await client.patch(
                f"/api/v1/alerts/{unread_alerts[0].id}", json={"is_read": True}
            )

        # Check updated stats
        stats_response = await client.get("/api/v1/alerts/stats")
        stats = stats_response.json()
        assert stats["unread_count"] == 2

    @pytest.mark.asyncio
    async def test_rule_deletion_cleans_alerts(
        self, client: AsyncClient, cascade_test_rule: Rule, cascade_test_alerts: list[Alert]
    ):
        """Test that deleting a rule properly cascades to alerts."""
        # Verify initial state
        alerts_response = await client.get("/api/v1/alerts")
        assert alerts_response.json()["total"] == 3

        stats_response = await client.get("/api/v1/alerts/stats")
        assert stats_response.json()["total_alerts"] == 3

        # Delete the rule
        await client.delete(f"/api/v1/rules/{cascade_test_rule.id}")

        # Verify alerts are gone
        alerts_response = await client.get("/api/v1/alerts")
        assert alerts_response.json()["total"] == 0

        stats_response = await client.get("/api/v1/alerts/stats")
        assert stats_response.json()["total_alerts"] == 0
