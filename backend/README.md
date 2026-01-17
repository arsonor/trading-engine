# Trading Engine Backend

FastAPI backend for the Trading Engine - a real-time trading alert system.

## Features

- REST API for alerts, rules, and watchlist management
- WebSocket for real-time alert notifications
- Rule engine for evaluating trading conditions
- Alpaca Markets API integration for market data
- MCP (Model Context Protocol) server for AI assistant integration

## Quick Start

```bash
# Install dependencies
uv sync

# Run migrations
uv run alembic upgrade head

# Start development server
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Documentation

- API Docs: http://localhost:8000/docs
- Full documentation: See [main README](../README.md)
