"""Watchlist MCP tools.

Tools:
- get_watchlist: Get current watchlist
- add_to_watchlist: Add symbol to watchlist
- remove_from_watchlist: Remove symbol from watchlist
"""

from typing import Optional

from sqlalchemy import func, select

from app.mcp.server import get_db_session, logger, mcp
from app.models.alert import Alert
from app.models.watchlist import Watchlist


@mcp.tool()
async def get_watchlist() -> str:
    """Get the current watchlist with all symbols being monitored.

    Returns:
        A formatted list of all watchlist items with their status and notes
    """
    logger.info("Getting watchlist")

    async with get_db_session() as session:
        query = select(Watchlist).order_by(Watchlist.added_at.desc())
        result = await session.execute(query)
        items = result.scalars().all()

        if not items:
            return (
                "# Watchlist\n\n"
                "Your watchlist is empty.\n\n"
                "Use `add_to_watchlist(symbol)` to add symbols you want to monitor."
            )

        # Get alert counts for each symbol
        symbols = [item.symbol for item in items]
        counts_query = (
            select(Alert.symbol, func.count(Alert.id))
            .where(Alert.symbol.in_(symbols))
            .group_by(Alert.symbol)
        )
        counts_result = await session.execute(counts_query)
        alert_counts = {row[0]: row[1] for row in counts_result.all()}

        lines = [
            f"# Watchlist ({len(items)} symbols)",
            "",
        ]

        active_items = [i for i in items if i.is_active]
        inactive_items = [i for i in items if not i.is_active]

        if active_items:
            lines.append("## Active")
            lines.append("")
            for item in active_items:
                alert_count = alert_counts.get(item.symbol, 0)
                lines.append(f"**{item.symbol}** - {alert_count} alert(s)")
                lines.append(f"   Added: {item.added_at.strftime('%Y-%m-%d')}")
                if item.notes:
                    lines.append(f"   Note: {item.notes}")
                lines.append("")

        if inactive_items:
            lines.append("## Inactive")
            lines.append("")
            for item in inactive_items:
                alert_count = alert_counts.get(item.symbol, 0)
                lines.append(f"**{item.symbol}** - {alert_count} alert(s)")
                lines.append(f"   Added: {item.added_at.strftime('%Y-%m-%d')}")
                if item.notes:
                    lines.append(f"   Note: {item.notes}")
                lines.append("")

        # Summary
        total_alerts = sum(alert_counts.values())
        lines.extend([
            "---",
            f"**Total:** {len(active_items)} active, {len(inactive_items)} inactive | "
            f"**Alerts:** {total_alerts}",
        ])

        return "\n".join(lines)


@mcp.tool()
async def add_to_watchlist(symbol: str, notes: Optional[str] = None) -> str:
    """Add a symbol to the watchlist.

    Args:
        symbol: Stock ticker symbol to add (e.g., "AAPL")
        notes: Optional notes about why you're watching this symbol

    Returns:
        Confirmation message or error if symbol already exists
    """
    symbol = symbol.upper()
    logger.info(f"Adding to watchlist: {symbol}")

    async with get_db_session() as session:
        # Check if already exists
        existing_query = select(Watchlist).where(Watchlist.symbol == symbol)
        existing = (await session.execute(existing_query)).scalar_one_or_none()

        if existing:
            status = "active" if existing.is_active else "inactive"
            return (
                f"**{symbol}** is already in your watchlist ({status}).\n\n"
                f"Added on: {existing.added_at.strftime('%Y-%m-%d')}\n"
                f"Notes: {existing.notes or 'None'}"
            )

        # Create new watchlist item
        item = Watchlist(
            symbol=symbol,
            notes=notes,
            is_active=True,
        )

        session.add(item)
        await session.commit()
        await session.refresh(item)

        lines = [
            f"# Added to Watchlist",
            "",
            f"**Symbol:** {symbol}",
            f"**Status:** Active",
            f"**Added:** {item.added_at.strftime('%Y-%m-%d %H:%M')}",
        ]

        if notes:
            lines.append(f"**Notes:** {notes}")

        lines.extend([
            "",
            "The symbol will now be monitored for trading alerts.",
        ])

        return "\n".join(lines)


@mcp.tool()
async def remove_from_watchlist(symbol: str) -> str:
    """Remove a symbol from the watchlist.

    Args:
        symbol: Stock ticker symbol to remove (e.g., "AAPL")

    Returns:
        Confirmation message or error if symbol not found
    """
    symbol = symbol.upper()
    logger.info(f"Removing from watchlist: {symbol}")

    async with get_db_session() as session:
        query = select(Watchlist).where(Watchlist.symbol == symbol)
        result = await session.execute(query)
        item = result.scalar_one_or_none()

        if not item:
            return f"**{symbol}** is not in your watchlist."

        # Get alert count before removal
        count_query = select(func.count(Alert.id)).where(Alert.symbol == symbol)
        alert_count = (await session.execute(count_query)).scalar() or 0

        added_date = item.added_at.strftime('%Y-%m-%d')
        notes = item.notes

        await session.delete(item)
        await session.commit()

        lines = [
            f"# Removed from Watchlist",
            "",
            f"**Symbol:** {symbol}",
            f"**Was Added:** {added_date}",
        ]

        if notes:
            lines.append(f"**Notes:** {notes}")

        lines.append("")

        if alert_count > 0:
            lines.append(
                f"Note: {alert_count} historical alert(s) for this symbol have been preserved."
            )
        else:
            lines.append("No historical alerts existed for this symbol.")

        return "\n".join(lines)
