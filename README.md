# ChatToSales

A production-grade **conversational commerce backend** built with FastAPI.  
Businesses connect any messaging channel (WhatsApp, SMS, Web chat) and ChatToSales handles inbound message ingestion, conversation management, order creation, payments, and notifications — all event-driven through a Redis pub/sub bus.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Clients (WhatsApp / SMS / Web)                                 │
└─────────────────────────┬───────────────────────────────────────┘
                          │  POST /api/v1/webhooks/webhook
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI App (modular monolith)                                 │
│                                                                 │
│  ingestion ──► Redis Event Bus ──► conversation                 │
│                (pub/sub)          orders                        │
│                                   payments                      │
│                                   notifications                 │
│                                                                 │
│  AMQP (RabbitMQ) for durable domain events                     │
└───────────┬──────────────────┬──────────────────────────────────┘
            │                  │
            ▼                  ▼
       PostgreSQL           Redis
       (persistent)         (cache + event bus)
```

**Key design choices:**

| Choice                   | Detail                                                                |
| ------------------------ | --------------------------------------------------------------------- |
| Multi-tenancy            | Every model carries a `tenant_id` via `TenantModel`                   |
| Async throughout         | `asyncpg` driver, `AsyncSession`, `aioredis`                          |
| Typed config             | `pydantic-settings` with `PostgresDsn`/`RedisDsn`                     |
| Zero-downtime migrations | Alembic async, `compare_type=True`                                    |
| Event bus                | Redis pub/sub; channel: `chattosales.events.<tenant_id>.<event_name>` |

---

## Tech Stack

- **Python 3.11** / **FastAPI 0.115**
- **PostgreSQL 16** + SQLAlchemy 2.0 async + Alembic
- **Redis 7** — shared cache pool + event bus
- **RabbitMQ 3.13** — durable AMQP domain events
- **Docker** — multi-stage build, non-root user, healthchecks

---

## Quick Start (Docker)

### Prerequisites

- Docker ≥ 24 and Docker Compose plugin

### 1 — Configure environment

```bash
cp .env.docker .env.docker.local   # optional: keep local overrides outside git
```

Edit `.env.docker` (or `.env.docker.local`) and set at minimum:

```
SECRET_KEY=<strong-random-string>
WHATSAPP_VERIFY_TOKEN=<your-verify-token>
WHATSAPP_ACCESS_TOKEN=<your-access-token>
```

### 2 — Build and start all services

```bash
docker compose up --build
```

This starts: **app** (port 8000), **postgres** (5432), **redis** (6379), **rabbitmq** (5672 + management UI 15672).

### 3 — Run database migrations

In a separate terminal while the stack is running:

```bash
docker compose exec app alembic upgrade head
```

### 4 — Verify

```bash
curl http://localhost:8000/health
# → {"status":"ok","environment":"development","version":"0.1.0"}
```

API docs:

| Interface   | URL                                    |
| ----------- | -------------------------------------- |
| Swagger UI  | http://localhost:8000/docs             |
| ReDoc       | http://localhost:8000/redoc            |
| RabbitMQ UI | http://localhost:15672 (guest / guest) |

---

## Local Development (without Docker)

### Prerequisites

- Python 3.11+
- PostgreSQL 16 running locally
- Redis 7 running locally
- RabbitMQ 3.x running locally (optional — app degrades gracefully)

### Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with local connection strings
```

### Start

```bash
uvicorn app.main:app --reload --port 8000
```

### Migrate

```bash
alembic upgrade head
```

---

## Running Tests

See [docs/testing.md](docs/testing.md) for the full testing guide.

```bash
pytest -v
```

---

## API Reference

All endpoints are prefixed with `/api/v1`.

| Method | Path                        | Description                         |
| ------ | --------------------------- | ----------------------------------- |
| `GET`  | `/health`                   | Health check                        |
| `POST` | `/api/v1/webhooks/webhook`  | Ingest message from any channel     |
| `GET`  | `/api/v1/webhooks/whatsapp` | Meta webhook verification challenge |
| `POST` | `/api/v1/webhooks/whatsapp` | Receive Meta Cloud API messages     |

---

## Project Structure

```
chatToSales/
├── app/
│   ├── core/
│   │   ├── config.py          # pydantic-settings singleton
│   │   ├── dependencies.py    # FastAPI Annotated deps
│   │   ├── exceptions.py      # typed exception hierarchy
│   │   ├── logging.py
│   │   └── models/
│   │       ├── base.py        # BaseModel, TenantMixin, TenantModel
│   │       └── customer.py    # example tenant-scoped model
│   ├── infra/
│   │   ├── database.py        # async engine, session factory
│   │   ├── cache.py           # Redis pool lifecycle
│   │   ├── messaging.py       # AMQP domain events
│   │   └── event_bus.py       # Redis pub/sub event bus
│   ├── modules/
│   │   ├── ingestion/         # webhook ingestion + normalization
│   │   ├── conversation/
│   │   ├── orders/
│   │   ├── payments/
│   │   └── notifications/
│   └── main.py                # app factory + lifespan
├── alembic/                   # async migrations
├── tests/
├── docs/
│   └── testing.md
├── Dockerfile
├── docker-compose.yml
└── .env.docker
```

---

## Environment Variables

| Variable       | Required  | Default       | Description                              |
| -------------- | --------- | ------------- | ---------------------------------------- |
| `DATABASE_URL` | ✅        | —             | `postgresql+asyncpg://...`               |
| `REDIS_URL`    | ✅        | —             | `redis://...`                            |
| `SECRET_KEY`   | ✅ (prod) | dev default   | App secret; production enforced          |
| `ENVIRONMENT`  | ❌        | `development` | `dev` / `stg` / `prod`                   |
| `DEBUG`        | ❌        | `false`       | Enable debug mode; blocked in production |
| `BROKER_URL`   | ❌        | —             | `amqp://...` RabbitMQ URL                |
| `WHATSAPP_*`   | ❌        | —             | Meta Cloud API credentials               |

See `.env.example` for the complete list.
