#!/bin/bash
set -e

echo "Waiting for database to be ready..."
# Simple wait for database (asyncpg doesn't have a CLI, so we just wait)
sleep 2

echo "Running database migrations..."
uv run alembic upgrade head

echo "Starting application..."
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
