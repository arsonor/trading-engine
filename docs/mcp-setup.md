# MCP (Model Context Protocol) Setup Guide

This guide explains how to set up and use the Trading Engine MCP server with AI assistants like Claude.

## Overview

The Trading Engine uses a hybrid MCP architecture:

1. **Trading Engine MCP Server** (Custom) - Alerts, rules, analysis, historical data
2. **Alpaca MCP Server** (Official) - Market data, trading, portfolio management (43 tools)

## Prerequisites

- Python 3.10+
- uv package manager
- Claude Desktop or Claude Code CLI
- Alpaca Markets paper trading account (free at [app.alpaca.markets](https://app.alpaca.markets/paper/dashboard/overview))

## Installation

### 1. Install Trading Engine Dependencies

```bash
cd backend
uv sync
```

### 2. Install Alpaca MCP Server

```bash
uvx alpaca-mcp-server init
```

This will prompt you for your Alpaca API keys and create a local configuration.

### 3. Verify Installation

```bash
# Test Trading Engine MCP
uv run python scripts/test_mcp_connection.py

# Test Alpaca MCP
uvx alpaca-mcp-server status
```

## Claude Desktop Configuration

### Combined Configuration (Both Servers)

Locate your Claude Desktop configuration file:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

Add both MCP servers:

**Windows:**
```json
{
  "mcpServers": {
    "trading-engine": {
      "command": "uv",
      "args": [
        "--directory",
        "C:/path/to/trading-engine/backend",
        "run",
        "run_mcp.py"
      ],
      "env": {
        "DATABASE_URL": "sqlite+aiosqlite:///C:/path/to/trading-engine/backend/trading_engine.db"
      }
    },
    "alpaca": {
      "command": "uvx",
      "args": ["alpaca-mcp-server", "serve"],
      "env": {
        "ALPACA_API_KEY": "your_alpaca_api_key",
        "ALPACA_SECRET_KEY": "your_alpaca_secret_key",
        "ALPACA_PAPER_TRADE": "true"
      }
    }
  }
}
```

**macOS/Linux:**
```json
{
  "mcpServers": {
    "trading-engine": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/trading-engine/backend",
        "run",
        "run_mcp.py"
      ],
      "env": {
        "DATABASE_URL": "sqlite+aiosqlite:////path/to/trading-engine/backend/trading_engine.db"
      }
    },
    "alpaca": {
      "command": "uvx",
      "args": ["alpaca-mcp-server", "serve"],
      "env": {
        "ALPACA_API_KEY": "your_alpaca_api_key",
        "ALPACA_SECRET_KEY": "your_alpaca_secret_key",
        "ALPACA_PAPER_TRADE": "true"
      }
    }
  }
}
```

**Important:**
- Replace paths with your actual project location
- Replace API keys with your Alpaca credentials
- Use forward slashes (`/`) even on Windows
- Restart Claude Desktop after configuration changes

### Claude Code CLI

```bash
# Add Trading Engine MCP
claude mcp add trading-engine --scope user --transport stdio uv \
  --directory /path/to/trading-engine/backend run run_mcp.py

# Add Alpaca MCP
claude mcp add alpaca --scope user --transport stdio uvx alpaca-mcp-server serve \
  --env ALPACA_API_KEY=your_key \
  --env ALPACA_SECRET_KEY=your_secret
```

## Available Tools

### Trading Engine MCP Server

#### Alert Tools
| Tool | Description |
|------|-------------|
| `explain_alert(alert_id)` | Get detailed explanation of why an alert triggered |
| `list_alerts(symbol?, limit?, setup_type?)` | List recent alerts with optional filters |
| `get_alert_by_id(alert_id)` | Get specific alert details |
| `mark_alert_read(alert_id)` | Mark an alert as read |
| `get_alert_statistics(days?)` | Get alert statistics for performance tracking |

#### Rule Management Tools
| Tool | Description |
|------|-------------|
| `list_rules(active_only?)` | List all trading rules |
| `get_rule(rule_id)` | Get rule details with configuration |
| `create_rule_from_description(name, description, conditions)` | Create rule from natural language |
| `toggle_rule(rule_id)` | Enable/disable a rule |
| `delete_rule(rule_id)` | Remove a rule |

#### Analysis Tools
| Tool | Description |
|------|-------------|
| `analyze_watchlist()` | Analyze all watched stocks for bullish/bearish signals |
| `get_symbol_analysis(symbol)` | Deep analysis of a single symbol |
| `compare_symbols(symbols[])` | Compare multiple symbols |
| `get_top_performers(days?, limit?)` | Get best performing alerts |

#### Watchlist Tools
| Tool | Description |
|------|-------------|
| `get_watchlist()` | Get current watchlist |
| `add_to_watchlist(symbol, notes?)` | Add symbol to watchlist |
| `remove_from_watchlist(symbol)` | Remove symbol from watchlist |

### Alpaca MCP Server (Official)

#### Account & Positions
| Tool | Description |
|------|-------------|
| `get_account_info()` | Get account balance, margin, status |
| `get_all_positions()` | Get all current holdings |
| `get_open_position(symbol)` | Get specific position details |

#### Market Data - Stocks
| Tool | Description |
|------|-------------|
| `get_stock_bars()` | OHLCV historical bars (1Min to 1Month timeframes) |
| `get_stock_quotes()` | Historical bid/ask data |
| `get_stock_trades()` | Trade-level history |
| `get_stock_latest_bar()` | Most recent OHLC bar |
| `get_stock_latest_quote()` | Real-time bid/ask |
| `get_stock_latest_trade()` | Latest market price |
| `get_stock_snapshot()` | Comprehensive quote, trade, minute bar, daily bar |

#### Market Data - Crypto
| Tool | Description |
|------|-------------|
| `get_crypto_bars()` | Historical price bars with configurable timeframe |
| `get_crypto_quotes()` | Historical bid/ask data |
| `get_crypto_trades()` | Historical trade prints |
| `get_crypto_latest_quote()` | Real-time quotes |
| `get_crypto_latest_bar()` | Latest minute bar |
| `get_crypto_latest_trade()` | Latest trade |
| `get_crypto_snapshot()` | Comprehensive crypto snapshot |
| `get_crypto_latest_orderbook()` | Current order book |

#### Market Data - Options
| Tool | Description |
|------|-------------|
| `get_option_contracts()` | Contracts with filtering by expiration, strike, type |
| `get_option_latest_quote()` | Latest bid/ask on contracts |
| `get_option_snapshot()` | Greeks and underlying asset info |

#### Trading - Orders
| Tool | Description |
|------|-------------|
| `get_orders()` | Retrieve all or filtered orders |
| `place_stock_order()` | Market, limit, stop, stop-limit, trailing-stop orders |
| `place_crypto_order()` | Market, limit, stop-limit with GTC/IOC |
| `place_option_market_order()` | Single or multi-leg option strategies |

#### Trading - Position Management
| Tool | Description |
|------|-------------|
| `cancel_all_orders()` | Cancel all open orders |
| `cancel_order_by_id()` | Cancel specific order |
| `close_position()` | Close part or entire position |
| `close_all_positions()` | Liquidate entire portfolio |
| `exercise_options_position()` | Exercise option contract |

#### Watchlists
| Tool | Description |
|------|-------------|
| `create_watchlist()` | Create new list with symbols |
| `get_watchlists()` | Get all saved lists |
| `update_watchlist_by_id()` | Modify existing list |
| `get_watchlist_by_id()` | Get specific watchlist details |
| `add_asset_to_watchlist_by_id()` | Add symbol to watchlist |
| `remove_asset_from_watchlist_by_id()` | Remove symbol from watchlist |
| `delete_watchlist_by_id()` | Delete watchlist |

#### Market Calendar & Status
| Tool | Description |
|------|-------------|
| `get_calendar()` | Get holidays and trading days |
| `get_clock()` | Get market open/close schedule and status |

#### Assets & Corporate Actions
| Tool | Description |
|------|-------------|
| `get_asset()` | Search asset metadata |
| `get_all_assets()` | List all tradable instruments with filtering |
| `get_corporate_actions()` | Historical and future earnings, dividends, splits |

#### Portfolio
| Tool | Description |
|------|-------------|
| `get_portfolio_history()` | Account equity and P/L over time |

## Available Resources (Trading Engine)

| Resource URI | Description |
|--------------|-------------|
| `alerts://recent` | Recent alerts |
| `alerts://unread` | Unread alerts |
| `rules://active` | Active rules configuration |
| `stats://daily` | Daily statistics summary |
| `watchlist://current` | Current watchlist |

## Example Usage

Once configured, you can interact with your trading engine using natural language:

### Alert & Rule Management (Trading Engine)
```
"Why did NVDA trigger an alert?"
"Show me all alerts from today"
"Create a rule to alert when tech stocks drop 5%"
"Which stocks on my watchlist look bullish?"
"What's my alert success rate this week?"
```

### Market Data & Trading (Alpaca)
```
"What's the current price of AAPL?"
"Show me TSLA's price history for the last week"
"What positions do I have open?"
"Buy 10 shares of MSFT at market price"
"What's my account balance?"
"Is the market open right now?"
```

### Combined Workflows
```
"Check my alerts, then get the current price for any triggered symbols"
"Analyze my watchlist and show me the latest quotes for bullish stocks"
"What options are available for NVDA expiring this month?"
```

## Troubleshooting

### MCP Server Won't Start

1. Check Python path: `which python` or `where python`
2. Verify uv is installed: `uv --version`
3. Run the test script: `uv run python scripts/test_mcp_connection.py`

### Alpaca MCP Issues

1. Verify credentials: `uvx alpaca-mcp-server status`
2. Re-initialize: `uvx alpaca-mcp-server init`
3. Check that API keys are valid at [app.alpaca.markets](https://app.alpaca.markets)

### Database Connection Errors

1. Ensure DATABASE_URL is set correctly
2. For SQLite, verify the database file exists
3. For PostgreSQL, verify the connection string is correct

### Claude Desktop Not Detecting Server

1. Verify the config file path is correct
2. Check the paths point to the correct directories
3. Restart Claude Desktop after config changes
4. Check Claude Desktop logs for errors

## Environment Variables

### Trading Engine MCP
| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `sqlite+aiosqlite:///./trading_engine.db` |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `LOG_FILE` | Path to log file (if not set, logs to stderr) | None |

### Alpaca MCP
| Variable | Description | Default |
|----------|-------------|---------|
| `ALPACA_API_KEY` | Alpaca API key | Required |
| `ALPACA_SECRET_KEY` | Alpaca secret key | Required |
| `ALPACA_PAPER_TRADE` | Use paper trading (true/false) | `true` |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Claude / AI Assistant                     │
└──────────────────────────────┬──────────────────────────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                 │
              ▼                                 ▼
┌─────────────────────────┐       ┌─────────────────────────┐
│   Trading Engine MCP    │       │     Alpaca MCP Server   │
│      (This Server)      │       │     (Official)          │
│                         │       │                         │
│  • Alert Tools (5)      │       │  • Account (3)          │
│  • Rule Management (5)  │       │  • Stock Data (7)       │
│  • Analysis (4)         │       │  • Crypto Data (8)      │
│  • Watchlist (3)        │       │  • Options Data (3)     │
│  • Resources (5)        │       │  • Trading (8)          │
│                         │       │  • Watchlists (7)       │
│  Total: 17 tools        │       │  • Calendar (2)         │
│         5 resources     │       │  • Assets (3)           │
│                         │       │  • Portfolio (1)        │
│                         │       │                         │
│                         │       │  Total: 43 tools        │
└───────────┬─────────────┘       └──────────────┬──────────┘
            │                                    │
            ▼                                    ▼
┌─────────────────────────┐       ┌─────────────────────────┐
│  Trading Engine DB      │       │   Alpaca Markets API    │
│  (SQLite/PostgreSQL)    │       │   (Paper or Live)       │
└─────────────────────────┘       └─────────────────────────┘
```

## Live Trading

To switch from paper to live trading with Alpaca:

1. Get live trading API keys from Alpaca
2. Update `ALPACA_PAPER_TRADE` to `false` in your config
3. Update API keys in your Claude Desktop config
4. Restart Claude Desktop

**Warning:** Live trading involves real money. Always test thoroughly with paper trading first.

## References

- [Alpaca MCP Server GitHub](https://github.com/alpacahq/alpaca-mcp-server)
- [Alpaca MCP Documentation](https://docs.alpaca.markets/docs/alpaca-mcp-server)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Alpaca Markets](https://alpaca.markets/)
