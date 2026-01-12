# Trading Engine Implementation Plan

## Overview

Build a real-time trading alert system with:
- **Backend**: FastAPI (Python 3.10+) with uv package manager
- **Frontend**: React + Vite (JavaScript)
- **Data Source**: Alpaca Markets API (paper account)
- **Real-time**: WebSocket for live updates
- **Database**: SQLite (dev) / PostgreSQL (prod)
- **Rules**: YAML configuration files
- **Containerization**: Docker + docker-compose
- **API Contract**: Design-First OpenAPI specification

---

## API Contract Management (Design-First)

### Strategy
The OpenAPI specification is the **single source of truth** for the API contract between frontend and backend.

### Workflow
1. **Write OpenAPI spec first** (`openapi/spec.yaml`) before implementing endpoints
2. **Generate TypeScript types** for frontend from the spec
3. **Validate FastAPI implementation** matches the spec in CI

### Tools
- **openapi-typescript**: Generate TypeScript types from OpenAPI spec
- **openapi-spec-validator**: Validate the OpenAPI spec is valid

---

## Project Structure

```
trading-engine/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI entry point
│   │   ├── config.py                  # Settings (Pydantic)
│   │   ├── api/v1/
│   │   │   ├── router.py              # API router
│   │   │   ├── alerts.py              # Alert endpoints
│   │   │   ├── rules.py               # Rules CRUD
│   │   │   ├── watchlist.py           # Watchlist endpoints
│   │   │   └── websocket.py           # WebSocket endpoint
│   │   ├── models/                    # SQLAlchemy models
│   │   ├── schemas/                   # Pydantic schemas
│   │   ├── engine/
│   │   │   └── rule_engine.py         # Rule evaluation
│   │   └── utils/
│   ├── rules/                         # YAML rule configs
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── store/
│   │   └── pages/
│   ├── package.json
│   └── Dockerfile
├── openapi/
│   └── spec.yaml                      # Master OpenAPI specification
├── docker/
├── .env.example
├── README.md
├── CLAUDE.md
└── PLAN.md
```

---

## Database Schema

### Tables

1. **alerts** - id, rule_id (FK), symbol, timestamp, setup_type, entry_price, stop_loss, target_price, confidence_score, market_data_json, is_read, created_at

2. **rules** - id, name, description, rule_type, config_yaml, is_active, priority, created_at, updated_at

3. **watchlist** - id, symbol, added_at, is_active, notes

---

## API Endpoints

### REST API (`/api/v1`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/alerts` | List alerts (paginated, filterable) |
| GET | `/alerts/{id}` | Get alert by ID |
| PATCH | `/alerts/{id}` | Update alert (mark read) |
| GET | `/alerts/stats` | Alert statistics |
| GET | `/rules` | List all rules |
| POST | `/rules` | Create rule |
| PUT | `/rules/{id}` | Update rule |
| DELETE | `/rules/{id}` | Delete rule |
| POST | `/rules/{id}/toggle` | Toggle rule active |
| GET | `/watchlist` | Get watchlist |
| POST | `/watchlist` | Add symbol |
| DELETE | `/watchlist/{symbol}` | Remove symbol |
| GET | `/market-data/{symbol}` | Current market data |
| GET | `/market-data/{symbol}/history` | Historical bars |

### WebSocket (`/api/v1/ws`)

```json
{"action": "subscribe", "channel": "alerts"}
{"action": "subscribe", "channel": "market_data", "symbols": ["AAPL"]}
```

---

## Implementation Phases

### Phase 1: API Contract & Project Setup (COMPLETED)
- [x] Write OpenAPI specification (`openapi/spec.yaml`)
- [x] Initialize backend with uv
- [x] Initialize frontend with Vite
- [x] Generate TypeScript types from OpenAPI spec
- [x] Set up Docker configuration
- [x] Configure database (Alembic migrations)
- [x] Create `.env.example` with all config options

### Phase 2: Core Backend (COMPLETED)
- [x] Implement config.py with Pydantic settings
- [x] Create SQLAlchemy models (Alert, Rule, Watchlist)
- [x] Implement API endpoints
- [x] Implement rule engine
- [x] Create default rules YAML

### Phase 3: Rule Engine & Alerts (COMPLETED)
- [x] Build rule evaluation engine
- [x] Create Alpaca client wrapper
- [x] Create stream manager for Alpaca WebSocket
- [x] Create alert generator service (connects StreamManager → RuleEngine → Alerts → WebSocket)

### Phase 4: API Layer (COMPLETED)
- [x] Implement REST endpoints for alerts, rules, watchlist
- [x] Add pagination and filtering
- [x] Create WebSocket endpoint for clients
- [x] Add health check endpoint

### Phase 5: Frontend (COMPLETED)
- [x] Set up React Router and Zustand store
- [x] Create WebSocket hook for real-time updates
- [x] Build Dashboard page with stats panel
- [x] Build Alerts page with filtering/search
- [x] Build Rules page with enable/disable toggle
- [x] Build Settings page
- [x] Add responsive styling with Tailwind CSS

### Phase 6: Testing (COMPLETED)
- [x] Unit tests for rule engine
- [x] Unit tests for alert service (alerts API)
- [x] Integration tests for API endpoints (rules, watchlist APIs)
- [x] Integration tests for WebSocket
- [x] Frontend component tests (Layout, hooks, services, store)

### Phase 7: Documentation & Deployment (COMPLETED)
- [x] Complete README with setup instructions
- [x] Update CLAUDE.md with specifications
- [x] Configure production docker-compose
- [x] Add nginx reverse proxy config

### Phase 8: CI/CD & Cloud Deployment (COMPLETED)
- [x] GitHub Actions CI/CD pipeline (`.github/workflows/ci-cd.yml`)
- [x] Render.com deployment blueprint (`render.yaml`)
- [x] PostgreSQL database on Render (free tier)
- [x] Backend API service with automatic migrations
- [x] Frontend static site with SPA routing
- [x] Live deployment URLs configured

---

## Phase 9: MCP (Model Context Protocol) Integration

### Overview

Implement MCP servers to enable AI assistants (Claude, ChatGPT) to interact with the trading engine using natural language. This uses a **hybrid architecture**:

1. **Alpaca MCP Server** (Official) - Market data, trading, portfolio management
2. **Trading Engine MCP Server** (Custom) - Alerts, rules, analysis, historical data

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Claude / AI Assistant                          │
│                                                                          │
│  "Why did NVDA trigger?"  "Show bullish stocks"  "Place order for AAPL" │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                 │
              ▼                                 ▼
┌─────────────────────────┐       ┌─────────────────────────────┐
│   Trading Engine MCP    │       │     Alpaca MCP Server       │
│      (Custom)           │       │     (Official)              │
│                         │       │                             │
│  Tools:                 │       │  Tools:                     │
│  • explain_alert        │       │  • get_quote                │
│  • list_alerts          │       │  • place_order              │
│  • create_rule          │       │  • get_positions            │
│  • analyze_watchlist    │       │  • get_portfolio_history    │
│  • get_alert_stats      │       │  • get_news                 │
│  • query_historical     │       │  • get_bars                 │
│                         │       │  • (43 endpoints total)     │
│  Resources:             │       │                             │
│  • alerts://recent      │       │                             │
│  • rules://active       │       │                             │
│  • stats://daily        │       │                             │
└───────────┬─────────────┘       └──────────────┬──────────────┘
            │                                    │
            ▼                                    ▼
┌─────────────────────────┐       ┌─────────────────────────────┐
│  Trading Engine Backend │       │      Alpaca Markets API     │
│  (PostgreSQL + FastAPI) │       │                             │
└─────────────────────────┘       └─────────────────────────────┘
```

### Use Cases

| Use Case | Example Prompt | MCP Server | Tool(s) |
|----------|----------------|------------|---------|
| Alert Explanation | "Why did NVDA trigger an alert?" | Trading Engine | `explain_alert` |
| Natural Language Rules | "Alert me when tech stocks drop 5%" | Trading Engine | `create_rule_from_description` |
| Market Analysis | "Which watched stocks look bullish?" | Trading Engine | `analyze_watchlist` |
| Performance Tracking | "How many alerts triggered this week?" | Trading Engine | `get_alert_statistics` |
| Trade Execution | "Buy 10 shares of AAPL" | Alpaca | `place_order` |
| Portfolio Check | "What's my current portfolio value?" | Alpaca | `get_account`, `get_positions` |
| Market Data | "Show me NVDA's price history" | Alpaca | `get_bars` |
| News Sentiment | "Any news affecting my watchlist?" | Alpaca | `get_news` |

### Implementation Tasks

#### Phase 9.1: Project Setup & Dependencies
- [ ] Add MCP SDK to backend dependencies (`mcp[cli]>=1.2.0`)
- [ ] Create MCP module structure (`backend/app/mcp/`)
- [ ] Set up MCP server configuration
- [ ] Create development scripts for testing MCP locally

#### Phase 9.2: Core MCP Server Implementation
- [ ] Create FastMCP server instance (`backend/app/mcp/server.py`)
- [ ] Implement database session management for MCP
- [ ] Set up logging (avoid stdout for STDIO transport)
- [ ] Create base tool decorators and error handling

#### Phase 9.3: Alert Tools
- [ ] `explain_alert(alert_id)` - Detailed explanation of why alert triggered
- [ ] `list_alerts(symbol?, limit?, setup_type?)` - List recent alerts with filters
- [ ] `get_alert_by_id(alert_id)` - Get specific alert details
- [ ] `mark_alert_read(alert_id)` - Mark alert as read
- [ ] `get_alert_statistics(days?)` - Alert stats for performance tracking

#### Phase 9.4: Rule Management Tools
- [ ] `list_rules(active_only?)` - List all trading rules
- [ ] `get_rule(rule_id)` - Get rule details with config
- [ ] `create_rule_from_description(name, description, conditions)` - NL rule creation
- [ ] `toggle_rule(rule_id)` - Enable/disable rule
- [ ] `delete_rule(rule_id)` - Remove rule

#### Phase 9.5: Analysis Tools
- [ ] `analyze_watchlist()` - Analyze all watched stocks, return bullish/bearish signals
- [ ] `get_symbol_analysis(symbol)` - Deep analysis of single symbol
- [ ] `compare_symbols(symbols[])` - Compare multiple symbols
- [ ] `get_top_performers(days?, limit?)` - Best performing alerts

#### Phase 9.6: Watchlist Tools
- [ ] `get_watchlist()` - Get current watchlist
- [ ] `add_to_watchlist(symbol, notes?)` - Add symbol
- [ ] `remove_from_watchlist(symbol)` - Remove symbol

#### Phase 9.7: MCP Resources (Read-only Data)
- [ ] `alerts://recent` - Recent alerts as resource
- [ ] `alerts://unread` - Unread alerts
- [ ] `rules://active` - Active rules configuration
- [ ] `stats://daily` - Daily statistics summary
- [ ] `watchlist://current` - Current watchlist

#### Phase 9.8: Alpaca MCP Integration
- [ ] Clone and configure Alpaca MCP server
- [ ] Test Alpaca MCP tools locally
- [ ] Document available Alpaca tools for reference
- [ ] Create combined configuration for both servers

#### Phase 9.9: Claude Desktop Configuration
- [ ] Create `claude_desktop_config.json` template
- [ ] Document setup instructions for Claude Desktop
- [ ] Document setup instructions for Claude Code CLI
- [ ] Test both MCP servers together

#### Phase 9.10: Testing & Documentation
- [ ] Unit tests for MCP tools
- [ ] Integration tests with mock database
- [ ] Update README with MCP setup instructions
- [ ] Create MCP-specific documentation
- [ ] Add example prompts and responses

### File Structure (New)

```
backend/
├── app/
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── server.py              # FastMCP server definition
│   │   ├── config.py              # MCP-specific configuration
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── alerts.py          # Alert-related tools
│   │   │   ├── rules.py           # Rule management tools
│   │   │   ├── analysis.py        # Analysis tools
│   │   │   └── watchlist.py       # Watchlist tools
│   │   └── resources/
│   │       ├── __init__.py
│   │       └── data.py            # MCP resources
│   └── ...
├── tests/
│   └── unit/
│       └── test_mcp_tools.py      # MCP tools tests
└── ...

docs/
├── mcp-setup.md                   # MCP installation guide
└── mcp-examples.md                # Example prompts and responses

config/
└── claude_desktop_config.json     # Template for Claude Desktop
```

### Configuration Templates

#### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "trading-engine": {
      "command": "uv",
      "args": ["run", "python", "-m", "app.mcp.server"],
      "cwd": "/path/to/trading-engine/backend",
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@host/db"
      }
    },
    "alpaca": {
      "command": "uv",
      "args": ["run", "alpaca-mcp-server"],
      "cwd": "/path/to/alpaca-mcp-server",
      "env": {
        "ALPACA_API_KEY": "your_key",
        "ALPACA_SECRET_KEY": "your_secret",
        "ALPACA_BASE_URL": "https://paper-api.alpaca.markets"
      }
    }
  }
}
```

### Dependencies

```toml
# backend/pyproject.toml additions
[project.dependencies]
mcp = { version = ">=1.2.0", extras = ["cli"] }
```

### Success Criteria

1. **Alert Explanation**: User asks "Why did AAPL alert?" → Returns detailed rule analysis
2. **Natural Language Rules**: User says "Alert when price > 100" → Rule created in database
3. **Watchlist Analysis**: User asks "Which stocks look good?" → Returns ranked analysis
4. **Statistics**: User asks "How did my alerts perform?" → Returns performance metrics
5. **Integration**: Both MCP servers work together in Claude Desktop

---

## Environment Variables

```bash
# Alpaca API
ALPACA_API_KEY=your_api_key
ALPACA_SECRET_KEY=your_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Database
DATABASE_URL=sqlite+aiosqlite:///./trading_engine.db

# Frontend
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```
