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
- [x] Backend unit tests (pytest) - 155 tests
  - `backend/tests/unit/test_rule_engine.py` - Rule engine unit tests
  - `backend/tests/unit/test_api_alerts.py` - Alerts API tests
  - `backend/tests/unit/test_api_rules.py` - Rules API tests
  - `backend/tests/unit/test_api_watchlist.py` - Watchlist API tests
  - `backend/tests/unit/test_alert_generator.py` - Alert generator unit tests
- [x] Backend integration tests - 48 tests
  - `backend/tests/integration/test_websocket.py` - WebSocket integration tests
  - `backend/tests/integration/test_workflows.py` - Cross-component workflow tests
    - Alert lifecycle workflows (create, read, update, filter, stats)
    - Rule management with cascade deletes
    - Rule engine evaluation integration
    - Watchlist management workflows
    - Cross-component workflows (complete trading alert flow)
  - `backend/tests/integration/test_alert_generator_integration.py` - Alert generator integration tests
    - Market data → alert creation flow
    - Multiple rules triggering
    - WebSocket broadcast verification
    - Rule toggle affects alert generation
- [x] Frontend component tests (vitest) - 60 tests
  - `frontend/src/test/components/Layout.test.jsx` - Layout component tests (7 tests)
  - `frontend/src/test/hooks/useWebSocket.test.js` - WebSocket hook tests (12 tests)
  - `frontend/src/test/services/api.test.js` - API service tests (18 tests)
  - `frontend/src/test/store/index.test.js` - Zustand store tests (23 tests)
- [x] Total: 263 tests (203 backend + 60 frontend)

#### Phase 7: Alert Generation Service (Completed)
- [x] `backend/app/services/alert_generator.py` - Background service that:
  - Listens to market data callbacks from StreamManager
  - Loads active rules from database with TTL-based caching (60s)
  - Evaluates rules using RuleEngine
  - Creates Alert records when rules trigger
  - Broadcasts new alerts via WebSocket to "alerts" channel
- [x] Wired up in `main.py` lifespan with combined callbacks
- [x] Unit tests (33 tests) and integration tests (10 tests)

#### Phase 8: CI/CD & Deployment (Completed)
- [x] Complete README.md with setup instructions
- [x] GitHub Actions CI/CD pipeline (`.github/workflows/ci-cd.yml`)
  - Backend tests with pytest and ruff linter
  - Frontend tests with vitest and build verification
  - Automatic deployment to Render on main branch push
- [x] Render.com production deployment (`render.yaml`)
  - PostgreSQL database (free tier)
  - Backend API service with automatic migrations
  - Frontend static site with SPA routing
- [x] Live URLs:
  - Frontend: https://trading-engine-ui.onrender.com
  - Backend API: https://trading-engine-api-5iai.onrender.com

### Remaining Tasks

None - Project is complete!

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
│   │   │   ├── alpaca_client.py   # Alpaca API wrapper
│   │   │   ├── stream_manager.py  # Real-time streaming
│   │   │   └── alert_generator.py # Alert generation from market data
│   │   └── engine/
│   │       └── rule_engine.py
│   ├── alembic/                  # Database migrations
│   │   ├── env.py
│   │   └── versions/
│   ├── rules/
│   │   └── default_rules.yaml
│   ├── scripts/
│   │   └── seed_test_alerts.py   # Seed test data for UI testing
│   ├── tests/
│   │   ├── conftest.py           # Test fixtures
│   │   ├── unit/
│   │   │   ├── test_rule_engine.py
│   │   │   ├── test_api_alerts.py
│   │   │   ├── test_api_rules.py
│   │   │   ├── test_api_watchlist.py
│   │   │   └── test_alert_generator.py
│   │   └── integration/
│   │       ├── test_websocket.py
│   │       ├── test_workflows.py # Cross-component workflow tests
│   │       └── test_alert_generator_integration.py
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
├── .github/
│   └── workflows/
│       └── ci-cd.yml             # GitHub Actions CI/CD pipeline
├── openapi/
│   └── spec.yaml                 # Master API contract
├── docker-compose.yml            # Production setup (Docker)
├── docker-compose.dev.yml        # Development (DB only)
├── render.yaml                   # Render.com deployment blueprint
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

### Development Utilities

- **Seed test alerts**: `cd backend && uv run python scripts/seed_test_alerts.py` - Creates 20 sample alerts for UI testing

## Docker Usage

### Development (database only)
```bash
docker-compose -f docker-compose.dev.yml up -d
```

### Production (full stack)
```bash
# Copy .env.example to .env and fill in Alpaca API keys
cp .env.example .env
# Edit .env to add your ALPACA_API_KEY and ALPACA_SECRET_KEY

# Build and start all containers
docker-compose up -d --build

# Note: Migrations run automatically on backend startup
# No need to run them manually
```

### Troubleshooting Docker

If the backend container keeps restarting:
```bash
# Check logs for errors
docker logs trading-engine-backend

# Force rebuild
docker-compose down -v
docker-compose up -d --build
```

**Important**: The `.env` file's `DATABASE_URL` is only used for local development.
Docker containers use the DATABASE_URL defined in `docker-compose.yml` which points to the `db` service (not `localhost`).

## Design Decisions

- **Design-First API**: OpenAPI spec is written first, then implemented
- **WebSocket for real-time**: Alerts broadcast via WebSocket to all connected clients
- **YAML for rules**: Human-readable rule configuration
- **Zustand for state**: Lightweight state management in React
- **SQLAlchemy async**: Async database operations for better performance
