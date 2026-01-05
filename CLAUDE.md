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

### Remaining Tasks

#### Phase 1 (Remaining)
- [ ] Generate TypeScript types from OpenAPI spec (`npm run generate-types`)
- [ ] Set up Docker configuration
- [ ] Configure Alembic migrations
- [ ] Create `.env.example` file
- [ ] Create `.gitignore` file

#### Phase 2 (Remaining)
- [ ] Implement Alpaca client wrapper (`alpaca_client.py`)
- [ ] Implement stream manager for real-time data (`stream_manager.py`)
- [ ] Implement alert generator service

#### Phase 3: Testing
- [ ] Backend unit tests (pytest)
- [ ] Backend integration tests
- [ ] Frontend component tests (vitest)

#### Phase 4: Documentation & Deployment
- [ ] Complete README.md with setup instructions
- [ ] Docker Compose configuration
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
│   │   │   ├── v1/
│   │   │   │   ├── router.py
│   │   │   │   ├── alerts.py
│   │   │   │   ├── rules.py
│   │   │   │   ├── watchlist.py
│   │   │   │   ├── market_data.py
│   │   │   │   └── websocket.py
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
│   │   └── engine/
│   │       └── rule_engine.py
│   ├── rules/
│   │   └── default_rules.yaml
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── main.jsx
│   │   ├── App.jsx
│   │   ├── App.css
│   │   ├── index.css
│   │   ├── components/
│   │   │   └── common/
│   │   │       └── Layout.jsx
│   │   ├── hooks/
│   │   │   └── useWebSocket.js
│   │   ├── services/
│   │   │   └── api.js
│   │   ├── store/
│   │   │   └── index.js
│   │   └── pages/
│   │       ├── DashboardPage.jsx
│   │       ├── AlertsPage.jsx
│   │       ├── RulesPage.jsx
│   │       └── SettingsPage.jsx
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   └── postcss.config.js
├── openapi/
│   └── spec.yaml                # Master API contract
├── PLAN.md                      # Implementation plan
├── CLAUDE.md                    # This file
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

## Next Steps

When continuing development, start with:

1. **Generate TypeScript types**:
   ```bash
   cd frontend
   npm run generate-types
   ```

2. **Set up Docker configuration** (docker-compose.yml)

3. **Configure Alembic migrations**:
   ```bash
   cd backend
   uv run alembic init alembic
   # Configure alembic.ini and env.py
   uv run alembic revision --autogenerate -m "Initial migration"
   uv run alembic upgrade head
   ```

4. **Create environment files** (.env.example, .gitignore)

5. **Implement Alpaca integration** (alpaca_client.py, stream_manager.py)

## Design Decisions

- **Design-First API**: OpenAPI spec is written first, then implemented
- **WebSocket for real-time**: Alerts broadcast via WebSocket to all connected clients
- **YAML for rules**: Human-readable rule configuration
- **Zustand for state**: Lightweight state management in React
- **SQLAlchemy async**: Async database operations for better performance
