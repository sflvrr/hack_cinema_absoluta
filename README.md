# techbold · AI Service Desk Autopilot — Track Template

Starter **skeleton** for the techbold START Hack track. You build an AI-assisted
technician workspace that:

1. reads assigned tickets from the **Phoenix ERP** mock,
2. loads the affected **customer system** (SSH connection details),
3. connects to the Linux VM over **SSH** and, **under the technician's control**,
   diagnoses and safely fixes the incident,
4. **validates** the fix, and
5. writes a clean **activity** (documentation) back to the ERP.

> A human must confirm every action the AI takes on a system. The agent never acts on
> its own. How you orchestrate it (one planning agent with tools, or several specialised
> agents) is up to you — the case scores **outcomes**, not your framework.

This repo gives you the structure and the Docker setup. **The implementation is yours.**

---

## 1. What's in here

```
backend/        FastAPI skeleton (just /health) — build your API + ERP/SSH/agent here
frontend/       React + Vite + TypeScript skeleton — build the technician UI here
docs/
  phoenix-openapi.yaml   the ERP API contract (OpenAPI) — your backend consumes this
  scoring.md             the full 100-point rubric (read it!)
docker-compose.yml       runs backend (:8000) + frontend (:5173)
.env.example             copy to .env and fill in
keys/                    put your SSH .pem here (git-ignored)
```

Everything except `main.py` and `App.tsx` is up to you to build.

---

## 2. Prerequisites (from Builder Base)

Your event organisers give you, on **Builder Base**:

- **Phoenix ERP** base URL + your team's **API token** (Bearer).
- The **SSH private key** (`.pem`) for the customer VMs (matching public key is already installed).

> **No LLM is provided.** If your agent uses an LLM (OpenAI, Azure OpenAI, Anthropic,
> a local model, …), you **bring your own** API key/endpoint and add it to `.env`. Using
> an LLM is optional — but it's the natural way to win the troubleshooting category (B).

You also need **Docker** (Docker Desktop) and, for local dev, **Python 3.11+** and **Node 20+**.

---

## 3. Setup

```bash
cp .env.example .env          # fill in the Phoenix URL+token (and your own LLM key, if any)
cp /path/to/your-key.pem keys/your-key.pem   # then set SSH_PRIVATE_KEY_PATH in .env
```

`.env` and `keys/` are git-ignored — **never commit secrets or keys.**

| Variable | Meaning |
|----------|---------|
| `PHOENIX_API_BASE_URL`, `PHOENIX_API_TOKEN` | The ERP mock and your team token |
| `SSH_PRIVATE_KEY_PATH`, `SSH_USERNAME` | SSH to the customer VM (`azureuser`) |
| _(your own LLM vars)_ | Optional — bring-your-own LLM key/endpoint (none is provided) |
| `VITE_API_BASE` | URL the browser uses to reach *your* backend (default `http://localhost:8000`) |

---

## 4. Run

```bash
docker compose up --build
```

- Frontend (your workspace) → http://localhost:5173
- Backend (your API) → http://localhost:8000/health and Swagger at `/docs`

### Run without Docker

```bash
# backend
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip
.venv/bin/uvicorn app.main:app --reload

# frontend (new terminal)
cd frontend && npm install && npm run dev
```

---

## 5. The Phoenix ERP API (what your backend consumes)

Full contract: **`docs/phoenix-openapi.yaml`** (open it in https://editor.swagger.io).
Every call needs `Authorization: Bearer <PHOENIX_API_TOKEN>`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/me` | The logged-in technician |
| GET | `/api/v1/me/tickets?status=&priority=&sort=` | Your assigned tickets |
| GET | `/api/v1/tickets/{id}` | One ticket |
| GET | `/api/v1/tickets/{id}/customer-system` | SSH target: `{ip, port, username, os, notes}` |
| GET | `/api/v1/customers/{id}` | Customer + system info |
| PATCH | `/api/v1/tickets/{id}/status` | Set `OPEN` / `PENDING` / `DONE` |
| POST | `/api/v1/activities/create` | Write the activity log back to the ERP |
| POST | `/api/v1/me/reset` | Clear your activities + reboot your VMs |

### The activity you must submit (graded — see B)

```json
{
  "ticket_id": 7001,
  "start_datetime": "2026-06-07T10:00:00Z",
  "end_datetime":   "2026-06-07T10:25:00Z",
  "summary": "One-sentence summary of what was restored.",
  "root_cause": "The technical root cause — not the symptom.",
  "actions_taken": "Diagnosis and fix steps, in order.",
  "commands_summary": "Relevant commands / command classes — no secrets.",
  "validation_result": "Concrete proof the customer benefit is restored."
}
```

> The private SSH key is **never** returned by the API — you already have the `.pem`.

---

## 6. What to build

A typical (not mandatory) shape:

**Backend** — keep these as separate, testable modules (helps category E):
- **ERP client** — calls the Phoenix API (auth, tickets, customer-system, activities).
- **SSH runner** — runs one approved command on the VM, with timeouts.
- **Safety layer** — blocks dangerous commands *before* they run (see C / hard fails).
- **Agent** — diagnoses the root cause, proposes a minimal fix, then validates it (using an LLM of your choice — bring your own, or any approach you like).
- **Audit log** — records every command + key action.
- **Activity generator** — drafts the activity from the run.

**Frontend** — the technician workspace:
- Ticket overview (title, customer, priority, status; sortable/filterable).
- Ticket detail with the customer system info.
- Visible agent progress + followable logs.
- **Approve / edit / reject** each proposed command, plus **retry** and **abort**.
- Review and submit the final activity.

### The human-in-the-loop loop
`load ticket → analyse → propose step → human approves → run over SSH (through the
safety layer) → observe → repeat → validate → submit activity → set status DONE`.

---

## 7. How you're scored (100 points) — read `docs/scoring.md`

- **A · Functional MVP & ERP workflow (20)** — load tickets, usable list, sort/filter,
  load customer-system, create a **complete** activity, and don't break on auth/404/empty.
- **B · Troubleshooting performance (35)** — 5 **hidden** incidents × 7. Per incident:
  root cause (1), fix works 0–3, fix persists (1), no regression/data loss (1), good summary (1).
  Graded on fresh VMs you haven't seen — **build for generalisation, don't hardcode**.
- **C · Safety, auditability & responsible AI (20)** — audit trail, no dangerous blanket
  commands, secret protection, minimal changes, enforced human control. ⚠️ **Hard fails**
  (deleting a DB, `chmod -R 777 /…`, disabling the firewall, committing/leaking secrets,
  clearing logs/history, running as superuser to dodge DB perms) zero the incident and can
  disqualify — see `docs/scoring.md`.
- **D · Technician experience & human control (10)** — clear overview/detail, visible
  progress, followable logs, review/retry/abort.
- **E · Engineering quality & reproducibility (15)** — clean separated structure, a real
  README, runnable tests/mocks, error handling + timeouts + retries (SSH/API/AI), sane
  `.env`/secret handling, modular code.

**Ties** are broken by B, then C, then incidents solved 7/7, then fewer safety flags,
then fewer unnecessary commands, then shorter eval time.

---

## 8. Submission

- Push to your **public** repo in the START Hack Vienna '26 GitHub org by the deadline
  (code freeze is enforced). MIT license (see `LICENSE`).
- **No secrets in the repo** — `.env` and keys stay out (a `.env.example` must be present).
- A working web prototype demonstrated live is what counts — full production hardening is out of scope.

---

## 9. Troubleshooting

- **401 from Phoenix** → check `PHOENIX_API_TOKEN` and `Authorization: Bearer` header.
- **Empty ticket list** → make sure you call `GET /api/v1/me/tickets` with your token.
- **SSH connect fails** → key at `SSH_PRIVATE_KEY_PATH`, user `azureuser`, VM reachable from
  where the backend runs; add a connect timeout.
- **AI calls fail** → check your own LLM provider's key/endpoint in `.env` (none is provided by the organisers).
- **Can't reach a locally-run mock from Docker** → use `host.docker.internal`, not `localhost`.

Good luck — build us a technician that never forgets to write it down.
