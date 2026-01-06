# Trading Engine - Project Specifications

## Project Overview

A real-time trading alert system that connects to Alpaca Markets API to monitor stocks and generate trading alerts based on configurable rules.

## Tech Stack

- **Backend**: FastAPI (Python 3.10+) with uv package manager
- **Frontend**: React 19 + Vite (JavaScript)
- **Database**: SQLite (dev) / PostgreSQL (prod) with SQLAlchemy ORM
- **Real-time**: WebSocket for live updates
- **Rules Configuration**: YAML files
- **API Contract**: Design-First OpenAPI specification

## Current Implementation Status

### Completed

#### Phase 1: Project Setup
- [x] OpenAPI specification (`openapi/spec.yaml`) - Full API contract defined
- [x] Backend initialized with uv (`backend/`)
- [x] Frontend initialized with Vite + React (`frontend/`)
- [x] Tailwind CSS configured

#### Phase 2: Backend Core
- [x] `backend/app/config.py` - Pydantic settings with env vars
- [x] `backend/app/core/database.py` - SQLAlchemy async setup
- [x] `backend/app/models/` - Alert, Rule, Watchlist models
- [x] `backend/app/schemas/` - Pydantic schemas for API
- [x] `backend/app/engine/rule_engine.py` - Rule evaluation logic
- [x] `backend/rules/default_rules.yaml` - Default trading rules

#### Phase 3: API Layer
- [x] `backend/app/main.py` - FastAPI entry point
- [x] `backend/app/api/v1/alerts.py` - Alert CRUD endpoints
- [x] `backend/app/api/v1/rules.py` - Rules CRUD endpoints
- [x] `backend/app/api/v1/watchlist.py` - Watchlist endpoints
- [x] `backend/app/api/v1/market_data.py` - Market data endpoints (demo)
- [x] `backend/app/api/v1/websocket.py` - WebSocket endpoint

#### Phase 4: Frontend
- [x] `frontend/src/services/api.js` - Axios API client
- [x] `frontend/src/hooks/useWebSocket.js` - WebSocket hook
- [x] `frontend/src/store/index.js` - Zustand state management
- [x] `frontend/src/components/common/Layout.jsx` - Main layout
- [x] `frontend/src/pages/DashboardPage.jsx` - Dashboard
- [x] `frontend/src/pages/AlertsPage.jsx` - Alerts list with filters
- [x] `frontend/src/pages/RulesPage.jsx` - Rules management
- [x] `frontend/src/pages/SettingsPage.jsx` - Settings & watchlist

#### Phase 5: Infrastructure (Completed)
- [x] `.env.example` - Environment configuration template
- [x] `frontend/src/types/api.d.ts` - Generated TypeScript types
- [x] Alembic migrations configured (`backend/alembic/`)
- [x] Docker configuration (Dockerfiles + docker-compose.yml)
- [x] `backend/app/services/alpaca_client.py` - Alpaca API client wrapper
- [x] `backend/app/services/stream_manager.py` - Real-time data streaming

#### Phase 6: Testing (Completed)
- [x] Backend unit tests (pytest) - 118 tests
  - `backend/tests/unit/test_rule_engine.py` - Rule engine unit tests (59 tests)
  - `backend/tests/unit/test_api_alerts.py` - Alerts API tests (16 tests)
  - `backend/tests/unit/test_api_rules.py` - Rules API tests (27 tests)
  - `backend/tests/unit/test_api_watchlist.py` - Watchlist API tests (16 tests)
- [x] Backend integration tests - 38 tests
  - `backend/tests/integration/test_websocket.py` - WebSocket integration tests (24 tests)
  - `backend/tests/integration/test_workflows.py` - Cross-component workflow tests (14 tests)
    - Alert lifecycle workflows (create, read, update, filter, stats)
    - Rule management with cascade deletes
    - Rule engine evaluation integration
    - Watchlist management workflows
    - Cross-component workflows (complete trading alert flow)
- [x] Frontend component tests (vitest) - 60 tests
  - `frontend/src/test/components/Layout.test.jsx` - Layout component tests (7 tests)
  - `frontend/src/test/hooks/useWebSocket.test.js` - WebSocket hook tests (12 tests)
  - `frontend/src/test/services/api.test.js` - API service tests (18 tests)
  - `frontend/src/test/store/index.test.js` - Zustand store tests (23 tests)
- [x] Total: 216 tests (156 backend + 60 frontend), ~55% backend code coverage

### Remaining Tasks

#### Phase 7: Documentation & Deployment
- [ ] Complete README.md with setup instructions
- [ ] Production deployment config

## How to Run (Development)

### Backend
```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## File Structure

```
trading-engine/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI entry
│   │   ├── config.py            # Settings
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── router.py
│   │   │       ├── alerts.py
│   │   │       ├── rules.py
│   │   │       ├── watchlist.py
│   │   │       ├── market_data.py
│   │   │       └── websocket.py
│   │   ├── core/
│   │   │   └── database.py
│   │   ├── models/
│   │   │   ├── alert.py
│   │   │   ├── rule.py
│   │   │   └── watchlist.py
│   │   ├── schemas/
│   │   │   ├── alert.py
│   │   │   ├── rule.py
│   │   │   ├── watchlist.py
│   │   │   ├── market_data.py
│   │   │   └── common.py
│   │   ├── services/
│   │   │   ├── alpaca_client.py  # Alpaca API wrapper
│   │   │   └── stream_manager.py # Real-time streaming
│   │   └── engine/
│   │       └── rule_engine.py
│   ├── alembic/                  # Database migrations
│   │   ├── env.py
│   │   └── versions/
│   ├── rules/
│   │   └── default_rules.yaml
│   ├── tests/
│   │   ├── conftest.py           # Test fixtures
│   │   ├── unit/
│   │   │   ├── test_rule_engine.py
│   │   │   ├── test_api_alerts.py
│   │   │   ├── test_api_rules.py
│   │   │   └── test_api_watchlist.py
│   │   └── integration/
│   │       ├── test_websocket.py
│   │       └── test_workflows.py # Cross-component workflow tests
│   ├── Dockerfile
│   ├── alembic.ini
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── main.jsx
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   └── common/
│   │   │       └── Layout.jsx
│   │   ├── hooks/
│   │   │   └── useWebSocket.js
│   │   ├── services/
│   │   │   └── api.js
│   │   ├── store/
│   │   │   └── index.js
│   │   ├── test/                  # Test files
│   │   │   ├── setup.js
│   │   │   ├── components/
│   │   │   │   └── Layout.test.jsx
│   │   │   ├── hooks/
│   │   │   │   └── useWebSocket.test.js
│   │   │   ├── services/
│   │   │   │   └── api.test.js
│   │   │   └── store/
│   │   │       └── index.test.js
│   │   ├── types/
│   │   │   └── api.d.ts          # Generated from OpenAPI
│   │   └── pages/
│   │       ├── DashboardPage.jsx
│   │       ├── AlertsPage.jsx
│   │       ├── RulesPage.jsx
│   │       └── SettingsPage.jsx
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
├── openapi/
│   └── spec.yaml                 # Master API contract
├── docker-compose.yml            # Production setup
├── docker-compose.dev.yml        # Development (DB only)
├── .env.example
├── PLAN.md
├── CLAUDE.md
└── README.md
```

## API Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/v1/alerts` | List alerts |
| GET | `/api/v1/alerts/{id}` | Get alert |
| PATCH | `/api/v1/alerts/{id}` | Update alert |
| GET | `/api/v1/alerts/stats` | Alert statistics |
| GET | `/api/v1/rules` | List rules |
| POST | `/api/v1/rules` | Create rule |
| PUT | `/api/v1/rules/{id}` | Update rule |
| DELETE | `/api/v1/rules/{id}` | Delete rule |
| POST | `/api/v1/rules/{id}/toggle` | Toggle rule |
| GET | `/api/v1/watchlist` | Get watchlist |
| POST | `/api/v1/watchlist` | Add to watchlist |
| DELETE | `/api/v1/watchlist/{symbol}` | Remove from watchlist |
| GET | `/api/v1/market-data/{symbol}` | Get market data |
| WS | `/api/v1/ws` | WebSocket endpoint |

## Environment Variables

```
# Backend (.env)
APP_ENV=development
DEBUG=true
DATABASE_URL=sqlite+aiosqlite:///./trading_engine.db
ALPACA_API_KEY=your_api_key
ALPACA_SECRET_KEY=your_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
CORS_ORIGINS=http://localhost:5173

# Frontend (.env)
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

## Running Tests

### Backend Tests
```bash
cd backend

# Run all tests
uv run pytest -v

# Run unit tests only
uv run pytest tests/unit -v

# Run integration tests only
uv run pytest tests/integration -v

# Run with coverage
uv run pytest --cov=app --cov-report=term-missing
```

### Frontend Tests
```bash
cd frontend

# Run all tests
npm test

# Run tests in watch mode
npm test -- --watch

# Run with coverage
npm run test:coverage
```

## Next Steps

When continuing development, the remaining tasks are:

1. **Complete README.md** with full setup instructions
2. **Production deployment configuration**

## Docker Usage

### Development (database only)
```bash
docker-compose -f docker-compose.dev.yml up -d
```

### Production (full stack)
```bash
# Copy .env.example to .env and fill in values
cp .env.example .env
docker-compose up -d
```

### Run migrations in container
```bash
docker-compose exec backend uv run alembic upgrade head
```

## Design Decisions

- **Design-First API**: OpenAPI spec is written first, then implemented
- **WebSocket for real-time**: Alerts broadcast via WebSocket to all connected clients
- **YAML for rules**: Human-readable rule configuration
- **Zustand for state**: Lightweight state management in React
- **SQLAlchemy async**: Async database operations for better performance
