# Trading Engine

A real-time trading alert system that monitors stocks via the Alpaca Markets API and generates actionable trading alerts based on configurable rules.

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

- **Monitor markets in real-time** across a customizable watchlist of stocks
- **Evaluate configurable trading rules** against live market data
- **Generate instant alerts** when trading setups are detected
- **Provide actionable information** including entry prices, stop losses, and profit targets

## What This System Does

The Trading Engine solves these problems by providing:

1. **Real-Time Market Monitoring**: Connects to Alpaca Markets API to stream live quotes and trades for stocks on your watchlist.

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
   - Managing your stock watchlist
   - Monitoring system status and statistics

5. **WebSocket Updates**: Live push notifications ensure you see new alerts immediately without refreshing.

## System Architecture

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
│  │  │ Alerts   │  │  Rules   │  │Watchlist │  │   WebSocket      │ │   │
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
│  │                    Alpaca Integration                             │   │
│  │  ┌────────────────────┐  ┌────────────────────┐                  │   │
│  │  │   Alpaca Client    │  │   Stream Manager   │                  │   │
│  │  │   (REST API)       │  │   (WebSocket)      │                  │   │
│  │  └────────────────────┘  └────────────────────┘                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           External Services                              │
│  ┌─────────────────────────────┐  ┌─────────────────────────────────┐  │
│  │      SQLite / PostgreSQL    │  │      Alpaca Markets API         │  │
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
| **Alpaca Markets** | Real-time market data and paper trading |

## Live Demo

The application is deployed and running on Render.com:

| Service | URL |
|---------|-----|
| **Frontend Dashboard** | https://trading-engine-ui.onrender.com |
| **Backend API** | https://trading-engine-api-5iai.onrender.com |
| **API Documentation** | https://trading-engine-api-5iai.onrender.com/docs |
| **Health Check** | https://trading-engine-api-5iai.onrender.com/health |

> **Note:** Free tier services may spin down after inactivity. The first request might take 30-60 seconds while the service wakes up.

## Prerequisites

- **Python 3.10+** with [uv](https://docs.astral.sh/uv/) package manager
- **Node.js 18+** with npm
- **Docker** and **Docker Compose** (optional, for containerized deployment)
- **Alpaca Markets account** (free) for API keys

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/trading-engine.git
cd trading-engine
```

### 2. Configure Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your Alpaca API credentials
# Get your keys from: https://app.alpaca.markets/paper/dashboard/overview
```

Required environment variables:
```env
# Backend
APP_ENV=development
DEBUG=true
DATABASE_URL=sqlite+aiosqlite:///./trading_engine.db
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
CORS_ORIGINS=http://localhost:5173

# Frontend
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

### 3. Start the Backend

```bash
cd backend

# Install dependencies
uv sync

# Run database migrations
uv run alembic upgrade head

# Start the development server
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`
- API Documentation: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/health`

### 4. Start the Frontend

In a new terminal:
```bash
cd frontend

# Install dependencies
npm install

# Start the development server
npm run dev
```

The dashboard will be available at `http://localhost:5173`

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
# Edit .env and add your Alpaca API credentials:
# - ALPACA_API_KEY
# - ALPACA_SECRET_KEY

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
   - Add `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`

#### Option 2: Manual Deployment

1. Create a PostgreSQL database on Render

2. Create a Web Service for the backend:
   - **Build Command:** `cd backend && pip install -e .`
   - **Start Command:** `cd backend && alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Environment Variables:**
     - `PYTHON_VERSION`: `3.10.12`
     - `DATABASE_URL`: (from your database)
     - `ALPACA_API_KEY`: (your key)
     - `ALPACA_SECRET_KEY`: (your secret)
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
- Unit tests: 155 tests (rule engine, API endpoints, alert generator)
- Integration tests: 48 tests (WebSocket, cross-component workflows, alert generation)
- Total: 203 backend tests

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

You can test the complete system without Alpaca API credentials or waiting for market hours. There are two methods:

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

1. **Configure Alpaca API credentials** in your `.env` file

2. **Start the backend and frontend** (see Quick Start above)

3. **Add symbols to your watchlist** via the Settings page

4. **Create trading rules** via the Rules page

5. **Monitor the Dashboard** for real-time alerts when market conditions match your rules

**Note:** Live data only streams during US market hours (9:30 AM - 4:00 PM ET)

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/v1/alerts` | List alerts (paginated, filterable) |
| GET | `/api/v1/alerts/{id}` | Get alert details |
| PATCH | `/api/v1/alerts/{id}` | Update alert (mark as read) |
| GET | `/api/v1/alerts/stats` | Alert statistics |
| GET | `/api/v1/rules` | List all rules |
| GET | `/api/v1/rules/{id}` | Get rule details |
| POST | `/api/v1/rules` | Create new rule |
| PUT | `/api/v1/rules/{id}` | Update rule |
| DELETE | `/api/v1/rules/{id}` | Delete rule |
| POST | `/api/v1/rules/{id}/toggle` | Enable/disable rule |
| GET | `/api/v1/watchlist` | Get watchlist |
| POST | `/api/v1/watchlist` | Add symbol to watchlist |
| DELETE | `/api/v1/watchlist/{symbol}` | Remove from watchlist |
| GET | `/api/v1/market-data/{symbol}` | Get market data for symbol |
| WS | `/api/v1/ws` | WebSocket for real-time updates |

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
│   │   ├── services/         # Alpaca integration
│   │   ├── config.py         # Settings
│   │   └── main.py           # FastAPI app
│   ├── alembic/              # Database migrations
│   ├── rules/                # Default rule configurations
│   ├── tests/                # pytest tests
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
- Verify Alpaca API keys are correct
- Check if market is open (US market hours)
- Use paper trading URL: `https://paper-api.alpaca.markets`

**WebSocket disconnects:**
- Check browser console for errors
- Verify `VITE_WS_URL` matches backend address

## License

MIT License - see [LICENSE](LICENSE) for details.
