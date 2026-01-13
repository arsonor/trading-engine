"""Rule management MCP tools.

Tools:
- list_rules: List all trading rules
- get_rule: Get rule details with config
- create_rule_from_description: Create rule from natural language description
- toggle_rule: Enable/disable rule
- delete_rule: Remove rule
"""

import yaml
from sqlalchemy import func, select

from app.mcp.server import get_db_session, logger, mcp
from app.models.alert import Alert
from app.models.rule import Rule


@mcp.tool()
async def list_rules(active_only: bool = False) -> str:
    """List all trading rules.

    Args:
        active_only: If True, only show active (enabled) rules

    Returns:
        A formatted list of all rules with their status and alert counts
    """
    logger.info(f"Listing rules: active_only={active_only}")

    async with get_db_session() as session:
        query = select(Rule).order_by(Rule.priority.desc(), Rule.name)

        if active_only:
            query = query.where(Rule.is_active == True)  # noqa: E712

        result = await session.execute(query)
        rules = result.scalars().all()

        if not rules:
            return "No rules found." if not active_only else "No active rules found."

        # Get alert counts for each rule
        rule_ids = [r.id for r in rules]
        counts = {}
        if rule_ids:
            counts_query = (
                select(Alert.rule_id, func.count(Alert.id))
                .where(Alert.rule_id.in_(rule_ids))
                .group_by(Alert.rule_id)
            )
            counts_result = await session.execute(counts_query)
            counts = {row[0]: row[1] for row in counts_result.all()}

        lines = [f"# Trading Rules ({len(rules)} total)", ""]

        for rule in rules:
            status = "✅" if rule.is_active else "❌"
            alert_count = counts.get(rule.id, 0)

            lines.append(f"{status} **#{rule.id} {rule.name}** (Priority: {rule.priority})")
            lines.append(f"   Type: {rule.rule_type} | Alerts: {alert_count}")
            if rule.description:
                lines.append(f"   {rule.description}")
            lines.append("")

        # Summary
        active_count = sum(1 for r in rules if r.is_active)
        total_alerts = sum(counts.values())
        lines.extend([
            "---",
            f"**Active:** {active_count}/{len(rules)} | **Total Alerts Generated:** {total_alerts}",
        ])

        return "\n".join(lines)


@mcp.tool()
async def get_rule(rule_id: int) -> str:
    """Get detailed information about a specific rule.

    Args:
        rule_id: The ID of the rule to retrieve

    Returns:
        Detailed rule information including configuration
    """
    logger.info(f"Getting rule: {rule_id}")

    async with get_db_session() as session:
        query = select(Rule).where(Rule.id == rule_id)
        result = await session.execute(query)
        rule = result.scalar_one_or_none()

        if not rule:
            return f"Rule with ID {rule_id} not found."

        # Get alert count
        count_query = select(func.count(Alert.id)).where(Alert.rule_id == rule_id)
        alerts_triggered = (await session.execute(count_query)).scalar() or 0

        lines = [
            f"# Rule #{rule.id}: {rule.name}",
            "",
            f"**Status:** {'Active' if rule.is_active else 'Inactive'}",
            f"**Type:** {rule.rule_type}",
            f"**Priority:** {rule.priority}",
            f"**Alerts Triggered:** {alerts_triggered}",
            "",
        ]

        if rule.description:
            lines.extend([
                "## Description",
                rule.description,
                "",
            ])

        lines.extend([
            "## Configuration (YAML)",
            "```yaml",
            rule.config_yaml,
            "```",
            "",
            "## Metadata",
            f"**Created:** {rule.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Updated:** {rule.updated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        ])

        return "\n".join(lines)


@mcp.tool()
async def create_rule_from_description(
    name: str,
    description: str,
    rule_type: str,
    conditions: str,
    stop_loss_percent: float = -3.0,
    target_percent: float = 6.0,
    priority: int = 10,
) -> str:
    """Create a new trading rule from a natural language description.

    This tool helps create rules by generating the proper YAML configuration
    from simpler inputs.

    Args:
        name: Unique name for the rule (e.g., "high_volume_breakout")
        description: Human-readable description of what the rule detects
        rule_type: Type of rule - one of: price, volume, gap, technical
        conditions: Natural language conditions (e.g., "volume_ratio > 2.0 and price_change > 3%")
        stop_loss_percent: Stop loss percentage (negative, default -3.0)
        target_percent: Target price percentage (positive, default 6.0)
        priority: Rule priority (higher = checked first, default 10)

    Returns:
        Confirmation with the created rule details or error message
    """
    logger.info(f"Creating rule from description: {name}")

    # Validate rule_type
    valid_types = ["price", "volume", "gap", "technical"]
    if rule_type.lower() not in valid_types:
        return f"Invalid rule_type '{rule_type}'. Must be one of: {', '.join(valid_types)}"

    # Parse conditions from natural language
    parsed_conditions = _parse_conditions(conditions)

    if not parsed_conditions:
        return (
            "Could not parse conditions. Please use format like:\n"
            "- 'volume_ratio > 2.0'\n"
            "- 'price_change_percent > 5 and volume_ratio > 1.5'\n"
            "- 'float_shares < 20000000'"
        )

    # Build YAML config
    config = {
        "conditions": parsed_conditions,
        "targets": {
            "stop_loss_percent": stop_loss_percent,
            "target_percent": target_percent,
        },
        "confidence": {
            "base_score": 0.70,
        },
    }

    config_yaml = yaml.dump(config, default_flow_style=False, sort_keys=False)

    async with get_db_session() as session:
        # Check for duplicate name
        existing_query = select(Rule).where(Rule.name == name)
        existing = (await session.execute(existing_query)).scalar_one_or_none()
        if existing:
            return f"A rule with name '{name}' already exists (ID: {existing.id})."

        # Create rule
        rule = Rule(
            name=name,
            description=description,
            rule_type=rule_type.lower(),
            config_yaml=config_yaml,
            is_active=True,
            priority=priority,
        )

        session.add(rule)
        await session.commit()
        await session.refresh(rule)

        lines = [
            f"# Rule Created Successfully",
            "",
            f"**ID:** {rule.id}",
            f"**Name:** {rule.name}",
            f"**Type:** {rule.rule_type}",
            f"**Status:** Active",
            f"**Priority:** {rule.priority}",
            "",
            "## Description",
            description,
            "",
            "## Generated Configuration",
            "```yaml",
            config_yaml,
            "```",
            "",
            "The rule is now active and will start generating alerts when conditions are met.",
        ]

        return "\n".join(lines)


def _parse_conditions(conditions_str: str) -> list:
    """Parse natural language conditions into structured format.

    Supports formats like:
    - "volume_ratio > 2.0"
    - "price > 100 and volume_ratio > 1.5"
    - "float_shares < 20000000"
    """
    import re

    conditions = []

    # Split by 'and' (case insensitive)
    parts = re.split(r'\s+and\s+', conditions_str, flags=re.IGNORECASE)

    # Pattern for condition: field operator value
    pattern = r'(\w+)\s*([<>=!]+)\s*([\d.]+|"\w+"|\w+)'

    for part in parts:
        match = re.search(pattern, part.strip())
        if match:
            field = match.group(1)
            operator = match.group(2)
            value = match.group(3)

            # Normalize operator
            op_map = {
                ">=": ">=",
                "<=": "<=",
                ">": ">",
                "<": "<",
                "==": "=",
                "=": "=",
                "!=": "!=",
            }
            operator = op_map.get(operator, operator)

            # Try to convert value to number
            try:
                if "." in value:
                    value = float(value)
                else:
                    value = int(value)
            except ValueError:
                # Keep as string (could be a reference like "sma_20")
                pass

            conditions.append({
                "field": field,
                "operator": operator,
                "value": value,
            })

    return conditions


@mcp.tool()
async def toggle_rule(rule_id: int) -> str:
    """Toggle a rule's active status (enable/disable).

    Args:
        rule_id: The ID of the rule to toggle

    Returns:
        Confirmation of the new status
    """
    logger.info(f"Toggling rule: {rule_id}")

    async with get_db_session() as session:
        query = select(Rule).where(Rule.id == rule_id)
        result = await session.execute(query)
        rule = result.scalar_one_or_none()

        if not rule:
            return f"Rule with ID {rule_id} not found."

        old_status = "Active" if rule.is_active else "Inactive"
        rule.is_active = not rule.is_active
        new_status = "Active" if rule.is_active else "Inactive"

        await session.commit()

        status_icon = "✅" if rule.is_active else "❌"
        return (
            f"{status_icon} Rule **#{rule.id} {rule.name}** has been toggled.\n\n"
            f"**Previous Status:** {old_status}\n"
            f"**New Status:** {new_status}\n\n"
            f"{'The rule will now generate alerts when conditions are met.' if rule.is_active else 'The rule will no longer generate alerts.'}"
        )


@mcp.tool()
async def delete_rule(rule_id: int) -> str:
    """Delete a trading rule.

    Warning: This will permanently remove the rule. Associated alerts will
    have their rule_id set to NULL but will not be deleted.

    Args:
        rule_id: The ID of the rule to delete

    Returns:
        Confirmation of deletion or error message
    """
    logger.info(f"Deleting rule: {rule_id}")

    async with get_db_session() as session:
        query = select(Rule).where(Rule.id == rule_id)
        result = await session.execute(query)
        rule = result.scalar_one_or_none()

        if not rule:
            return f"Rule with ID {rule_id} not found."

        # Get alert count before deletion
        count_query = select(func.count(Alert.id)).where(Alert.rule_id == rule_id)
        alerts_count = (await session.execute(count_query)).scalar() or 0

        rule_name = rule.name
        rule_type = rule.rule_type

        await session.delete(rule)
        await session.commit()

        lines = [
            f"# Rule Deleted",
            "",
            f"**ID:** {rule_id}",
            f"**Name:** {rule_name}",
            f"**Type:** {rule_type}",
            "",
        ]

        if alerts_count > 0:
            lines.append(
                f"Note: {alerts_count} alert(s) were associated with this rule. "
                f"They have been preserved but are no longer linked to a rule."
            )
        else:
            lines.append("No alerts were associated with this rule.")

        return "\n".join(lines)
