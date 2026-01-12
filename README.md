# Uzbek Receipt Parser

High-load financial transaction parsing system for Uzbek banking receipts (Uzcard/Humo).

## Architecture Overview

This system combines deterministic text processing with AI-powered parsing to transform unstructured receipt data into structured analytics. It monitors Telegram chats automatically and provides a strict business-style React interface for data visualization.

### Key Components

1. **Data Ingestion Layer**
   - Telegram Bot (Aiogram) - Manual receipt input
   - MTProto Userbot (Telethon) - Auto-monitoring of target chats
   - Redis queue for async processing

2. **Parsing Engine**
   - Regex parser (3 receipt formats: Humo, SMS, Semicolon)
   - GPT-4o fallback with Structured Outputs
   - Operator-to-Application mapping (100+ rules)

3. **Backend API**
   - FastAPI with PostgreSQL
   - Transaction CRUD with pagination/filtering
   - Analytics endpoints ("Top Agent")

4. **Frontend**
   - React + Vite + TypeScript
   - TanStack Table (strict design)
   - Real-time updates with TanStack Query

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Telegram API credentials (API_ID, API_HASH, BOT_TOKEN)
- OpenAI API key

### Setup

1. **Clone and configure environment**

```bash
cp .env.example .env
# Edit .env with your credentials
```

2. **Start services with Docker Compose**

```bash
docker-compose up -d
```

3. **Initialize database and seed operators**

```bash
docker-compose exec backend python -m database.seed_operators
```

4. **Initialize Userbot session** (first time only)

```bash
docker-compose exec userbot python -m ingestion.telegram_userbot
# Follow prompts to authenticate with your phone number
```

### Access

- **Frontend**: http://localhost:5173
- **API Docs**: http://localhost:8000/docs
- **Database**: localhost:5432

## Development

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn api.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

#### Table Virtualization (Performance)
- The transactions grid uses `@tanstack/react-virtual` inside `TransactionTable.tsx` to only render visible rows while keeping the header sticky and all table interactions (sorting, filtering, inline edit, drag-to-select) intact.
- Row height is estimated per density (`compact`, `standard`, `comfortable`); adjust `ROW_HEIGHT_BY_DENSITY` for custom sizing if row heights change.
- Overscan is set to `10` rows; tune `overscan` in the `useVirtualizer` config for smoother scroll on slow machines (higher = fewer reflows, lower = less work per scroll).
- A dev-only guard logs a warning if a large dataset (>2000 rows) ever renders without virtualization.

### Telegram Web K (bots-only)

The Userbot tab embeds a local build of Telegram Web K from `telegram-web-k/`.

Build and copy steps:
```bash
cd telegram-web-k
pnpm install
node build
```

Then copy the build output into the frontend public folder:
```bash
# from repo root
rm -rf frontend/public/tweb
mkdir -p frontend/public/tweb
cp -r telegram-web-k/public/* frontend/public/tweb/
```

Rebuild the frontend after copying.

## Configuration

### Target Chat IDs

Edit `.env` to configure which Telegram chats to monitor:

```
TARGET_CHAT_IDS=915326936,856264490,7028509569
```

### Hourly Reports

Reports are sent to the Telegram channel specified in `REPORT_CHANNEL_ID`.

## System Features

- ✅ Dual ingestion: Manual (bot) + Automatic (userbot)
- ✅ Hybrid parsing: Regex (95% confidence) + GPT fallback
- ✅ Operator normalization: 100+ mapping rules
- ✅ Strict table UI: Data-dense design with TanStack Table
- ✅ Real-time analytics: Top Agent widget, hourly reports
- ✅ Production-ready: Docker, error handling, logging

## Technology Stack

**Backend:** Python, FastAPI, Aiogram, Telethon, SQLAlchemy, Celery, Redis, OpenAI  
**Frontend:** React, TypeScript, Vite, TanStack Table, TanStack Query, Tailwind CSS  
**Database:** PostgreSQL  
**Infrastructure:** Docker, Nginx

## License

Proprietary - All rights reserved
