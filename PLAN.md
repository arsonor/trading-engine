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

### Phase 7: Documentation & Deployment
- [ ] Complete README with setup instructions
- [x] Update CLAUDE.md with specifications
- [ ] Configure production docker-compose
- [ ] Add nginx reverse proxy config

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
