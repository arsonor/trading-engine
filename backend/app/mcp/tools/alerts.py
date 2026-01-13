"""Alert-related MCP tools.

Tools:
- explain_alert: Detailed explanation of why an alert triggered
- list_alerts: List recent alerts with optional filters
- get_alert_by_id: Get specific alert details
- mark_alert_read: Mark an alert as read
- get_alert_statistics: Alert stats for performance tracking
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.mcp.server import get_db_session, logger, mcp
from app.models.alert import Alert


@mcp.tool()
async def explain_alert(alert_id: int) -> str:
    """Explain why a specific alert was triggered.

    Provides detailed information about the alert including:
    - The rule that triggered it
    - Market conditions at trigger time
    - Entry price, stop loss, and target levels
    - Risk/reward analysis

    Args:
        alert_id: The ID of the alert to explain

    Returns:
        A detailed explanation of why the alert was triggered
    """
    logger.info(f"Explaining alert {alert_id}")

    async with get_db_session() as session:
        query = (
            select(Alert)
            .options(selectinload(Alert.rule))
            .where(Alert.id == alert_id)
        )
        result = await session.execute(query)
        alert = result.scalar_one_or_none()

        if not alert:
            return f"Alert with ID {alert_id} not found."

        # Build explanation
        lines = [
            f"# Alert #{alert.id}: {alert.symbol} - {alert.setup_type.upper()}",
            "",
            f"**Triggered at:** {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Status:** {'Read' if alert.is_read else 'Unread'}",
            "",
        ]

        # Rule information
        if alert.rule:
            lines.extend([
                "## Rule Details",
                f"**Rule Name:** {alert.rule.name}",
                f"**Rule Type:** {alert.rule.rule_type}",
            ])
            if alert.rule.description:
                lines.append(f"**Description:** {alert.rule.description}")
            lines.append("")

        # Price levels
        lines.extend([
            "## Price Levels",
            f"**Entry Price:** ${alert.entry_price:.2f}",
        ])

        if alert.stop_loss:
            stop_loss_pct = ((alert.entry_price - alert.stop_loss) / alert.entry_price) * 100
            lines.append(f"**Stop Loss:** ${alert.stop_loss:.2f} ({stop_loss_pct:.1f}% risk)")

        if alert.target_price:
            target_pct = ((alert.target_price - alert.entry_price) / alert.entry_price) * 100
            lines.append(f"**Target Price:** ${alert.target_price:.2f} ({target_pct:.1f}% potential)")

        # Risk/Reward ratio
        if alert.stop_loss and alert.target_price:
            risk = alert.entry_price - alert.stop_loss
            reward = alert.target_price - alert.entry_price
            if risk > 0:
                rr_ratio = reward / risk
                lines.append(f"**Risk/Reward Ratio:** {rr_ratio:.2f}:1")

        if alert.confidence_score is not None:
            lines.append(f"**Confidence Score:** {alert.confidence_score * 100:.0f}%")

        lines.append("")

        # Market data at trigger time
        if alert.market_data_json:
            lines.append("## Market Conditions at Trigger")
            md = alert.market_data_json

            if md.get("price"):
                lines.append(f"**Price:** ${md['price']:.2f}")
            if md.get("volume"):
                lines.append(f"**Volume:** {md['volume']:,}")
            if md.get("volume_ratio"):
                lines.append(f"**Volume Ratio:** {md['volume_ratio']:.1f}x average")
            if md.get("day_high"):
                lines.append(f"**Day High:** ${md['day_high']:.2f}")
            if md.get("day_low"):
                lines.append(f"**Day Low:** ${md['day_low']:.2f}")
            if md.get("pre_market_high"):
                lines.append(f"**Pre-Market High:** ${md['pre_market_high']:.2f}")
            if md.get("float_shares"):
                float_m = md["float_shares"] / 1_000_000
                lines.append(f"**Float:** {float_m:.1f}M shares")
            if md.get("short_interest"):
                lines.append(f"**Short Interest:** {md['short_interest'] * 100:.1f}%")

            lines.append("")

        # Setup type explanation
        lines.append("## Setup Type Explanation")
        setup_explanations = {
            "breakout": "A breakout alert occurs when price moves above a key resistance level with increased volume, suggesting potential continuation.",
            "volume_spike": "A volume spike alert triggers when trading volume exceeds normal levels significantly, often indicating institutional interest or news.",
            "gap_up": "A gap up alert occurs when a stock opens significantly higher than the previous close, potentially signaling bullish momentum.",
            "gap_down": "A gap down alert occurs when a stock opens significantly lower than the previous close, potentially signaling bearish momentum.",
            "momentum": "A momentum alert triggers when price shows strong directional movement with supporting volume patterns.",
        }
        explanation = setup_explanations.get(
            alert.setup_type.lower(),
            f"This is a {alert.setup_type} setup."
        )
        lines.append(explanation)

        return "\n".join(lines)


@mcp.tool()
async def list_alerts(
    symbol: Optional[str] = None,
    limit: int = 10,
    setup_type: Optional[str] = None,
    unread_only: bool = False,
) -> str:
    """List recent trading alerts.

    Args:
        symbol: Optional ticker symbol to filter by (e.g., "AAPL")
        limit: Maximum number of alerts to return (default 10, max 50)
        setup_type: Optional setup type filter (breakout, volume_spike, gap_up, gap_down, momentum)
        unread_only: If True, only show unread alerts

    Returns:
        A formatted list of recent alerts
    """
    logger.info(
        f"Listing alerts: symbol={symbol}, limit={limit}, "
        f"setup_type={setup_type}, unread_only={unread_only}"
    )

    # Clamp limit
    limit = min(max(1, limit), 50)

    async with get_db_session() as session:
        query = select(Alert).options(selectinload(Alert.rule))

        if symbol:
            query = query.where(Alert.symbol == symbol.upper())
        if setup_type:
            query = query.where(Alert.setup_type == setup_type.lower())
        if unread_only:
            query = query.where(Alert.is_read == False)  # noqa: E712

        query = query.order_by(Alert.timestamp.desc()).limit(limit)

        result = await session.execute(query)
        alerts = result.scalars().all()

        if not alerts:
            filter_desc = []
            if symbol:
                filter_desc.append(f"symbol={symbol.upper()}")
            if setup_type:
                filter_desc.append(f"type={setup_type}")
            if unread_only:
                filter_desc.append("unread only")
            filter_str = f" ({', '.join(filter_desc)})" if filter_desc else ""
            return f"No alerts found{filter_str}."

        lines = [f"# Recent Alerts ({len(alerts)} shown)", ""]

        for alert in alerts:
            status = "🔵" if not alert.is_read else "⚪"
            rule_name = f" [{alert.rule.name}]" if alert.rule else ""
            confidence = f" ({alert.confidence_score * 100:.0f}%)" if alert.confidence_score else ""

            lines.append(
                f"{status} **#{alert.id}** {alert.symbol} - {alert.setup_type.upper()}{rule_name}{confidence}"
            )
            lines.append(
                f"   Entry: ${alert.entry_price:.2f} | {alert.timestamp.strftime('%Y-%m-%d %H:%M')}"
            )

            # Add stop/target if available
            price_info = []
            if alert.stop_loss:
                price_info.append(f"SL: ${alert.stop_loss:.2f}")
            if alert.target_price:
                price_info.append(f"TP: ${alert.target_price:.2f}")
            if price_info:
                lines.append(f"   {' | '.join(price_info)}")

            lines.append("")

        # Add summary
        unread_count = sum(1 for a in alerts if not a.is_read)
        if unread_count > 0:
            lines.append(f"*{unread_count} unread alert(s)*")

        return "\n".join(lines)


@mcp.tool()
async def get_alert_statistics(days: int = 7) -> str:
    """Get alert statistics and performance metrics.

    Args:
        days: Number of days to analyze (default 7, max 90)

    Returns:
        A summary of alert statistics including counts by type, symbol, and trends
    """
    logger.info(f"Getting alert statistics for {days} days")

    # Clamp days
    days = min(max(1, days), 90)
    start_date = datetime.utcnow() - timedelta(days=days)

    async with get_db_session() as session:
        # Total alerts in period
        total_query = select(func.count(Alert.id)).where(Alert.timestamp >= start_date)
        total_alerts = (await session.execute(total_query)).scalar() or 0

        # Alerts today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_query = select(func.count(Alert.id)).where(Alert.timestamp >= today_start)
        alerts_today = (await session.execute(today_query)).scalar() or 0

        # Unread count
        unread_query = select(func.count(Alert.id)).where(Alert.is_read == False)  # noqa: E712
        unread_count = (await session.execute(unread_query)).scalar() or 0

        # By setup type (in period)
        by_type_query = (
            select(Alert.setup_type, func.count(Alert.id))
            .where(Alert.timestamp >= start_date)
            .group_by(Alert.setup_type)
            .order_by(func.count(Alert.id).desc())
        )
        by_type_result = await session.execute(by_type_query)
        by_setup_type = {row[0]: row[1] for row in by_type_result.all()}

        # By symbol (top 10 in period)
        by_symbol_query = (
            select(Alert.symbol, func.count(Alert.id))
            .where(Alert.timestamp >= start_date)
            .group_by(Alert.symbol)
            .order_by(func.count(Alert.id).desc())
            .limit(10)
        )
        by_symbol_result = await session.execute(by_symbol_query)
        by_symbol = [(row[0], row[1]) for row in by_symbol_result.all()]

        # Average confidence
        avg_conf_query = (
            select(func.avg(Alert.confidence_score))
            .where(Alert.timestamp >= start_date)
            .where(Alert.confidence_score.isnot(None))
        )
        avg_confidence = (await session.execute(avg_conf_query)).scalar()

        # High confidence alerts (>= 0.8)
        high_conf_query = (
            select(func.count(Alert.id))
            .where(Alert.timestamp >= start_date)
            .where(Alert.confidence_score >= 0.8)
        )
        high_conf_count = (await session.execute(high_conf_query)).scalar() or 0

        # Daily average
        daily_avg = total_alerts / days if days > 0 else 0

        # Build report
        lines = [
            f"# Alert Statistics ({days} Day{'s' if days != 1 else ''})",
            "",
            "## Overview",
            f"- **Total Alerts:** {total_alerts}",
            f"- **Daily Average:** {daily_avg:.1f} alerts/day",
            f"- **Today:** {alerts_today} alert{'s' if alerts_today != 1 else ''}",
            f"- **Unread:** {unread_count}",
            "",
        ]

        if avg_confidence is not None:
            lines.extend([
                "## Confidence Metrics",
                f"- **Average Confidence:** {avg_confidence * 100:.1f}%",
                f"- **High Confidence Alerts (≥80%):** {high_conf_count}",
                "",
            ])

        if by_setup_type:
            lines.append("## By Setup Type")
            for setup_type, count in by_setup_type.items():
                pct = (count / total_alerts * 100) if total_alerts > 0 else 0
                lines.append(f"- **{setup_type.upper()}:** {count} ({pct:.1f}%)")
            lines.append("")

        if by_symbol:
            lines.append("## Top Symbols")
            for symbol, count in by_symbol:
                pct = (count / total_alerts * 100) if total_alerts > 0 else 0
                lines.append(f"- **{symbol}:** {count} alert{'s' if count != 1 else ''} ({pct:.1f}%)")
            lines.append("")

        return "\n".join(lines)


@mcp.tool()
async def get_alert_by_id(alert_id: int) -> str:
    """Get details for a specific alert by ID.

    Args:
        alert_id: The ID of the alert to retrieve

    Returns:
        Alert details in a formatted string
    """
    logger.info(f"Getting alert by ID: {alert_id}")

    async with get_db_session() as session:
        query = (
            select(Alert)
            .options(selectinload(Alert.rule))
            .where(Alert.id == alert_id)
        )
        result = await session.execute(query)
        alert = result.scalar_one_or_none()

        if not alert:
            return f"Alert with ID {alert_id} not found."

        # Build response
        lines = [
            f"# Alert #{alert.id}",
            "",
            f"**Symbol:** {alert.symbol}",
            f"**Setup Type:** {alert.setup_type.upper()}",
            f"**Status:** {'Read' if alert.is_read else 'Unread'}",
            f"**Timestamp:** {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "## Price Levels",
            f"**Entry Price:** ${alert.entry_price:.2f}",
        ]

        if alert.stop_loss:
            lines.append(f"**Stop Loss:** ${alert.stop_loss:.2f}")
        if alert.target_price:
            lines.append(f"**Target Price:** ${alert.target_price:.2f}")
        if alert.confidence_score is not None:
            lines.append(f"**Confidence:** {alert.confidence_score * 100:.0f}%")

        if alert.rule:
            lines.extend([
                "",
                "## Rule",
                f"**Name:** {alert.rule.name}",
                f"**Type:** {alert.rule.rule_type}",
            ])

        if alert.market_data_json:
            lines.extend(["", "## Market Data"])
            md = alert.market_data_json
            if md.get("price"):
                lines.append(f"**Price:** ${md['price']:.2f}")
            if md.get("volume"):
                lines.append(f"**Volume:** {md['volume']:,}")
            if md.get("volume_ratio"):
                lines.append(f"**Volume Ratio:** {md['volume_ratio']:.1f}x")

        return "\n".join(lines)


@mcp.tool()
async def mark_alert_read(alert_id: int) -> str:
    """Mark an alert as read.

    Args:
        alert_id: The ID of the alert to mark as read

    Returns:
        Confirmation message
    """
    logger.info(f"Marking alert {alert_id} as read")

    async with get_db_session() as session:
        query = select(Alert).where(Alert.id == alert_id)
        result = await session.execute(query)
        alert = result.scalar_one_or_none()

        if not alert:
            return f"Alert with ID {alert_id} not found."

        if alert.is_read:
            return f"Alert #{alert_id} ({alert.symbol} - {alert.setup_type.upper()}) was already marked as read."

        alert.is_read = True
        await session.commit()

        return f"Alert #{alert_id} ({alert.symbol} - {alert.setup_type.upper()}) has been marked as read."
