# Backend Dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install uv and bash
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml .
COPY uv.lock* .

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY app/ app/
COPY rules/ rules/
COPY alembic/ alembic/
COPY alembic.ini .
COPY start.sh .

# Make startup script executable
RUN chmod +x start.sh

# Expose port
EXPOSE 8000

# Run the startup script (runs migrations then starts app)
CMD ["./start.sh"]
