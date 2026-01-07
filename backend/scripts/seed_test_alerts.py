"""Seed script to create test alerts for dashboard testing."""

import asyncio
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add backend directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.alert import Alert
from app.models.rule import Rule


async def seed_alerts():
    """Create test alerts in the database."""
    async with async_session_maker() as db:
        # Get existing rule (if any)
        result = await db.execute(select(Rule).limit(1))
        rule = result.scalar_one_or_none()
        rule_id = rule.id if rule else None

        # Sample data
        symbols = ["AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "AMZN", "META"]
        setup_types = ["breakout", "volume_spike", "gap_up", "gap_down", "momentum"]

        # Create 20 test alerts
        alerts = []
        for i in range(20):
            symbol = random.choice(symbols)
            base_price = {
                "AAPL": 185.0,
                "TSLA": 250.0,
                "NVDA": 480.0,
                "MSFT": 375.0,
                "GOOGL": 140.0,
                "AMZN": 180.0,
                "META": 500.0,
            }.get(symbol, 100.0)

            entry_price = base_price * (1 + random.uniform(-0.05, 0.05))
            stop_loss = entry_price * 0.97  # 3% below
            target_price = entry_price * 1.06  # 6% above

            alert = Alert(
                rule_id=rule_id,
                symbol=symbol,
                timestamp=datetime.utcnow() - timedelta(hours=random.randint(0, 72)),
                setup_type=random.choice(setup_types),
                entry_price=round(entry_price, 2),
                stop_loss=round(stop_loss, 2),
                target_price=round(target_price, 2),
                confidence_score=round(random.uniform(0.6, 0.95), 2),
                market_data_json={
                    "price": round(entry_price, 2),
                    "volume": random.randint(100000, 5000000),
                    "change_percent": round(random.uniform(-5, 10), 2),
                },
                is_read=random.choice([True, False, False]),  # More unread
            )
            alerts.append(alert)

        db.add_all(alerts)
        await db.commit()

        print(f"✓ Created {len(alerts)} test alerts")
        print(f"  Rule ID: {rule_id or 'None (no rules exist)'}")
        print(f"  Symbols: {', '.join(set(a.symbol for a in alerts))}")


if __name__ == "__main__":
    asyncio.run(seed_alerts())
