# Trading Engine

An alerts-only pre-market stock scanner. It scans a US equity universe during the pre-market session and surfaces candidates where a ~5% intraday move is structurally plausible, delivered to a mobile-first web dashboard.

**It does not execute trades, does not predict returns, and is not financial advice.** Market data comes from FMP (Financial Modeling Prep).

![Trading Dashboard](docs/trading_dashboard.png)

![Alerts Page](docs/alerts_page.png)

## Table of Contents

- [Problem Statement](#problem-statement) - Why this system exists
- [What This System Does](#what-this-system-does) - Core features and capabilities
- [System Architecture](#system-architecture) - High-level architecture diagram
- [Technology Stack](#technology-stack) - Frontend, backend, database, and infrastructure
- [Live Demo](#live-demo) - Production deployment on Render
- [Prerequisites](#prerequisites) - What you need to get started
- [Quick Start](#quick-start) - Get up and running in minutes
- [Docker Deployment](#docker-deployment) - Containerized deployment options
- [Cloud Deployment](#cloud-deployment) - Deploy to Render.com
- [CI/CD Pipeline](#cicd-pipeline) - GitHub Actions automation
- [Running Tests](#running-tests) - Backend and frontend test suites
- [Usage and Demonstration](#usage-and-demonstration) - Testing without live market data
- [API Endpoints](#api-endpoints) - REST API reference
- [Project Structure](#project-structure) - Codebase organization
- [Configuration](#configuration) - Trading rules configuration guide
- [Troubleshooting](#troubleshooting) - Common issues and solutions
- [License](#license) - MIT License

## Problem Statement

Active traders need to monitor multiple stocks simultaneously for trading opportunities, but manually watching price movements, volume spikes, and technical patterns across many securities is impractical. This creates a need for an automated system that can:

- **Scan the whole universe** each morning rather than a hand-picked list
- **Evaluate configurable trading rules** against live market data
- **Generate instant alerts** when trading setups are detected
- **Provide actionable information** including entry prices, stop losses, and profit targets

## What This System Does

The Trading Engine solves these problems by providing:

1. **Scheduled Pre-market Scanning**: A cron job runs a 3-stage filtration pipeline over the universe on a tiered cadence from 04:15 to 09:25 ET — 19 passes a session, coarse early and every 5 minutes for the last hour — using FMP market data.

2. **Configurable Rule Engine**: Define trading rules in YAML format with conditions, filters, and target calculations. Rules can detect:
   - Price breakouts above resistance levels
   - Volume spikes indicating institutional activity
   - Gap ups/downs at market open
   - Momentum patterns and technical setups

3. **Instant Alert Generation**: When market data matches rule conditions, the system generates alerts with:
   - Entry price and setup type
   - Calculated stop-loss levels
   - Profit targets based on risk/reward ratios
   - Confidence scores based on how strongly conditions are met

4. **Web Dashboard**: A React-based frontend for:
   - Viewing and managing alerts in real-time
   - Creating and editing trading rules
   - Monitoring system status and statistics

5. **WebSocket Updates**: Live push notifications ensure you see new alerts immediately without refreshing.


## System Architecture

The system consists of a React frontend, a FastAPI backend, and a scheduled scanner job, with market data from FMP.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Frontend                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │  Dashboard  │  │   Alerts    │  │    Rules    │  │  Settings   │    │
│  │    Page     │  │    Page     │  │    Page     │  │    Page     │    │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘    │
│         └─────────────────┴─────────────────┴─────────────────┘         │
│                                    │                                     │
│                          ┌─────────┴─────────┐                          │
│                          │   Zustand Store   │                          │
│                          │  + WebSocket Hook │                          │
│                          └─────────┬─────────┘                          │
└────────────────────────────────────┼────────────────────────────────────┘
                                     │ HTTP/WebSocket
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              Backend                                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                         FastAPI Server                           │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │   │
│  │  │ Scanner  │  │ Settings │  │  Status  │  │   WebSocket      │ │   │
│  │  │   API    │  │   API    │  │   API    │  │   Endpoint       │ │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘ │   │
│  └───────┼─────────────┼─────────────┼─────────────────┼───────────┘   │
│          │             │             │                 │                │
│  ┌───────┴─────────────┴─────────────┴─────────────────┴───────────┐   │
│  │                      SQLAlchemy ORM                              │   │
│  └──────────────────────────────┬───────────────────────────────────┘   │
│                                 │                                        │
│  ┌──────────────────────────────┴───────────────────────────────────┐   │
│  │                    Rule Engine                                    │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐                  │   │
│  │  │ Conditions │  │  Filters   │  │  Targets   │                  │   │
│  │  │ Evaluator  │  │  Checker   │  │ Calculator │                  │   │
│  │  └────────────┘  └────────────┘  └────────────┘                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                 │                                        │
│  ┌──────────────────────────────┴───────────────────────────────────┐   │
└─────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           External Services                              │
│  ┌─────────────────────────────┐  ┌─────────────────────────────────┐  │
│  │        PostgreSQL           │  │           FMP API               │  │
│  │         (Database)          │  │    (Market Data & Trading)      │  │
│  └─────────────────────────────┘  └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Technology Stack

### Frontend
| Technology | Purpose |
|------------|---------|
| **React 19** | UI component framework |
| **Vite** | Build tool and dev server |
| **Tailwind CSS** | Utility-first styling |
| **Zustand** | Lightweight state management |
| **Axios** | HTTP client for API calls |
| **React Router** | Client-side routing |

### Backend
| Technology | Purpose |
|------------|---------|
| **FastAPI** | High-performance async Python web framework |
| **SQLAlchemy** | Async ORM for database operations |
| **Pydantic** | Data validation and settings management |
| **uvicorn** | ASGI server |
| **websockets** | Real-time bidirectional communication |
| **PyYAML** | Rule configuration parsing |

### Database
| Technology | Purpose |
|------------|---------|
| **SQLite** | Development database (zero-config) |
| **PostgreSQL** | Production database (via Docker) |
| **Alembic** | Database migrations |

### Infrastructure
| Technology | Purpose |
|------------|---------|
| **Docker** | Containerization |
| **Docker Compose** | Multi-container orchestration |
| **nginx** | Frontend static file serving (production) |
| **Render.com** | Cloud hosting (PostgreSQL, backend, frontend) |
| **GitHub Actions** | CI/CD pipeline automation |

### External APIs
| Service | Purpose |
|---------|---------|
| **FMP (Financial Modeling Prep)** | Market data: EOD prices, float, quotes |

## Live Demo

The application is deployed and running on Render.com:

| Service | URL |
|---------|-----|
| **Frontend Dashboard** | https://trading-engine-ui.onrender.com |
| **Backend API** | https://trading-engine-api-5iai.onrender.com |
| **API Documentation** | https://trading-engine-api-5iai.onrender.com/docs |
| **Health Check** | https://trading-engine-api-5iai.onrender.com/health |

> **Note:** Free tier services may spin down after inactivity. The first request might take 30-60 seconds while the service wakes up.
>
> **Important:** To use the frontend dashboard, you must first wake up the backend API by visiting the [Backend API URL](https://trading-engine-api-5iai.onrender.com) or [Health Check](https://trading-engine-api-5iai.onrender.com/health). Wait until it responds (up to 60 seconds on free tier), then the frontend will be able to connect and display data.

## Prerequisites

- **Python 3.10+** with [uv](https://docs.astral.sh/uv/) package manager
- **Node.js 18+** with npm
- **Docker** and **Docker Compose** (required for local Postgres)
- **FMP API key** (the free Basic tier is enough for V1)
- **FMP account** (needed from Phase 1 onwards; not required for Phase 0 verification)

## Quick Start

> **v2 status:** the project is migrating to a pre-market universe scanner on FMP data.
> SQLite is no longer supported; the app is Postgres-only, locally and in production.
> See `docs/CLAUDE.md` and `docs/PLAN.md` for the full plan.

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/trading-engine.git
cd trading-engine
```

### 2. Start Postgres (local dev)

```bash
docker compose -f docker-compose.dev.yml up -d
```

This starts Postgres 16 on **host port 5433** (mapped to the container's 5432) so it
does not clash with a native Postgres install that may already own 5432 on your machine.

### 3. Configure environment variables

The backend reads `.env` from the `backend/` directory.

```bash
cp .env.example backend/.env
# then edit backend/.env
```

Minimum for Phase 0:
```env
APP_ENV=development
DEBUG=true
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/trading_engine
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

FMP keys and scanner thresholds are wired in configuration but unused until Phase 1/2.

### 4. Start the backend

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API docs: `http://localhost:8000/docs`
- Health check (DB-probing): `http://localhost:8000/health` → `{"status":"healthy","database_connected":true,...}`

### 5. Start the frontend

In a new terminal:
```bash
cd frontend
npm install
npm run dev
```

Dashboard: `http://localhost:5173`.

### 6. Smoke test (no live market data)

```bash
cd backend
uv run python scripts/seed_test_alerts.py    # sample alerts visible in the dashboard
```

### Production database (Supabase)

Supabase exposes three endpoints per project. The project uses **two URLs**:

| Setting | Endpoint | Host / port | pgBouncer mode |
|---|---|---|---|
| `DATABASE_URL` | Transaction pooler | `aws-<region>.pooler.supabase.com:6543` | transaction |
| `MIGRATION_DATABASE_URL` | Session pooler | `aws-<region>.pooler.supabase.com:5432` | session |
| *(unused)* | Direct | `db.<project>.supabase.co:5432` | none |

Same host, different port. `MIGRATION_DATABASE_URL` is **optional** — when unset,
Alembic falls back to `DATABASE_URL`.

**Why two.** The app runtime issues many short queries, which suits transaction pooling:
pgBouncer hands the server connection back after every transaction. Migrations want the
opposite — DDL, advisory locks and Alembic's version bookkeeping all assume the server
connection stays put for the session, which is what session mode gives you.

**The pgBouncer problem, and where it bit.** In transaction mode two different client
connections can be multiplexed onto the *same* server connection. asyncpg names its
prepared statements with a per-connection counter (`__asyncpg_stmt_1__`, `_2_`, …), so
two clients both starting at 1 collide:

```
asyncpg.exceptions.DuplicatePreparedStatementError:
prepared statement "__asyncpg_stmt_1__" already exists
```

Three settings are needed together, and each fixes a different half:

| Setting | Fixes |
|---|---|
| `statement_cache_size=0` | asyncpg caching a statement that goes stale when pgBouncer reassigns the server connection |
| `prepared_statement_cache_size=0` | the same, one layer up in SQLAlchemy |
| `prepared_statement_name_func` | the **name collision** — UUID names instead of a shared counter |

All three live in [`backend/app/core/db_connect.py`](backend/app/core/db_connect.py) and
are applied to **both** the app engine and Alembic. They used to live only in
`app/core/database.py`; `alembic/env.py` built its own engine via
`async_engine_from_config` and inherited none of them, which is exactly how migrations
failed on Render while the app itself was fine. If you touch this, change it in the one
shared helper — two copies will drift.

All DSNs should be `postgresql+asyncpg://...` — the legacy `postgres://` prefix from
Supabase's copy-paste UI is normalized automatically.

### Migration strategy

`alembic upgrade head` runs from the web service's `startCommand`, so it executes on
every container start. That is a deliberate trade-off:

**Why it is currently acceptable**
- The service runs a single free-tier instance, so there is no concurrent-start race today.
- Migrations take a Postgres advisory lock (`pg_advisory_xact_lock`, see
  `backend/alembic/env.py`), so if two instances ever do start together they serialize:
  the second waits, then finds nothing to apply.
- It keeps deploys to one step, which matters when the alternative is remembering to run
  a manual command.

**What it costs**
- App boot is coupled to DDL. A bad migration means the service does not start at all,
  rather than a failed deploy step leaving the previous version serving.
- Every cold start pays the migration check — small, but on the free tier cold starts are
  frequent.
- It does not scale. The advisory lock prevents corruption, not the delay: with N
  instances, N−1 wait on the lock before booting.

**Move it out when any of these become true:** the web service scales past one instance,
migrations grow long enough that boot latency matters, or you want a failed migration to
stop a deploy rather than a running service. Render's pre-deploy command is the
destination (it requires a paid instance type — verify availability for your plan):

```yaml
preDeployCommand: cd backend && alembic upgrade head
startCommand: cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Until then, run migrations manually against the session pooler if you prefer:

```bash
cd backend
MIGRATION_DATABASE_URL="postgresql+asyncpg://...pooler.supabase.com:5432/postgres" \
  uv run alembic upgrade head
```

### Rolling back

**Take a backup first.** `alembic downgrade` from the v2 alert contract preserves every
row, but it is not lossless — and re-upgrading does not bring the lost values back.

**What is preserved.** No rows are deleted. Scanner alerts are converted into valid v1
rows: `entry_price` is backfilled from `entry_reference_price` (the same quantity under
two names), and `setup_type` is set to `gap_up` for scanner-origin rows — accurate,
because every v2 candidate cleared Stage 2's `3.0 <= gap_pct <= 15.0` requirement.

**What is destroyed, irreversibly.** The v2 columns are dropped, taking their contents
with them: `gap_pct`, `rvol_pct`, `rvol_mode`, `rvol_is_approximate`, `catalyst`,
`entry_reference_price`, `nearest_resistance`, `resistance_source`, `upside_pct`,
`suggested_entry_window`, `scan_timestamp`, `is_final_pass`, `score_breakdown_json`,
`session_date`, `profile` and `scan_run_id` — plus the entire `scanner_settings` table
(your threshold overrides). Upgrading again restores the *columns*, empty. Every
confidence score and its breakdown is gone.

**When it refuses.** If a row has no `entry_price`, no `entry_reference_price` and no
`session_date`, it cannot be expressed in v1 and the downgrade aborts with the offending
row IDs rather than guessing. Nothing is changed — the migration transaction rolls back.
Give those rows values or delete them, then re-run.

Going further back (`downgrade base`) drops the tables outright, so all data goes with
them. The full reasoning lives in the downgrade docstring of
`backend/alembic/versions/0ca0181ab014_*.py`, and the behaviour is pinned by
`backend/tests/integration/test_migration_round_trip.py`.

take a pg_dump before running any downgrade

## Docker Deployment

### Development (Database Only)

Run just the PostgreSQL database in Docker while developing locally:

```bash
docker-compose -f docker-compose.dev.yml up -d
```

Then update your `.env`:
```env
DATABASE_URL=postgresql+asyncpg://trading:trading@localhost:5432/trading_engine
```

### Production (Full Stack)

Deploy the complete application stack:

```bash
# Configure environment
cp .env.example .env
# Edit .env and add your FMP API key:
# - FMP_API_KEY

# Build and start all services (migrations run automatically)
docker-compose up -d --build
```

**Important Notes:**
- Migrations run automatically when the backend container starts
- The `DATABASE_URL` in your `.env` file is **ignored** when using Docker
- Docker uses the database URL defined in `docker-compose.yml` (which points to the `db` service)

Services:
- Frontend: `http://localhost:80`
- Backend API: `http://localhost:8000`
- PostgreSQL: `localhost:5432`

**If the backend container keeps restarting:**
```bash
# Check logs for errors
docker logs trading-engine-backend

# Force clean rebuild
docker-compose down -v
docker-compose up -d --build
```

## Cloud Deployment

### Deploy to Render.com

This project includes a `render.yaml` blueprint for one-click deployment to Render.

#### Option 1: Deploy via Render Dashboard

1. Fork this repository to your GitHub account

2. Go to [Render Dashboard](https://dashboard.render.com) and sign in

3. Click **New** → **Blueprint**

4. Connect your GitHub repository

5. Render will detect `render.yaml` and create:
   - PostgreSQL database (free tier)
   - Backend API service
   - Frontend static site

6. **Configure secrets** in the Render dashboard:
   - Go to your `trading-engine-api` service → Environment
   - Add `FMP_API_KEY`

#### Option 2: Manual Deployment

1. Create a PostgreSQL database on Render

2. Create a Web Service for the backend:
   - **Build Command:** `cd backend && pip install -e .`
   - **Start Command:** `cd backend && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Environment Variables:**
     - `PYTHON_VERSION`: `3.10.12`
     - `DATABASE_URL`: (from your database)
     - `FMP_API_KEY`: (your key)
     - `CORS_ORIGINS`: `["https://your-frontend-url.onrender.com"]`

3. Create a Static Site for the frontend:
   - **Build Command:** `cd frontend && npm ci && npm run build`
   - **Publish Directory:** `frontend/dist`
   - **Environment Variables:**
     - `VITE_API_URL`: `https://your-backend-url.onrender.com`
     - `VITE_WS_URL`: `wss://your-backend-url.onrender.com`

## CI/CD Pipeline

This project uses GitHub Actions for continuous integration and deployment.

### Workflow Overview

The CI/CD pipeline (`.github/workflows/ci-cd.yml`) runs on every push and pull request to `main`:

```
Push/PR to main
      │
      ├──→ Backend Tests (parallel)
      │         ├── Lint with ruff
      │         └── Run pytest (203 tests)
      │
      └──→ Frontend Tests (parallel)
                ├── Lint with ESLint
                ├── Run vitest (60 tests)
                └── Build verification
      │
      ▼
   All tests pass?
      │
      ├── No  → Pipeline fails, PR blocked
      │
      └── Yes → Deploy to Render (main branch only)
                  ├── Trigger backend deploy hook
                  └── Trigger frontend deploy hook
```

### Setting Up CI/CD

1. **GitHub Secrets Required:**

   Go to your repository → Settings → Secrets and variables → Actions → New repository secret:

   | Secret | Description |
   |--------|-------------|
   | `RENDER_BACKEND_DEPLOY_HOOK` | Deploy hook URL from Render backend service |
   | `RENDER_FRONTEND_DEPLOY_HOOK` | Deploy hook URL from Render frontend service |

2. **Get Render Deploy Hooks:**
   - Go to your Render service → Settings → Build & Deploy
   - Copy the "Deploy Hook" URL

3. **Pipeline Features:**
   - Runs on Ubuntu with Python 3.10 and Node.js 20
   - Uses `uv` for fast Python dependency management
   - 30-second timeout per test to prevent hanging
   - Automatic deployment only on successful tests

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

# Run with coverage report
uv run pytest --cov=app --cov-report=term-missing

# Run a specific test file
uv run pytest tests/unit/test_rule_engine.py -v
```

**Test Coverage:**
- Backend tests: see `uv run pytest` for the current count

### Frontend Tests

```bash
cd frontend

# Run all tests
npm test

# Run tests in watch mode
npm test -- --watch

# Run with coverage report
npm run test:coverage
```

**Test Coverage:**
- Component tests: 7 tests
- Hook tests: 12 tests
- Service tests: 18 tests
- Store tests: 23 tests
- Total: 60 frontend tests

## Usage and Demonstration

### Testing Without Live Market Data

You can test the complete system without live market data or waiting for market hours. There are two methods:

#### Method 1: Seed Sample Alerts (Quick Dashboard Demo)

Populate the database with sample alerts to test the dashboard UI:

```bash
# If running locally
cd backend
uv run python scripts/seed_test_alerts.py

# If running with Docker
docker exec -it trading-engine-backend uv run python scripts/seed_test_alerts.py
```

This creates 20 sample alerts with random symbols, prices, and setup types. Refresh the frontend to see them.

#### Method 2: Simulate Market Data (Test Rule Evaluation)

Test the full alert generation pipeline by simulating market data:

**Step 1: Create a Rule**

Go to the **Rules** page in the frontend and click **"+ Create Rule"**:
- **Name**: `Price Above 100`
- **Conditions**: `price > 100`
- **Active**: ✓ Enabled

Or via API:
```bash
curl -X POST "http://localhost:8000/api/v1/rules" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Price Above 100",
    "description": "Alert when price exceeds 100",
    "rule_type": "price",
    "config_yaml": "{\"conditions\":[{\"field\":\"price\",\"operator\":\">\",\"value\":100}]}",
    "is_active": true,
    "priority": 10
  }'
```

**Step 2: Simulate Market Data**

Use the simulation endpoint to trigger the rule:

```bash
curl -X POST "http://localhost:8000/api/v1/market-data/simulate" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL", "price": 150.0, "volume": 1000000}'
```

Or use the Swagger UI at `http://localhost:8000/docs`:
1. Find `POST /api/v1/market-data/simulate`
2. Click "Try it out"
3. Enter: `{"symbol": "AAPL", "price": 150.0}`
4. Click "Execute"

**Expected Response:**
```json
{
  "symbol": "AAPL",
  "price": 150.0,
  "rules_evaluated": 1,
  "alerts_triggered": 1,
  "alerts": [
    {
      "id": 1,
      "symbol": "AAPL",
      "setup_type": "breakout",
      "entry_price": 150.0,
      "rule_id": 1
    }
  ],
  "message": "Simulated AAPL @ $150.00 - 1 alert(s) triggered"
}
```

The alert will:
- Be saved to the database
- Be broadcast via WebSocket to connected clients
- Appear on the **Alerts** page in the frontend

**Step 3: Test Non-Triggering Data**

Simulate data that doesn't match the rule:
```bash
curl -X POST "http://localhost:8000/api/v1/market-data/simulate" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL", "price": 50.0}'
```

This returns `alerts_triggered: 0` because 50 < 100.

### End-to-End Testing with Live Data

To test with real market data:

1. **Configure your FMP API key** in your `.env` file

2. **Start the backend and frontend** (see Quick Start above)

3. **Build the universe and reference data**:
   ```bash
   cd backend
   uv run python scripts/probe_fmp_symbols.py       # discover accessible symbols
   uv run python scripts/refresh_reference_data.py  # 2 API calls per ticker
   ```

4. **Run a scan** — `uv run python scripts/run_scan.py --fixture --profile demo`

5. **Monitor the Candidates page** for the session's alerts, pushed live over WebSocket

**Note:** the scanner runs pre-market (04:00-09:25 ET). Outside that window it records a
`skipped` run and does no work.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check (reports DB connectivity) |
| GET | `/api/v1/scanner/alerts` | Session candidates, highest confidence first |
| GET | `/api/v1/scanner/alerts/{id}` | One candidate with its score breakdown |
| POST | `/api/v1/scanner/alerts/{id}/read` | Mark a candidate read |
| GET | `/api/v1/scanner/status` | Scanner health — distinguishes quiet market from outage |
| GET | `/api/v1/scanner/scan-runs` | Recent scan runs with per-stage funnel counts |
| GET | `/api/v1/scanner/settings` | Effective thresholds (env defaults + stored overrides) |
| PUT | `/api/v1/scanner/settings` | Update thresholds; applies on the next scan |
| DELETE | `/api/v1/scanner/settings` | Reset thresholds to environment defaults |
| WS | `/api/v1/ws` | WebSocket; subscribe to the `alerts` channel |

Full API documentation available at `/docs` when the server is running.

## Project Structure

```
trading-engine/
├── backend/
│   ├── app/
│   │   ├── api/v1/           # API endpoints
│   │   ├── core/             # Database setup
│   │   ├── engine/           # Rule evaluation engine
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic schemas
│   │   ├── services/         # FMP client, scanner, alerts
│   │   ├── config.py         # Settings
│   │   └── main.py           # FastAPI app
│   ├── alembic/              # Database migrations
│   ├── rules/                # Default rule configurations
│   ├── tests/                # pytest tests (unit + integration)
│   └── pyproject.toml        # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── components/       # React components
│   │   ├── hooks/            # Custom hooks (WebSocket)
│   │   ├── pages/            # Page components
│   │   ├── services/         # API client
│   │   ├── store/            # Zustand state
│   │   └── test/             # Vitest tests
│   └── package.json          # Node dependencies
├── .github/
│   └── workflows/
│       └── ci-cd.yml         # GitHub Actions CI/CD pipeline
├── openapi/
│   └── spec.yaml             # OpenAPI specification
├── docs/
├── docker-compose.yml        # Production Docker config
├── docker-compose.dev.yml    # Development Docker config
├── render.yaml               # Render.com deployment blueprint
└── .env.example              # Environment template
```

## Configuration

### Trading Rules

Rules are defined in YAML format with the following structure:

```yaml
name: "Rule Name"
description: "What this rule detects"
type: "price|volume|gap|technical"
enabled: true
priority: 10  # Higher = evaluated first

conditions:
  - field: price          # Market data field
    operator: ">"         # >, >=, <, <=, ==, !=
    value: 100            # Threshold value

filters:
  min_price: 5.0          # Minimum stock price
  max_price: 500.0        # Maximum stock price
  min_volume: 100000      # Minimum daily volume

targets:
  stop_loss_percent: -3.0       # Stop loss as % below entry
  stop_loss_atr_multiplier: 2.0 # Or use ATR-based stop
  target_percent: 6.0           # Target as % above entry
  target_rr_ratio: 2.0          # Or use risk/reward ratio

confidence:
  base_score: 0.7         # Base confidence (0.0 - 1.0)
  modifiers:              # Adjust based on conditions
    - condition: "volume_ratio > 3.0"
      adjustment: 0.1     # Add 10% confidence
```

## Troubleshooting

### Common Issues

**Backend won't start:**
- Ensure Python 3.10+ is installed: `python --version`
- Ensure uv is installed: `uv --version`
- Check that all environment variables are set in `.env`

**Database errors:**
- Run migrations: `uv run alembic upgrade head`
- For fresh start: Delete `trading_engine.db` and re-run migrations

**Frontend can't connect to backend:**
- Verify backend is running on port 8000
- Check `VITE_API_URL` in frontend `.env`
- Ensure CORS is configured in backend `.env`

**No market data:**
- Verify the FMP API key is correct
- Check if market is open (US market hours)
- Check today's API budget: `uv run python scripts/fmp_budget.py`

**WebSocket disconnects:**
- Check browser console for errors
- Verify `VITE_WS_URL` matches backend address

## License

MIT License - see [LICENSE](LICENSE) for details.
