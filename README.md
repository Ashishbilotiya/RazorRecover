# RazorRecover

AI-powered Revenue Recovery agent for the Razorpay Buildathon 2026 — Track 03.

> Detects recoverable revenue loss, identifies the root cause, selects a safe recovery strategy, executes the approved action through Razorpay Test Mode, and measures the actual revenue recovered.

See [CLAUDE.md](./CLAUDE.md) for the full development specification.

---

## Architecture (one-liner)

```
Razorpay Webhooks
        ↓
   FastAPI ingestion  →  PostgreSQL (transaction, customer, case, audit)
        ↓
   ML risk model  +  AI agent pipeline (risk · root cause · recovery)
        ↓
   Policy engine  →  Deterministic safeguards  →  Recovery executor
        ↓
   Razorpay Test Mode  +  Audit log  +  Analytics
```

The LLM **never** calls Razorpay, and neither does the API. The chain is:

```
Agent recommendation  →  Policy  →  Safeguards  →  Executor  →  Razorpay
```

The frontend reads from the FastAPI surface only — it never talks to Razorpay directly.

## Tech stack

* **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, PostgreSQL
* **ML:** pandas, NumPy, scikit-learn, joblib
* **AI agents:** structured Pydantic outputs, deterministic fallback rules
* **Frontend:** React 18, Vite 5, TypeScript 5, Tailwind 3
* **Integration:** Razorpay Test Mode APIs + Webhooks

## Repo layout

```
backend/      FastAPI app: agents, recovery engine, ML, integrations, API, audit
frontend/     React + Vite + Tailwind dashboard
data/         Synthetic transactions + generator
models/       Trained ML model artefact
scripts/      Seed + demo helpers
tests/        pytest + FastAPI TestClient
docs/         architecture, demo flow, evaluation
```

## Setup

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r ../requirements.txt

# Configure environment (edit .env after copying)
cp ../.env.example ../.env

# Apply schema + run
uvicorn backend.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

The Vite dev server proxies `/api/*` to `http://localhost:8000` by default.
Override the backend URL with `VITE_API_BASE` (see `frontend/.env.example`).

### 3. For a production-style build

```bash
cd frontend
npm run build    # produces dist/
npm run preview  # serves dist/ on http://localhost:4173
```

## Environment variables

See `.env.example` at the repo root. Never commit a real `.env`.

Key variables:

* `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` — Razorpay Test Mode
* `DATABASE_URL` — defaults to local SQLite for tests; PostgreSQL in production
* `LLM_API_KEY` (optional) — without it, all three agents fall back to deterministic rules
* `FRONTEND_VITE_API_BASE` (optional) — only for non-default backend URLs

## API surface

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/health` | Liveness check |
| `POST` | `/api/webhooks/razorpay` | Webhook ingestion (signature-verified, idempotent) |
| `GET`  | `/api/transactions` | List transactions (filter by status) |
| `GET`  | `/api/recovery/cases` | List recovery cases (filter by status, action) |
| `GET`  | `/api/recovery/cases/{id}` | One recovery case (transaction + actions) |
| `POST` | `/api/recovery/cases/{id}/approve` | Human approval (state machine) |
| `POST` | `/api/recovery/cases/{id}/execute` | Execute approved action |
| `GET`  | `/api/audit/{case_id}` | Full audit timeline for a case |
| `GET`  | `/api/analytics/overview` | Business + ML aggregate metrics |

## Testing

```bash
cd backend
python -m pytest tests/ -q
```

The frontend has no test runner by design (hackathon scope). The build
(`npm run build`) is the primary verification step — it runs both Vite and
TypeScript in strict mode.

## Demo flow

See `docs/demo-flow.md`. The 5–7 minute narrative is:

1. Merchant has revenue leakage.
2. RazorRecover receives a `payment.failed` webhook.
3. ML predicts recoverability.
4. AI agent pipeline picks a recovery strategy.
5. Policy + safeguards validate.
6. Executor calls Razorpay Test Mode.
7. Outcome is recorded and the dashboard updates.

The dashboard is the demo — judges see revenue at risk → targeted → recovered → recovery rate on a single page.

## Safety invariants

* The LLM **never** calls Razorpay (CLAUDE.md §21).
* The API **never** calls Razorpay — only `recovery/engine.py` does, via the executor (CLAUDE.md §21, §25).
* Every financial action is gated by policy + safeguards + idempotency.
* Every decision produces an audit row.
* Webhooks are HMAC-verified before persistence; replays return `outcome="duplicate"`.

## License

Built for the Razorpay Buildathon 2026.
