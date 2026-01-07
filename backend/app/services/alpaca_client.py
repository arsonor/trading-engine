"""Alpaca Markets API client wrapper."""

from datetime import datetime, timedelta
from typing import Optional

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from app.config import get_settings
from app.schemas.market_data import Bar, MarketData, Timeframe


class AlpacaClient:
    """Wrapper for Alpaca Markets API."""

    _instance: Optional["AlpacaClient"] = None

    def __init__(self) -> None:
        """Initialize Alpaca client with credentials from settings."""
        settings = get_settings()

        self._api_key = settings.alpaca_api_key
        self._secret_key = settings.alpaca_secret_key
        self._data_feed = settings.alpaca_data_feed

        # Initialize data client (for REST API calls)
        if self._api_key and self._secret_key:
            self._data_client = StockHistoricalDataClient(
                api_key=self._api_key,
                secret_key=self._secret_key,
            )
        else:
            # Use unauthenticated client (limited to IEX data)
            self._data_client = StockHistoricalDataClient()

        self._stream: Optional[StockDataStream] = None

    @classmethod
    def get_instance(cls) -> "AlpacaClient":
        """Get singleton instance of Alpaca client."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _convert_timeframe(self, timeframe: Timeframe) -> TimeFrame:
        """Convert our Timeframe enum to Alpaca TimeFrame."""
        mapping = {
            Timeframe.MIN_1: TimeFrame(1, TimeFrameUnit.Minute),
            Timeframe.MIN_5: TimeFrame(5, TimeFrameUnit.Minute),
            Timeframe.MIN_15: TimeFrame(15, TimeFrameUnit.Minute),
            Timeframe.HOUR_1: TimeFrame(1, TimeFrameUnit.Hour),
            Timeframe.DAY_1: TimeFrame(1, TimeFrameUnit.Day),
        }
        return mapping.get(timeframe, TimeFrame(1, TimeFrameUnit.Minute))

    async def get_latest_quote(self, symbol: str) -> Optional[MarketData]:
        """Get the latest quote for a symbol.

        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL')

        Returns:
            MarketData object with current price info, or None if not found
        """
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quotes = self._data_client.get_stock_latest_quote(request)

            if symbol not in quotes:
                return None

            quote = quotes[symbol]

            return MarketData(
                symbol=symbol,
                price=(quote.ask_price + quote.bid_price) / 2 if quote.ask_price and quote.bid_price else 0,
                bid=quote.bid_price,
                ask=quote.ask_price,
                bid_size=quote.bid_size,
                ask_size=quote.ask_size,
                timestamp=quote.timestamp,
            )
        except Exception:
            return None

    async def get_snapshot(self, symbol: str) -> Optional[MarketData]:
        """Get a complete snapshot of market data for a symbol.

        Args:
            symbol: Stock ticker symbol

        Returns:
            MarketData with full market info including daily stats
        """
        try:
            request = StockSnapshotRequest(symbol_or_symbols=symbol)
            snapshots = self._data_client.get_stock_snapshot(request)

            if symbol not in snapshots:
                return None

            snapshot = snapshots[symbol]
            quote = snapshot.latest_quote
            trade = snapshot.latest_trade
            daily_bar = snapshot.daily_bar
            prev_daily_bar = snapshot.previous_daily_bar

            price = trade.price if trade else 0
            prev_close = prev_daily_bar.close if prev_daily_bar else None
            change = None
            change_percent = None

            if price and prev_close:
                change = price - prev_close
                change_percent = (change / prev_close) * 100

            return MarketData(
                symbol=symbol,
                price=price,
                bid=quote.bid_price if quote else None,
                ask=quote.ask_price if quote else None,
                bid_size=quote.bid_size if quote else None,
                ask_size=quote.ask_size if quote else None,
                volume=daily_bar.volume if daily_bar else None,
                timestamp=trade.timestamp if trade else datetime.utcnow(),
                change=change,
                change_percent=change_percent,
                day_high=daily_bar.high if daily_bar else None,
                day_low=daily_bar.low if daily_bar else None,
                day_open=daily_bar.open if daily_bar else None,
                prev_close=prev_close,
                vwap=daily_bar.vwap if daily_bar else None,
            )
        except Exception:
            return None

    async def get_bars(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.MIN_1,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[Bar]:
        """Get historical bars for a symbol.

        Args:
            symbol: Stock ticker symbol
            timeframe: Bar timeframe (1Min, 5Min, etc.)
            start: Start datetime (defaults to 24 hours ago)
            end: End datetime (defaults to now)
            limit: Maximum number of bars to return

        Returns:
            List of Bar objects
        """
        try:
            if end is None:
                end = datetime.utcnow()
            if start is None:
                start = end - timedelta(days=1)

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=self._convert_timeframe(timeframe),
                start=start,
                end=end,
                limit=limit,
            )

            bars_data = self._data_client.get_stock_bars(request)

            if symbol not in bars_data:
                return []

            bars = []
            for bar in bars_data[symbol]:
                bars.append(
                    Bar(
                        timestamp=bar.timestamp,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                        vwap=bar.vwap,
                        trade_count=bar.trade_count,
                    )
                )

            return bars[:limit]
        except Exception:
            return []

    def get_stream(self) -> StockDataStream:
        """Get or create the stock data stream for real-time data.

        Returns:
            StockDataStream instance for subscribing to live data
        """
        if self._stream is None:
            # Convert string feed to DataFeed enum
            feed = DataFeed.IEX if self._data_feed.lower() == "iex" else DataFeed.SIP
            self._stream = StockDataStream(
                api_key=self._api_key,
                secret_key=self._secret_key,
                feed=feed,
            )
        return self._stream

    async def close(self) -> None:
        """Close any open connections."""
        if self._stream is not None:
            await self._stream.close()
            self._stream = None


def get_alpaca_client() -> AlpacaClient:
    """Dependency to get Alpaca client instance."""
    return AlpacaClient.get_instance()
