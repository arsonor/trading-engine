"""Unit tests for rules API endpoints."""

import pytest
from httpx import AsyncClient

from app.models import Alert, Rule


class TestListRules:
    """Tests for GET /api/v1/rules endpoint."""

    @pytest.mark.asyncio
    async def test_list_rules_empty(self, client: AsyncClient):
        """Test listing rules when database is empty."""
        response = await client.get("/api/v1/rules")
        assert response.status_code == 200
        data = response.json()
        assert data == []

    @pytest.mark.asyncio
    async def test_list_rules_with_data(self, client: AsyncClient, sample_rule: Rule):
        """Test listing rules with data."""
        response = await client.get("/api/v1/rules")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Breakout Rule"
        assert data[0]["rule_type"] == "price"  # Valid RuleType enum value
        assert data[0]["is_active"] is True

    @pytest.mark.asyncio
    async def test_list_rules_sorted_by_priority(
        self, client: AsyncClient, sample_rule: Rule, sample_rule_inactive: Rule
    ):
        """Test rules are sorted by priority (descending) then name."""
        response = await client.get("/api/v1/rules")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # Higher priority first (10 > 5)
        assert data[0]["name"] == "Test Breakout Rule"
        assert data[1]["name"] == "Inactive Rule"

    @pytest.mark.asyncio
    async def test_list_rules_includes_alert_count(
        self, client: AsyncClient, sample_rule: Rule, sample_alert: Alert
    ):
        """Test that rule listing includes alert count."""
        response = await client.get("/api/v1/rules")
        assert response.status_code == 200
        data = response.json()
        # sample_alert is associated with sample_rule
        rule_data = next(r for r in data if r["id"] == sample_rule.id)
        assert rule_data["alerts_triggered"] == 1


class TestCreateRule:
    """Tests for POST /api/v1/rules endpoint."""

    @pytest.mark.asyncio
    async def test_create_rule_success(self, client: AsyncClient):
        """Test creating a new rule."""
        rule_data = {
            "name": "New Test Rule",
            "description": "A new rule for testing",
            "rule_type": "price",  # Valid RuleType enum value
            "config_yaml": "conditions:\n  - field: price\n    operator: '>'\n    value: 100",
            "is_active": True,
            "priority": 5,
        }
        response = await client.post("/api/v1/rules", json=rule_data)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Test Rule"
        assert data["description"] == "A new rule for testing"
        assert data["rule_type"] == "price"
        assert data["is_active"] is True
        assert data["priority"] == 5
        assert data["alerts_triggered"] == 0
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_rule_invalid_yaml(self, client: AsyncClient):
        """Test creating a rule with invalid YAML."""
        rule_data = {
            "name": "Bad YAML Rule",
            "rule_type": "price",  # Valid RuleType enum value
            "config_yaml": "invalid: yaml: content: [",  # Invalid YAML
            "is_active": True,
            "priority": 1,
        }
        response = await client.post("/api/v1/rules", json=rule_data)
        assert response.status_code == 400
        assert "invalid yaml" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_rule_yaml_not_object(self, client: AsyncClient):
        """Test creating a rule where YAML is not an object."""
        rule_data = {
            "name": "Array YAML Rule",
            "rule_type": "volume",  # Valid RuleType enum value
            "config_yaml": "- item1\n- item2",  # YAML array, not object
            "is_active": True,
            "priority": 1,
        }
        response = await client.post("/api/v1/rules", json=rule_data)
        assert response.status_code == 400
        assert "must be a yaml object" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_rule_duplicate_name(self, client: AsyncClient, sample_rule: Rule):
        """Test creating a rule with duplicate name."""
        rule_data = {
            "name": "Test Breakout Rule",  # Same name as sample_rule
            "rule_type": "gap",  # Valid RuleType enum value
            "config_yaml": "conditions: []",
            "is_active": True,
            "priority": 1,
        }
        response = await client.post("/api/v1/rules", json=rule_data)
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_rule_minimal(self, client: AsyncClient):
        """Test creating a rule with minimal required fields."""
        rule_data = {
            "name": "Minimal Rule",
            "rule_type": "technical",  # Valid RuleType enum value
            "config_yaml": "conditions: []",
        }
        response = await client.post("/api/v1/rules", json=rule_data)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Minimal Rule"
        assert data["is_active"] is True  # Default
        assert data["priority"] == 0  # Default


class TestGetRule:
    """Tests for GET /api/v1/rules/{rule_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_rule_success(self, client: AsyncClient, sample_rule: Rule):
        """Test getting a specific rule."""
        response = await client.get(f"/api/v1/rules/{sample_rule.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == sample_rule.id
        assert data["name"] == "Test Breakout Rule"
        assert data["rule_type"] == "price"  # Valid RuleType enum value
        assert "config_yaml" in data

    @pytest.mark.asyncio
    async def test_get_rule_not_found(self, client: AsyncClient):
        """Test getting non-existent rule returns 404."""
        response = await client.get("/api/v1/rules/99999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_rule_with_alerts_count(
        self, client: AsyncClient, sample_rule: Rule, sample_alert: Alert
    ):
        """Test rule includes alert count."""
        response = await client.get(f"/api/v1/rules/{sample_rule.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["alerts_triggered"] == 1


class TestUpdateRule:
    """Tests for PUT /api/v1/rules/{rule_id} endpoint."""

    @pytest.mark.asyncio
    async def test_update_rule_name(self, client: AsyncClient, sample_rule: Rule):
        """Test updating rule name."""
        response = await client.put(
            f"/api/v1/rules/{sample_rule.id}",
            json={"name": "Updated Rule Name"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Rule Name"

    @pytest.mark.asyncio
    async def test_update_rule_description(self, client: AsyncClient, sample_rule: Rule):
        """Test updating rule description."""
        response = await client.put(
            f"/api/v1/rules/{sample_rule.id}",
            json={"description": "New description"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "New description"

    @pytest.mark.asyncio
    async def test_update_rule_config_yaml(self, client: AsyncClient, sample_rule: Rule):
        """Test updating rule YAML config."""
        new_yaml = "conditions:\n  - field: volume\n    operator: '>'\n    value: 1000000"
        response = await client.put(
            f"/api/v1/rules/{sample_rule.id}",
            json={"config_yaml": new_yaml},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["config_yaml"] == new_yaml

    @pytest.mark.asyncio
    async def test_update_rule_invalid_yaml(self, client: AsyncClient, sample_rule: Rule):
        """Test updating rule with invalid YAML."""
        response = await client.put(
            f"/api/v1/rules/{sample_rule.id}",
            json={"config_yaml": "invalid: yaml: ["},
        )
        assert response.status_code == 400
        assert "invalid yaml" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_rule_duplicate_name(
        self, client: AsyncClient, sample_rule: Rule, sample_rule_inactive: Rule
    ):
        """Test updating rule to duplicate name fails."""
        response = await client.put(
            f"/api/v1/rules/{sample_rule.id}",
            json={"name": "Inactive Rule"},  # Name of sample_rule_inactive
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_rule_same_name_allowed(self, client: AsyncClient, sample_rule: Rule):
        """Test updating rule to keep same name is allowed."""
        response = await client.put(
            f"/api/v1/rules/{sample_rule.id}",
            json={"name": "Test Breakout Rule", "description": "Updated desc"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Breakout Rule"
        assert data["description"] == "Updated desc"

    @pytest.mark.asyncio
    async def test_update_rule_not_found(self, client: AsyncClient):
        """Test updating non-existent rule returns 404."""
        response = await client.put(
            "/api/v1/rules/99999",
            json={"name": "Ghost Rule"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_update_rule_priority(self, client: AsyncClient, sample_rule: Rule):
        """Test updating rule priority."""
        response = await client.put(
            f"/api/v1/rules/{sample_rule.id}",
            json={"priority": 100},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["priority"] == 100

    @pytest.mark.asyncio
    async def test_update_rule_is_active(self, client: AsyncClient, sample_rule: Rule):
        """Test updating rule active status."""
        response = await client.put(
            f"/api/v1/rules/{sample_rule.id}",
            json={"is_active": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False


class TestDeleteRule:
    """Tests for DELETE /api/v1/rules/{rule_id} endpoint."""

    @pytest.mark.asyncio
    async def test_delete_rule_success(self, client: AsyncClient, sample_rule: Rule):
        """Test deleting a rule."""
        response = await client.delete(f"/api/v1/rules/{sample_rule.id}")
        assert response.status_code == 204

        # Verify rule is deleted
        get_response = await client.get(f"/api/v1/rules/{sample_rule.id}")
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_rule_not_found(self, client: AsyncClient):
        """Test deleting non-existent rule returns 404."""
        response = await client.delete("/api/v1/rules/99999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_rule_cascades_alerts(
        self, client: AsyncClient, sample_rule: Rule, sample_alert: Alert
    ):
        """Test deleting a rule cascades to alerts (sets rule_id to NULL or deletes)."""
        alert_id = sample_alert.id
        rule_id = sample_rule.id

        # Delete the rule
        response = await client.delete(f"/api/v1/rules/{rule_id}")
        assert response.status_code == 204

        # Check if alert still exists (should be deleted due to cascade)
        # Based on the model, alerts are deleted with cascade="all, delete-orphan"
        alert_response = await client.get(f"/api/v1/alerts/{alert_id}")
        # Alert should be deleted due to cascade
        assert alert_response.status_code == 404


class TestToggleRule:
    """Tests for POST /api/v1/rules/{rule_id}/toggle endpoint."""

    @pytest.mark.asyncio
    async def test_toggle_rule_activate(
        self, client: AsyncClient, sample_rule_inactive: Rule
    ):
        """Test toggling inactive rule to active."""
        assert sample_rule_inactive.is_active is False

        response = await client.post(f"/api/v1/rules/{sample_rule_inactive.id}/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_toggle_rule_deactivate(self, client: AsyncClient, sample_rule: Rule):
        """Test toggling active rule to inactive."""
        assert sample_rule.is_active is True

        response = await client.post(f"/api/v1/rules/{sample_rule.id}/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False

    @pytest.mark.asyncio
    async def test_toggle_rule_twice(self, client: AsyncClient, sample_rule: Rule):
        """Test toggling rule twice returns to original state."""
        original_state = sample_rule.is_active

        # First toggle
        await client.post(f"/api/v1/rules/{sample_rule.id}/toggle")
        # Second toggle
        response = await client.post(f"/api/v1/rules/{sample_rule.id}/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] == original_state

    @pytest.mark.asyncio
    async def test_toggle_rule_not_found(self, client: AsyncClient):
        """Test toggling non-existent rule returns 404."""
        response = await client.post("/api/v1/rules/99999/toggle")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestValidateYamlConfig:
    """Tests for YAML validation helper function."""

    @pytest.mark.asyncio
    async def test_valid_yaml_object(self, client: AsyncClient):
        """Test valid YAML object is accepted."""
        rule_data = {
            "name": "Valid YAML Rule",
            "rule_type": "price",  # Valid RuleType enum value
            "config_yaml": "key: value\nnested:\n  foo: bar",
        }
        response = await client.post("/api/v1/rules", json=rule_data)
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_yaml_with_lists(self, client: AsyncClient):
        """Test YAML with lists inside object is accepted."""
        rule_data = {
            "name": "YAML Lists Rule",
            "rule_type": "volume",  # Valid RuleType enum value
            "config_yaml": "conditions:\n  - item1\n  - item2",
        }
        response = await client.post("/api/v1/rules", json=rule_data)
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_empty_yaml_object(self, client: AsyncClient):
        """Test empty YAML object is accepted."""
        rule_data = {
            "name": "Empty YAML Rule",
            "rule_type": "gap",  # Valid RuleType enum value
            "config_yaml": "{}",
        }
        response = await client.post("/api/v1/rules", json=rule_data)
        assert response.status_code == 201
