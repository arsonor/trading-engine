"""Alert generation service.

This service connects StreamManager market data callbacks to the RuleEngine,
generates alerts when rules trigger, persists them to the database,
and broadcasts via WebSocket.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.websocket import get_manager
from app.core.database import async_session_maker
from app.engine.rule_engine import (
    ConfidenceModifier,
    OperatorType,
    RuleCondition,
    RuleConfidence,
    RuleDefinition,
    RuleEngine,
    RuleEvaluationResult,
    RuleFilters,
    RuleTargets,
)
from app.models import Alert, Rule
from app.schemas.market_data import MarketData

logger = logging.getLogger(__name__)


class AlertGenerator:
    """Service that generates alerts from market data using configured rules."""

    _instance: Optional["AlertGenerator"] = None

    def __init__(self) -> None:
        """Initialize the alert generator."""
        self._rule_engine: RuleEngine = RuleEngine()
        self._rules_cache: Dict[int, Tuple[Rule, RuleDefinition]] = {}
        self._cache_ttl: int = 60  # seconds
        self._last_cache_refresh: Optional[datetime] = None
        self._running: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "AlertGenerator":
        """Get singleton instance of alert generator."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        cls._instance = None

    async def start(self) -> None:
        """Start the alert generator service."""
        if self._running:
            return

        self._running = True
        # Pre-load rules cache
        await self.refresh_rules_cache(force=True)
        logger.info("Alert generator started")

    async def stop(self) -> None:
        """Stop the alert generator service."""
        self._running = False
        self._rules_cache.clear()
        self._last_cache_refresh = None
        logger.info("Alert generator stopped")

    async def on_market_data(self, symbol: str, market_data: MarketData) -> None:
        """
        Callback for processing incoming market data from StreamManager.

        This is the main entry point called by StreamManager when new
        market data arrives.
        """
        if not self._running:
            return

        try:
            # Refresh cache if needed
            await self.refresh_rules_cache()

            # Convert and enrich market data
            market_data_dict = self._enrich_market_data(symbol, market_data)

            # Evaluate rules and generate alerts
            await self._evaluate_and_generate(symbol, market_data_dict)

        except Exception as e:
            logger.error(f"Error processing market data for {symbol}: {e}")

    async def refresh_rules_cache(self, force: bool = False) -> None:
        """Refresh rules cache from database if TTL expired or forced."""
        now = datetime.utcnow()

        # Check if refresh needed (outside lock for performance)
        if not force and self._last_cache_refresh:
            elapsed = (now - self._last_cache_refresh).total_seconds()
            if elapsed < self._cache_ttl:
                return

        async with self._lock:
            # Double-check after acquiring lock
            if not force and self._last_cache_refresh:
                elapsed = (now - self._last_cache_refresh).total_seconds()
                if elapsed < self._cache_ttl:
                    return

            try:
                # Fetch active rules from database
                async with async_session_maker() as session:
                    query = select(Rule).where(Rule.is_active.is_(True))
                    result = await session.execute(query)
                    db_rules = result.scalars().all()

                # Parse and cache rules
                new_cache: Dict[int, Tuple[Rule, RuleDefinition]] = {}
                new_engine = RuleEngine()

                for db_rule in db_rules:
                    try:
                        rule_def = self._parse_rule_to_definition(db_rule)
                        if rule_def:
                            new_cache[db_rule.id] = (db_rule, rule_def)
                            new_engine.add_rule(rule_def)
                    except Exception as e:
                        logger.warning(f"Failed to parse rule '{db_rule.name}': {e}")

                self._rules_cache = new_cache
                self._rule_engine = new_engine
                self._last_cache_refresh = now
                logger.debug(f"Refreshed rules cache: {len(new_cache)} active rules")

            except Exception as e:
                logger.error(f"Failed to refresh rules cache: {e}")

    async def invalidate_cache(self) -> None:
        """Force cache invalidation (call when rules are updated via API)."""
        async with self._lock:
            self._last_cache_refresh = None
        logger.debug("Rules cache invalidated")

    def _parse_rule_to_definition(self, db_rule: Rule) -> Optional[RuleDefinition]:
        """Parse database rule's config_yaml into RuleDefinition."""
        try:
            config = yaml.safe_load(db_rule.config_yaml)
            if not config:
                return None

            # Build conditions
            conditions = []
            for cond in config.get("conditions", []):
                conditions.append(
                    RuleCondition(
                        field=cond["field"],
                        operator=OperatorType(cond["operator"]),
                        value=cond["value"],
                    )
                )

            if not conditions:
                logger.warning(f"Rule '{db_rule.name}' has no conditions")
                return None

            # Build filters
            filters = None
            filters_data = config.get("filters")
            if filters_data:
                filters = RuleFilters(**filters_data)

            # Build targets
            targets = None
            targets_data = config.get("targets")
            if targets_data:
                targets = RuleTargets(**targets_data)

            # Build confidence
            confidence = None
            conf_data = config.get("confidence")
            if conf_data:
                modifiers = None
                if conf_data.get("modifiers"):
                    modifiers = [
                        ConfidenceModifier(**m) for m in conf_data["modifiers"]
                    ]
                confidence = RuleConfidence(
                    base_score=conf_data.get("base_score", 0.7),
                    modifiers=modifiers,
                )

            return RuleDefinition(
                name=db_rule.name,
                description=db_rule.description,
                type=db_rule.rule_type,
                enabled=db_rule.is_active,
                priority=db_rule.priority,
                conditions=conditions,
                filters=filters,
                targets=targets,
                confidence=confidence,
            )

        except Exception as e:
            logger.error(f"Failed to parse rule '{db_rule.name}': {e}")
            return None

    def _enrich_market_data(
        self, symbol: str, market_data: MarketData
    ) -> Dict[str, Any]:
        """
        Convert MarketData to dict and enrich with calculated fields.

        Rules that require unavailable data will simply not trigger due to
        RuleEngine's behavior of returning False when a field is None.
        """
        # Use mode="json" to ensure datetime is serialized to ISO string
        data = market_data.model_dump(mode="json")

        # Ensure symbol is set
        data["symbol"] = symbol

        # Calculate derived fields if source data is available
        if market_data.prev_close and market_data.price:
            data["price_change_percent"] = (
                (market_data.price - market_data.prev_close)
                / market_data.prev_close
                * 100
            )

        if market_data.day_open and market_data.prev_close:
            data["gap_percent"] = (
                (market_data.day_open - market_data.prev_close)
                / market_data.prev_close
                * 100
            )

        # Fields that require external data sources default to None
        # This allows rules requiring them to gracefully not trigger
        data.setdefault("volume_ratio", None)
        data.setdefault("resistance_level", None)
        data.setdefault("sma_20", None)
        data.setdefault("pre_market_high", None)
        data.setdefault("float_shares", None)
        data.setdefault("short_interest", None)
        data.setdefault("atr", None)
        data.setdefault("pre_market_volume", None)

        return data

    async def _evaluate_and_generate(
        self, symbol: str, market_data_dict: Dict[str, Any]
    ) -> List[Alert]:
        """Evaluate rules against market data and generate alerts."""
        alerts_created = []

        # Evaluate all active rules
        results = self._rule_engine.evaluate_all_rules(market_data_dict)

        if not results:
            return alerts_created

        # Process triggered rules
        async with async_session_maker() as session:
            for result in results:
                try:
                    # Find the rule ID from cache
                    rule_id = None
                    rule_name = result.rule_name
                    for rid, (db_rule, rule_def) in self._rules_cache.items():
                        if rule_def.name == result.rule_name:
                            rule_id = rid
                            break

                    # Create alert
                    alert = await self._create_alert(
                        session=session,
                        rule_id=rule_id,
                        symbol=symbol,
                        result=result,
                        market_data=market_data_dict,
                    )
                    alerts_created.append(alert)

                    # Broadcast via WebSocket
                    await self._broadcast_alert(alert, rule_name)

                    logger.info(
                        f"Alert generated: {symbol} - {result.rule_name} "
                        f"(confidence: {result.confidence:.2f})"
                    )

                except Exception as e:
                    logger.error(
                        f"Failed to create alert for {symbol} "
                        f"rule '{result.rule_name}': {e}"
                    )

            # Commit all alerts
            await session.commit()

        return alerts_created

    async def _create_alert(
        self,
        session: AsyncSession,
        rule_id: Optional[int],
        symbol: str,
        result: RuleEvaluationResult,
        market_data: Dict[str, Any],
    ) -> Alert:
        """Create and persist an alert to the database."""
        # Determine setup_type from rule name/type
        setup_type = self._determine_setup_type(result.rule_name)

        alert = Alert(
            rule_id=rule_id,
            symbol=symbol,
            timestamp=datetime.utcnow(),
            setup_type=setup_type,
            entry_price=result.entry_price or market_data.get("price", 0),
            stop_loss=result.stop_loss,
            target_price=result.target_price,
            confidence_score=result.confidence,
            market_data_json=market_data,
            is_read=False,
        )

        session.add(alert)
        await session.flush()  # Get the ID without committing
        await session.refresh(alert)

        return alert

    def _determine_setup_type(self, rule_name: str) -> str:
        """Determine setup type from rule name."""
        rule_name_lower = rule_name.lower()

        if "breakout" in rule_name_lower:
            return "breakout"
        elif "volume" in rule_name_lower or "spike" in rule_name_lower:
            return "volume_spike"
        elif "gap_up" in rule_name_lower or "gap up" in rule_name_lower:
            return "gap_up"
        elif "gap_down" in rule_name_lower or "gap down" in rule_name_lower:
            return "gap_down"
        elif "momentum" in rule_name_lower:
            return "momentum"
        else:
            return "breakout"  # Default

    async def _broadcast_alert(self, alert: Alert, rule_name: str) -> None:
        """Broadcast the new alert via WebSocket."""
        try:
            manager = get_manager()
            await manager.broadcast_to_channel(
                "alerts",
                {
                    "type": "alert",
                    "data": {
                        "id": alert.id,
                        "symbol": alert.symbol,
                        "setup_type": alert.setup_type,
                        "entry_price": alert.entry_price,
                        "stop_loss": alert.stop_loss,
                        "target_price": alert.target_price,
                        "confidence_score": alert.confidence_score,
                        "rule_name": rule_name,
                        "timestamp": alert.timestamp.isoformat(),
                        "is_read": alert.is_read,
                    },
                },
            )
        except Exception as e:
            logger.error(f"Failed to broadcast alert: {e}")


def get_alert_generator() -> AlertGenerator:
    """Get the alert generator singleton instance."""
    return AlertGenerator.get_instance()
