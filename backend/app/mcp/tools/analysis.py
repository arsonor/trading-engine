"""Analysis MCP tools.

Tools:
- analyze_watchlist: Analyze all watched stocks for signals
- get_symbol_analysis: Deep analysis of single symbol
- compare_symbols: Compare multiple symbols
- get_top_performers: Best performing alerts
"""

from datetime import datetime, timedelta
from typing import List

from sqlalchemy import select

from app.mcp.server import get_db_session, logger, mcp
from app.models.alert import Alert
from app.models.watchlist import Watchlist


@mcp.tool()
async def analyze_watchlist() -> str:
    """Analyze all watched stocks and return bullish/bearish signals.

    Examines recent alerts for each symbol in the watchlist to determine
    overall market sentiment and highlight notable patterns.

    Returns:
        Analysis of watchlist symbols with signal summaries
    """
    logger.info("Analyzing watchlist")

    async with get_db_session() as session:
        # Get active watchlist items
        watchlist_query = select(Watchlist).where(Watchlist.is_active == True)  # noqa: E712
        result = await session.execute(watchlist_query)
        watchlist_items = result.scalars().all()

        if not watchlist_items:
            return "No symbols in watchlist. Add symbols to analyze."

        symbols = [item.symbol for item in watchlist_items]

        # Get alerts from last 7 days for watchlist symbols
        week_ago = datetime.utcnow() - timedelta(days=7)
        alerts_query = (
            select(Alert)
            .where(Alert.symbol.in_(symbols))
            .where(Alert.timestamp >= week_ago)
            .order_by(Alert.timestamp.desc())
        )
        alerts_result = await session.execute(alerts_query)
        alerts = alerts_result.scalars().all()

        # Group alerts by symbol
        alerts_by_symbol = {}
        for alert in alerts:
            if alert.symbol not in alerts_by_symbol:
                alerts_by_symbol[alert.symbol] = []
            alerts_by_symbol[alert.symbol].append(alert)

        lines = [
            "# Watchlist Analysis",
            f"*{len(symbols)} symbols analyzed | Last 7 days*",
            "",
        ]

        bullish_symbols = []
        bearish_symbols = []
        neutral_symbols = []

        for item in watchlist_items:
            symbol = item.symbol
            symbol_alerts = alerts_by_symbol.get(symbol, [])

            if not symbol_alerts:
                neutral_symbols.append((symbol, "No recent alerts", item.notes))
                continue

            # Analyze alerts for this symbol
            analysis = _analyze_symbol_alerts(symbol_alerts)

            if analysis["signal"] == "bullish":
                bullish_symbols.append((symbol, analysis["summary"], item.notes))
            elif analysis["signal"] == "bearish":
                bearish_symbols.append((symbol, analysis["summary"], item.notes))
            else:
                neutral_symbols.append((symbol, analysis["summary"], item.notes))

        # Bullish section
        if bullish_symbols:
            lines.extend([
                "## 🟢 Bullish Signals",
                "",
            ])
            for symbol, summary, notes in bullish_symbols:
                lines.append(f"**{symbol}** - {summary}")
                if notes:
                    lines.append(f"   *Note: {notes}*")
            lines.append("")

        # Bearish section
        if bearish_symbols:
            lines.extend([
                "## 🔴 Bearish Signals",
                "",
            ])
            for symbol, summary, notes in bearish_symbols:
                lines.append(f"**{symbol}** - {summary}")
                if notes:
                    lines.append(f"   *Note: {notes}*")
            lines.append("")

        # Neutral section
        if neutral_symbols:
            lines.extend([
                "## ⚪ Neutral/No Activity",
                "",
            ])
            for symbol, summary, notes in neutral_symbols:
                lines.append(f"**{symbol}** - {summary}")
                if notes:
                    lines.append(f"   *Note: {notes}*")
            lines.append("")

        # Summary
        lines.extend([
            "---",
            f"**Summary:** {len(bullish_symbols)} bullish | "
            f"{len(bearish_symbols)} bearish | {len(neutral_symbols)} neutral",
        ])

        return "\n".join(lines)


def _analyze_symbol_alerts(alerts: list) -> dict:
    """Analyze alerts for a symbol and determine signal."""
    if not alerts:
        return {"signal": "neutral", "summary": "No recent alerts"}

    # Count setup types
    setup_counts = {}
    total_confidence = 0
    confidence_count = 0

    for alert in alerts:
        setup_type = alert.setup_type
        setup_counts[setup_type] = setup_counts.get(setup_type, 0) + 1
        if alert.confidence_score:
            total_confidence += alert.confidence_score
            confidence_count += 1

    avg_confidence = total_confidence / confidence_count if confidence_count > 0 else 0

    # Determine signal based on setup types
    bullish_setups = {"breakout", "gap_up", "momentum", "volume_spike"}
    bearish_setups = {"gap_down"}

    bullish_count = sum(setup_counts.get(s, 0) for s in bullish_setups)
    bearish_count = sum(setup_counts.get(s, 0) for s in bearish_setups)

    # Build summary
    most_common = max(setup_counts.items(), key=lambda x: x[1])
    summary_parts = [
        f"{len(alerts)} alert(s)",
        f"mostly {most_common[0].upper()}",
    ]
    if avg_confidence > 0:
        summary_parts.append(f"{avg_confidence * 100:.0f}% avg confidence")

    summary = ", ".join(summary_parts)

    # Determine overall signal
    if bullish_count > bearish_count and avg_confidence >= 0.6:
        signal = "bullish"
    elif bearish_count > bullish_count:
        signal = "bearish"
    else:
        signal = "neutral"

    return {"signal": signal, "summary": summary}


@mcp.tool()
async def get_symbol_analysis(symbol: str) -> str:
    """Get deep analysis of a single symbol.

    Provides comprehensive analysis including:
    - Recent alert history
    - Setup type distribution
    - Confidence trends
    - Key price levels from alerts

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")

    Returns:
        Detailed analysis of the symbol
    """
    symbol = symbol.upper()
    logger.info(f"Analyzing symbol: {symbol}")

    async with get_db_session() as session:
        # Get alerts for this symbol (last 30 days)
        month_ago = datetime.utcnow() - timedelta(days=30)
        alerts_query = (
            select(Alert)
            .where(Alert.symbol == symbol)
            .where(Alert.timestamp >= month_ago)
            .order_by(Alert.timestamp.desc())
        )
        result = await session.execute(alerts_query)
        alerts = result.scalars().all()

        # Check if symbol is in watchlist
        watchlist_query = select(Watchlist).where(Watchlist.symbol == symbol)
        watchlist_result = await session.execute(watchlist_query)
        watchlist_item = watchlist_result.scalar_one_or_none()

        if not alerts:
            watchlist_status = "In watchlist" if watchlist_item else "Not in watchlist"
            return f"# {symbol} Analysis\n\nNo alerts found in the last 30 days.\n\n*{watchlist_status}*"

        # Gather statistics
        setup_counts = {}
        confidence_scores = []
        entry_prices = []
        stop_losses = []
        targets = []

        for alert in alerts:
            setup_counts[alert.setup_type] = setup_counts.get(alert.setup_type, 0) + 1
            if alert.confidence_score:
                confidence_scores.append(alert.confidence_score)
            entry_prices.append(alert.entry_price)
            if alert.stop_loss:
                stop_losses.append(alert.stop_loss)
            if alert.target_price:
                targets.append(alert.target_price)

        # Calculate metrics
        avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
        avg_entry = sum(entry_prices) / len(entry_prices)
        price_range = (min(entry_prices), max(entry_prices))

        # Recent trend (last 7 days vs previous)
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_alerts = [a for a in alerts if a.timestamp >= week_ago]
        older_alerts = [a for a in alerts if a.timestamp < week_ago]

        lines = [
            f"# {symbol} Analysis",
            "",
            f"*Last 30 days | {'In watchlist' if watchlist_item else 'Not in watchlist'}*",
            "",
            "## Overview",
            f"- **Total Alerts:** {len(alerts)}",
            f"- **Last 7 Days:** {len(recent_alerts)} alerts",
            f"- **Average Confidence:** {avg_confidence * 100:.1f}%" if confidence_scores else "- **Average Confidence:** N/A",
            "",
            "## Price Levels",
            f"- **Average Entry:** ${avg_entry:.2f}",
            f"- **Price Range:** ${price_range[0]:.2f} - ${price_range[1]:.2f}",
        ]

        if stop_losses:
            avg_sl = sum(stop_losses) / len(stop_losses)
            lines.append(f"- **Avg Stop Loss:** ${avg_sl:.2f}")

        if targets:
            avg_target = sum(targets) / len(targets)
            lines.append(f"- **Avg Target:** ${avg_target:.2f}")

        lines.extend(["", "## Setup Distribution"])
        for setup_type, count in sorted(setup_counts.items(), key=lambda x: -x[1]):
            pct = count / len(alerts) * 100
            bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            lines.append(f"- **{setup_type.upper()}:** {count} ({pct:.0f}%) {bar}")

        # Activity trend
        lines.extend(["", "## Activity Trend"])
        if len(recent_alerts) > len(older_alerts) / 3:  # More than expected
            lines.append("📈 **Increasing activity** - More alerts recently than average")
        elif len(recent_alerts) == 0:
            lines.append("📉 **Quiet period** - No alerts in the last 7 days")
        else:
            lines.append("➡️ **Stable activity** - Consistent alert frequency")

        # Most recent alert
        latest = alerts[0]
        lines.extend([
            "",
            "## Latest Alert",
            f"- **Type:** {latest.setup_type.upper()}",
            f"- **Entry:** ${latest.entry_price:.2f}",
            f"- **Time:** {latest.timestamp.strftime('%Y-%m-%d %H:%M')}",
        ])
        if latest.confidence_score:
            lines.append(f"- **Confidence:** {latest.confidence_score * 100:.0f}%")

        return "\n".join(lines)


@mcp.tool()
async def compare_symbols(symbols: List[str]) -> str:
    """Compare multiple symbols side by side.

    Compares alert frequency, setup types, and confidence levels
    across multiple symbols.

    Args:
        symbols: List of stock ticker symbols to compare (e.g., ["AAPL", "MSFT", "GOOGL"])

    Returns:
        Comparative analysis of the symbols
    """
    if not symbols:
        return "Please provide at least one symbol to compare."

    if len(symbols) > 10:
        return "Please limit comparison to 10 symbols or fewer."

    symbols = [s.upper() for s in symbols]
    logger.info(f"Comparing symbols: {symbols}")

    async with get_db_session() as session:
        # Get alerts for all symbols (last 30 days)
        month_ago = datetime.utcnow() - timedelta(days=30)
        alerts_query = (
            select(Alert)
            .where(Alert.symbol.in_(symbols))
            .where(Alert.timestamp >= month_ago)
        )
        result = await session.execute(alerts_query)
        alerts = result.scalars().all()

        # Group by symbol
        data_by_symbol = {s: {"alerts": [], "confidence": [], "setups": {}} for s in symbols}

        for alert in alerts:
            if alert.symbol in data_by_symbol:
                data = data_by_symbol[alert.symbol]
                data["alerts"].append(alert)
                if alert.confidence_score:
                    data["confidence"].append(alert.confidence_score)
                setup = alert.setup_type
                data["setups"][setup] = data["setups"].get(setup, 0) + 1

        lines = [
            "# Symbol Comparison",
            f"*{len(symbols)} symbols | Last 30 days*",
            "",
            "## Alert Frequency",
            "",
        ]

        # Sort by alert count
        sorted_symbols = sorted(
            symbols,
            key=lambda s: len(data_by_symbol[s]["alerts"]),
            reverse=True
        )

        max_alerts = max(len(data_by_symbol[s]["alerts"]) for s in symbols) or 1

        for symbol in sorted_symbols:
            data = data_by_symbol[symbol]
            count = len(data["alerts"])
            bar_len = int(count / max_alerts * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"**{symbol}:** {count:3d} {bar}")

        lines.extend(["", "## Average Confidence", ""])

        for symbol in sorted_symbols:
            data = data_by_symbol[symbol]
            if data["confidence"]:
                avg = sum(data["confidence"]) / len(data["confidence"])
                bar_len = int(avg * 20)
                bar = "█" * bar_len + "░" * (20 - bar_len)
                lines.append(f"**{symbol}:** {avg * 100:5.1f}% {bar}")
            else:
                lines.append(f"**{symbol}:** N/A")

        lines.extend(["", "## Primary Setup Types", ""])

        for symbol in sorted_symbols:
            data = data_by_symbol[symbol]
            if data["setups"]:
                top_setup = max(data["setups"].items(), key=lambda x: x[1])
                lines.append(f"**{symbol}:** {top_setup[0].upper()} ({top_setup[1]} alerts)")
            else:
                lines.append(f"**{symbol}:** No alerts")

        # Recommendation
        lines.extend(["", "## Summary", ""])

        # Find most active with high confidence
        best_symbol = None
        best_score = 0
        for symbol in symbols:
            data = data_by_symbol[symbol]
            if data["confidence"]:
                avg_conf = sum(data["confidence"]) / len(data["confidence"])
                score = len(data["alerts"]) * avg_conf
                if score > best_score:
                    best_score = score
                    best_symbol = symbol

        if best_symbol:
            data = data_by_symbol[best_symbol]
            avg_conf = sum(data["confidence"]) / len(data["confidence"]) if data["confidence"] else 0
            lines.append(
                f"**Most Active with High Confidence:** {best_symbol} "
                f"({len(data['alerts'])} alerts, {avg_conf * 100:.0f}% avg confidence)"
            )
        else:
            lines.append("No clear leader among compared symbols.")

        return "\n".join(lines)


@mcp.tool()
async def get_top_performers(days: int = 7, limit: int = 10) -> str:
    """Get the best performing alerts based on confidence and setup quality.

    Identifies high-confidence alerts that represent the strongest
    trading opportunities.

    Args:
        days: Number of days to analyze (default 7, max 90)
        limit: Maximum number of results (default 10, max 50)

    Returns:
        List of top performing alerts with analysis
    """
    # Clamp parameters
    days = min(max(1, days), 90)
    limit = min(max(1, limit), 50)

    logger.info(f"Getting top performers: days={days}, limit={limit}")

    async with get_db_session() as session:
        start_date = datetime.utcnow() - timedelta(days=days)

        # Get high-confidence alerts
        alerts_query = (
            select(Alert)
            .where(Alert.timestamp >= start_date)
            .where(Alert.confidence_score.isnot(None))
            .order_by(Alert.confidence_score.desc())
            .limit(limit)
        )
        result = await session.execute(alerts_query)
        alerts = result.scalars().all()

        if not alerts:
            return f"No alerts with confidence scores found in the last {days} days."

        lines = [
            "# Top Performing Alerts",
            f"*Last {days} day{'s' if days != 1 else ''} | Top {limit}*",
            "",
        ]

        for i, alert in enumerate(alerts, 1):
            confidence_pct = alert.confidence_score * 100

            # Calculate R/R if available
            rr_str = ""
            if alert.stop_loss and alert.target_price:
                risk = alert.entry_price - alert.stop_loss
                reward = alert.target_price - alert.entry_price
                if risk > 0:
                    rr = reward / risk
                    rr_str = f" | R/R: {rr:.1f}:1"

            lines.extend([
                f"## #{i} {alert.symbol} - {alert.setup_type.upper()} ({confidence_pct:.0f}%)",
                f"**Entry:** ${alert.entry_price:.2f}{rr_str}",
                f"**Time:** {alert.timestamp.strftime('%Y-%m-%d %H:%M')}",
            ])

            if alert.stop_loss:
                lines.append(f"**Stop Loss:** ${alert.stop_loss:.2f}")
            if alert.target_price:
                lines.append(f"**Target:** ${alert.target_price:.2f}")

            lines.append("")

        # Summary statistics
        avg_confidence = sum(a.confidence_score for a in alerts) / len(alerts)
        setup_counts = {}
        for alert in alerts:
            setup_counts[alert.setup_type] = setup_counts.get(alert.setup_type, 0) + 1

        top_setup = max(setup_counts.items(), key=lambda x: x[1])

        lines.extend([
            "---",
            "## Statistics",
            f"- **Average Confidence:** {avg_confidence * 100:.1f}%",
            f"- **Most Common Setup:** {top_setup[0].upper()} ({top_setup[1]} alerts)",
            f"- **Unique Symbols:** {len(set(a.symbol for a in alerts))}",
        ])

        return "\n".join(lines)
