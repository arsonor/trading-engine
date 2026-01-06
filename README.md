# Trading Engine

A real-time trading alert system that monitors stocks via the Alpaca Markets API and generates actionable trading alerts based on configurable rules.

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

### External APIs
| Service | Purpose |
|---------|---------|
| **Alpaca Markets** | Real-time market data and paper trading |

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
# Edit .env with production values

# Build and start all services
docker-compose up -d

# Run database migrations
docker-compose exec backend uv run alembic upgrade head
```

Services:
- Frontend: `http://localhost:80`
- Backend API: `http://localhost:8000`
- PostgreSQL: `localhost:5432`

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
- Unit tests: 118 tests (rule engine, API endpoints)
- Integration tests: 38 tests (WebSocket, cross-component workflows)
- Total: 156 backend tests, ~55% code coverage

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

### End-to-End Testing

To verify the complete system:

1. **Start the backend and frontend** (see Quick Start above)

2. **Create a trading rule** via the Rules page:
   ```yaml
   name: Volume Spike Alert
   conditions:
     - field: volume_ratio
       operator: ">="
       value: 2.0
   filters:
     min_price: 10.0
     min_volume: 100000
   targets:
     stop_loss_percent: -3.0
     target_rr_ratio: 2.0
   confidence:
     base_score: 0.75
   ```

3. **Add symbols to your watchlist** via the Settings page

4. **Monitor the Dashboard** for real-time alerts when market conditions match your rules

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
├── openapi/
│   └── spec.yaml             # OpenAPI specification
├── docker-compose.yml        # Production Docker config
├── docker-compose.dev.yml    # Development Docker config
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
