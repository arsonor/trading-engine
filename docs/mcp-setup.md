# MCP (Model Context Protocol) Setup Guide

This guide explains how to set up and use the Trading Engine MCP server with AI assistants like Claude.

## Overview

The Trading Engine uses a hybrid MCP architecture:

1. **Trading Engine MCP Server** (Custom) - Alerts, rules, analysis, historical data
2. **Alpaca MCP Server** (Official) - Market data, trading, portfolio management

## Prerequisites

- Python 3.10+
- uv package manager
- Claude Desktop or Claude Code CLI
- (Optional) Alpaca Markets paper trading account

## Installation

### 1. Install Dependencies

```bash
cd backend
uv sync
```

### 2. Verify Installation

```bash
uv run python scripts/test_mcp_connection.py
```

This script verifies:
- MCP SDK is installed correctly
- Server can be instantiated
- Database connection works

## Running the MCP Server

### Standalone (for testing)

```bash
cd backend
uv run python -m app.mcp.server
```

Or use the convenience script:

```bash
uv run python scripts/run_mcp_server.py
```

### With Claude Desktop

1. Locate your Claude Desktop configuration file:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **Linux**: `~/.config/Claude/claude_desktop_config.json`

2. Add the Trading Engine MCP server configuration:

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
    }
  }
}
```

**Important:** Replace the paths with your actual project location. Use forward slashes (`/`) even on Windows.

3. Restart Claude Desktop

### With Claude Code CLI

Add to your Claude Code MCP settings:

```json
{
  "mcpServers": {
    "trading-engine": {
      "command": "uv",
      "args": ["run", "python", "-m", "app.mcp.server"],
      "cwd": "/path/to/trading-engine/backend"
    }
  }
}
```

## Available Tools

### Alert Tools (Phase 9.3)
- `explain_alert(alert_id)` - Get detailed explanation of why an alert triggered
- `list_alerts(symbol?, limit?, setup_type?)` - List recent alerts with optional filters
- `get_alert_by_id(alert_id)` - Get specific alert details
- `mark_alert_read(alert_id)` - Mark an alert as read
- `get_alert_statistics(days?)` - Get alert statistics for performance tracking

### Rule Management Tools (Phase 9.4)
- `list_rules(active_only?)` - List all trading rules
- `get_rule(rule_id)` - Get rule details with configuration
- `create_rule_from_description(name, description, conditions)` - Create rule from natural language
- `toggle_rule(rule_id)` - Enable/disable a rule
- `delete_rule(rule_id)` - Remove a rule

### Analysis Tools (Phase 9.5)
- `analyze_watchlist()` - Analyze all watched stocks for bullish/bearish signals
- `get_symbol_analysis(symbol)` - Deep analysis of a single symbol
- `compare_symbols(symbols[])` - Compare multiple symbols
- `get_top_performers(days?, limit?)` - Get best performing alerts

### Watchlist Tools (Phase 9.6)
- `get_watchlist()` - Get current watchlist
- `add_to_watchlist(symbol, notes?)` - Add symbol to watchlist
- `remove_from_watchlist(symbol)` - Remove symbol from watchlist

## Available Resources (Phase 9.7)

- `alerts://recent` - Recent alerts
- `alerts://unread` - Unread alerts
- `rules://active` - Active rules configuration
- `stats://daily` - Daily statistics summary
- `watchlist://current` - Current watchlist

## Example Usage

Once configured, you can interact with your trading engine using natural language:

```
"Why did NVDA trigger an alert?"
"Show me all alerts from today"
"Create a rule to alert when tech stocks drop 5%"
"Which stocks on my watchlist look bullish?"
"What's my alert success rate this week?"
```

## Troubleshooting

### MCP Server Won't Start

1. Check Python path: `which python` or `where python`
2. Verify uv is installed: `uv --version`
3. Run the test script: `uv run python scripts/test_mcp_connection.py`

### Database Connection Errors

1. Ensure DATABASE_URL is set correctly
2. For SQLite, verify the database file exists
3. For PostgreSQL, verify the connection string is correct

### Claude Desktop Not Detecting Server

1. Verify the config file path is correct
2. Check the `cwd` path points to the backend directory
3. Restart Claude Desktop after config changes

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `sqlite+aiosqlite:///./trading_engine.db` |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `LOG_FILE` | Path to log file (if not set, logs to stderr) | None |

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
│  • Alert Tools          │       │  • Market Data          │
│  • Rule Management      │       │  • Trading              │
│  • Analysis             │       │  • Portfolio            │
│  • Watchlist            │       │  • Account              │
└───────────┬─────────────┘       └──────────────┬──────────┘
            │                                    │
            ▼                                    ▼
┌─────────────────────────┐       ┌─────────────────────────┐
│  Trading Engine DB      │       │   Alpaca Markets API    │
│  (SQLite/PostgreSQL)    │       │                         │
└─────────────────────────┘       └─────────────────────────┘
```
