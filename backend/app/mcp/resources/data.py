"""MCP resources for read-only data access.

Resources:
- alerts://recent - Recent alerts
- alerts://unread - Unread alerts
- rules://active - Active rules configuration
- stats://daily - Daily statistics summary
- watchlist://current - Current watchlist
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.mcp.server import get_db_session, logger, mcp
from app.models.alert import Alert
from app.models.rule import Rule
from app.models.watchlist import Watchlist


@mcp.resource("alerts://recent")
async def get_recent_alerts() -> str:
    """Get the 20 most recent alerts.

    Returns a quick summary of recent trading alerts for easy reference.
    """
    logger.info("Resource: alerts://recent")

    async with get_db_session() as session:
        query = (
            select(Alert)
            .options(selectinload(Alert.rule))
            .order_by(Alert.timestamp.desc())
            .limit(20)
        )
        result = await session.execute(query)
        alerts = result.scalars().all()

        if not alerts:
            return "No recent alerts."

        lines = ["Recent Alerts (Last 20)", "=" * 30, ""]

        for alert in alerts:
            status = "[UNREAD]" if not alert.is_read else "[read]"
            rule_name = f" ({alert.rule.name})" if alert.rule else ""
            conf = f" {alert.confidence_score * 100:.0f}%" if alert.confidence_score else ""

            lines.append(
                f"{status} #{alert.id} {alert.symbol} {alert.setup_type.upper()}{rule_name}{conf}"
            )
            lines.append(
                f"    ${alert.entry_price:.2f} @ {alert.timestamp.strftime('%Y-%m-%d %H:%M')}"
            )

        return "\n".join(lines)


@mcp.resource("alerts://unread")
async def get_unread_alerts() -> str:
    """Get all unread alerts.

    Returns alerts that haven't been marked as read yet.
    """
    logger.info("Resource: alerts://unread")

    async with get_db_session() as session:
        query = (
            select(Alert)
            .options(selectinload(Alert.rule))
            .where(Alert.is_read == False)  # noqa: E712
            .order_by(Alert.timestamp.desc())
            .limit(50)
        )
        result = await session.execute(query)
        alerts = result.scalars().all()

        if not alerts:
            return "No unread alerts. All caught up!"

        lines = [f"Unread Alerts ({len(alerts)})", "=" * 30, ""]

        for alert in alerts:
            rule_name = f" ({alert.rule.name})" if alert.rule else ""
            conf = f" {alert.confidence_score * 100:.0f}%" if alert.confidence_score else ""

            lines.append(
                f"#{alert.id} {alert.symbol} {alert.setup_type.upper()}{rule_name}{conf}"
            )
            lines.append(
                f"    Entry: ${alert.entry_price:.2f} @ {alert.timestamp.strftime('%Y-%m-%d %H:%M')}"
            )

            if alert.stop_loss and alert.target_price:
                lines.append(f"    SL: ${alert.stop_loss:.2f} | TP: ${alert.target_price:.2f}")

            lines.append("")

        return "\n".join(lines)


@mcp.resource("rules://active")
async def get_active_rules() -> str:
    """Get all active trading rules.

    Returns the current active rules configuration.
    """
    logger.info("Resource: rules://active")

    async with get_db_session() as session:
        query = (
            select(Rule)
            .where(Rule.is_active == True)  # noqa: E712
            .order_by(Rule.priority.desc(), Rule.name)
        )
        result = await session.execute(query)
        rules = result.scalars().all()

        if not rules:
            return "No active rules configured."

        # Get alert counts
        rule_ids = [r.id for r in rules]
        counts_query = (
            select(Alert.rule_id, func.count(Alert.id))
            .where(Alert.rule_id.in_(rule_ids))
            .group_by(Alert.rule_id)
        )
        counts_result = await session.execute(counts_query)
        counts = {row[0]: row[1] for row in counts_result.all()}

        lines = [f"Active Trading Rules ({len(rules)})", "=" * 30, ""]

        for rule in rules:
            alert_count = counts.get(rule.id, 0)
            lines.append(f"[{rule.priority:2d}] {rule.name} ({rule.rule_type})")
            lines.append(f"     Alerts: {alert_count}")
            if rule.description:
                lines.append(f"     {rule.description}")
            lines.append("")

        return "\n".join(lines)


@mcp.resource("stats://daily")
async def get_daily_stats() -> str:
    """Get daily statistics summary.

    Returns key metrics for today and recent trends.
    """
    logger.info("Resource: stats://daily")

    async with get_db_session() as session:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = datetime.utcnow() - timedelta(days=7)

        # Today's alerts
        today_query = select(func.count(Alert.id)).where(Alert.timestamp >= today_start)
        alerts_today = (await session.execute(today_query)).scalar() or 0

        # This week's alerts
        week_query = select(func.count(Alert.id)).where(Alert.timestamp >= week_ago)
        alerts_week = (await session.execute(week_query)).scalar() or 0

        # Unread count
        unread_query = select(func.count(Alert.id)).where(Alert.is_read == False)  # noqa: E712
        unread_count = (await session.execute(unread_query)).scalar() or 0

        # Total alerts
        total_query = select(func.count(Alert.id))
        total_alerts = (await session.execute(total_query)).scalar() or 0

        # Active rules
        rules_query = select(func.count(Rule.id)).where(Rule.is_active == True)  # noqa: E712
        active_rules = (await session.execute(rules_query)).scalar() or 0

        # Watchlist size
        watchlist_query = select(func.count(Watchlist.id)).where(
            Watchlist.is_active == True  # noqa: E712
        )
        watchlist_size = (await session.execute(watchlist_query)).scalar() or 0

        # Today's setup type breakdown
        today_types_query = (
            select(Alert.setup_type, func.count(Alert.id))
            .where(Alert.timestamp >= today_start)
            .group_by(Alert.setup_type)
        )
        today_types_result = await session.execute(today_types_query)
        today_types = {row[0]: row[1] for row in today_types_result.all()}

        # Average confidence today
        avg_conf_query = (
            select(func.avg(Alert.confidence_score))
            .where(Alert.timestamp >= today_start)
            .where(Alert.confidence_score.isnot(None))
        )
        avg_confidence = (await session.execute(avg_conf_query)).scalar()

        lines = [
            "Daily Statistics",
            "=" * 30,
            f"Date: {datetime.utcnow().strftime('%Y-%m-%d')}",
            "",
            "ALERTS",
            f"  Today: {alerts_today}",
            f"  This Week: {alerts_week}",
            f"  Unread: {unread_count}",
            f"  Total: {total_alerts}",
            "",
            "CONFIGURATION",
            f"  Active Rules: {active_rules}",
            f"  Watchlist: {watchlist_size} symbols",
            "",
        ]

        if today_types:
            lines.append("TODAY'S BREAKDOWN")
            for setup_type, count in sorted(today_types.items(), key=lambda x: -x[1]):
                lines.append(f"  {setup_type.upper()}: {count}")
            lines.append("")

        if avg_confidence is not None:
            lines.append(f"Avg Confidence Today: {avg_confidence * 100:.1f}%")

        return "\n".join(lines)


@mcp.resource("watchlist://current")
async def get_current_watchlist() -> str:
    """Get the current watchlist.

    Returns all symbols being monitored.
    """
    logger.info("Resource: watchlist://current")

    async with get_db_session() as session:
        query = select(Watchlist).order_by(Watchlist.added_at.desc())
        result = await session.execute(query)
        items = result.scalars().all()

        if not items:
            return "Watchlist is empty."

        # Get recent alert counts
        week_ago = datetime.utcnow() - timedelta(days=7)
        symbols = [item.symbol for item in items]
        counts_query = (
            select(Alert.symbol, func.count(Alert.id))
            .where(Alert.symbol.in_(symbols))
            .where(Alert.timestamp >= week_ago)
            .group_by(Alert.symbol)
        )
        counts_result = await session.execute(counts_query)
        recent_counts = {row[0]: row[1] for row in counts_result.all()}

        active_items = [i for i in items if i.is_active]
        inactive_items = [i for i in items if not i.is_active]

        lines = [f"Watchlist ({len(items)} symbols)", "=" * 30, ""]

        if active_items:
            lines.append("ACTIVE:")
            for item in active_items:
                recent = recent_counts.get(item.symbol, 0)
                alert_info = f" ({recent} alerts this week)" if recent > 0 else ""
                lines.append(f"  {item.symbol}{alert_info}")
                if item.notes:
                    lines.append(f"    Note: {item.notes}")
            lines.append("")

        if inactive_items:
            lines.append("INACTIVE:")
            for item in inactive_items:
                lines.append(f"  {item.symbol}")
            lines.append("")

        return "\n".join(lines)
