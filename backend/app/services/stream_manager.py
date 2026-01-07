"""Stream manager for real-time Alpaca market data."""

import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional, Set

from alpaca.data.enums import DataFeed
from alpaca.data.live import StockDataStream
from alpaca.data.models import Bar as AlpacaBar
from alpaca.data.models import Quote as AlpacaQuote
from alpaca.data.models import Trade as AlpacaTrade

from app.config import get_settings
from app.schemas.market_data import Bar, MarketData

logger = logging.getLogger(__name__)


class StreamManager:
    """Manages real-time data streaming from Alpaca."""

    _instance: Optional["StreamManager"] = None

    def __init__(self) -> None:
        """Initialize stream manager."""
        settings = get_settings()

        self._api_key = settings.alpaca_api_key
        self._secret_key = settings.alpaca_secret_key
        self._data_feed = settings.alpaca_data_feed

        self._stream: Optional[StockDataStream] = None
        self._subscribed_symbols: Set[str] = set()
        self._running = False
        self._stream_task: Optional[asyncio.Task] = None

        # Callbacks for broadcasting data
        self._on_trade: Optional[Callable] = None
        self._on_quote: Optional[Callable] = None
        self._on_bar: Optional[Callable] = None

    @classmethod
    def get_instance(cls) -> "StreamManager":
        """Get singleton instance of stream manager."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_callbacks(
        self,
        on_trade: Optional[Callable] = None,
        on_quote: Optional[Callable] = None,
        on_bar: Optional[Callable] = None,
    ) -> None:
        """Set callback functions for data events.

        Args:
            on_trade: Called with (symbol, MarketData) when trade received
            on_quote: Called with (symbol, MarketData) when quote received
            on_bar: Called with (symbol, Bar) when bar received
        """
        self._on_trade = on_trade
        self._on_quote = on_quote
        self._on_bar = on_bar

    def _create_stream(self) -> StockDataStream:
        """Create a new stock data stream."""
        # Convert string feed to DataFeed enum
        feed = DataFeed.IEX if self._data_feed.lower() == "iex" else DataFeed.SIP
        return StockDataStream(
            api_key=self._api_key,
            secret_key=self._secret_key,
            feed=feed,
        )

    async def _handle_trade(self, trade: AlpacaTrade) -> None:
        """Handle incoming trade data."""
        if self._on_trade is None:
            return

        try:
            market_data = MarketData(
                symbol=trade.symbol,
                price=trade.price,
                volume=trade.size,
                timestamp=trade.timestamp,
            )
            await self._on_trade(trade.symbol, market_data)
        except Exception as e:
            logger.error(f"Error handling trade for {trade.symbol}: {e}")

    async def _handle_quote(self, quote: AlpacaQuote) -> None:
        """Handle incoming quote data."""
        if self._on_quote is None:
            return

        try:
            mid_price = (quote.ask_price + quote.bid_price) / 2 if quote.ask_price and quote.bid_price else 0
            market_data = MarketData(
                symbol=quote.symbol,
                price=mid_price,
                bid=quote.bid_price,
                ask=quote.ask_price,
                bid_size=quote.bid_size,
                ask_size=quote.ask_size,
                timestamp=quote.timestamp,
            )
            await self._on_quote(quote.symbol, market_data)
        except Exception as e:
            logger.error(f"Error handling quote for {quote.symbol}: {e}")

    async def _handle_bar(self, bar: AlpacaBar) -> None:
        """Handle incoming bar data."""
        if self._on_bar is None:
            return

        try:
            bar_data = Bar(
                timestamp=bar.timestamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                vwap=bar.vwap,
                trade_count=bar.trade_count,
            )
            await self._on_bar(bar.symbol, bar_data)
        except Exception as e:
            logger.error(f"Error handling bar for {bar.symbol}: {e}")

    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to real-time data for symbols.

        Args:
            symbols: List of stock symbols to subscribe to
        """
        if not self._api_key or not self._secret_key:
            logger.warning("Alpaca credentials not configured, skipping subscription")
            return

        new_symbols = set(s.upper() for s in symbols) - self._subscribed_symbols
        if not new_symbols:
            return

        if self._stream is None:
            self._stream = self._create_stream()
            self._stream.subscribe_trades(self._handle_trade, *new_symbols)
            self._stream.subscribe_quotes(self._handle_quote, *new_symbols)
            self._stream.subscribe_bars(self._handle_bar, *new_symbols)
        else:
            self._stream.subscribe_trades(self._handle_trade, *new_symbols)
            self._stream.subscribe_quotes(self._handle_quote, *new_symbols)
            self._stream.subscribe_bars(self._handle_bar, *new_symbols)

        self._subscribed_symbols.update(new_symbols)
        logger.info(f"Subscribed to symbols: {new_symbols}")

    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from real-time data for symbols.

        Args:
            symbols: List of stock symbols to unsubscribe from
        """
        if self._stream is None:
            return

        symbols_to_remove = set(s.upper() for s in symbols) & self._subscribed_symbols
        if not symbols_to_remove:
            return

        self._stream.unsubscribe_trades(*symbols_to_remove)
        self._stream.unsubscribe_quotes(*symbols_to_remove)
        self._stream.unsubscribe_bars(*symbols_to_remove)

        self._subscribed_symbols -= symbols_to_remove
        logger.info(f"Unsubscribed from symbols: {symbols_to_remove}")

    async def start(self) -> None:
        """Start the stream manager."""
        if self._running:
            return

        if not self._api_key or not self._secret_key:
            logger.warning("Alpaca credentials not configured, stream manager not started")
            return

        self._running = True

        if self._stream is None:
            self._stream = self._create_stream()

        async def run_stream():
            try:
                await self._stream.run()
            except Exception as e:
                logger.error(f"Stream error: {e}")
                self._running = False

        self._stream_task = asyncio.create_task(run_stream())
        logger.info("Stream manager started")

    async def stop(self) -> None:
        """Stop the stream manager."""
        self._running = False

        if self._stream is not None:
            try:
                await self._stream.close()
            except Exception as e:
                logger.error(f"Error closing stream: {e}")
            self._stream = None

        if self._stream_task is not None:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
            self._stream_task = None

        self._subscribed_symbols.clear()
        logger.info("Stream manager stopped")

    @property
    def is_running(self) -> bool:
        """Check if stream manager is running."""
        return self._running

    @property
    def subscribed_symbols(self) -> Set[str]:
        """Get currently subscribed symbols."""
        return self._subscribed_symbols.copy()


def get_stream_manager() -> StreamManager:
    """Dependency to get stream manager instance."""
    return StreamManager.get_instance()
