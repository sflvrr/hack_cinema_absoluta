"""FastAPI entrypoint — skeleton.

This is intentionally minimal. Build your own API here for the frontend to call,
and consume the Phoenix ERP mock from your backend (see docs/phoenix-openapi.yaml).
Keep the ERP token and the SSH key on the backend — never in the browser.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="techbold AI Service Desk Autopilot — Team Backend")

# Open CORS for local dev so your React app can call this backend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# TODO: add your routes. A typical shape (yours may differ):
#   GET  /api/tickets              -> list tickets (via your Phoenix client)
#   GET  /api/tickets/{id}         -> ticket + customer system
#   POST /api/runs                 -> start an agent troubleshooting run
#   POST /api/runs/{id}/approve    -> run the approved command over SSH
#   POST /api/runs/{id}/activity   -> submit the activity to the ERP
