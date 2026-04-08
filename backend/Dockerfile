# ── Stage 1: dependency layer ─────────────────────────────────────────────────
FROM python:3.11-slim AS deps

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from the deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy all backend source files
COPY . .

# Expose all service ports
EXPOSE 5001 8000 6001 7000 9000 9001

# Default: run the FastAPI monolith on port 8080 (Vercel-compatible entry-point).
# Override CMD (or use docker-compose) to run individual microservices.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
