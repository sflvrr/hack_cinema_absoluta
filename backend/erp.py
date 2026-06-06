"""
erp_client.py — Phoenix ERP API client
All calls to the Phoenix mock go through this module.
"""

import os
import asyncio
import logging
from typing import Optional
from datetime import datetime

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config (loaded from environment)
# ---------------------------------------------------------------------------

PHOENIX_BASE_URL = os.getenv("PHOENIX_API_BASE_URL", "").rstrip("/")
PHOENIX_TOKEN    = os.getenv("PHOENIX_API_TOKEN", "")

if not PHOENIX_BASE_URL or not PHOENIX_TOKEN:
    logger.warning(
        "PHOENIX_API_BASE_URL or PHOENIX_API_TOKEN is not set — "
        "ERP calls will fail at runtime."
    )

_HEADERS = {"Authorization": f"Bearer {PHOENIX_TOKEN}"}

# Retry settings
_MAX_RETRIES    = 3
_RETRY_BACKOFF  = 1.5   # seconds; doubles each attempt
_CONNECT_TIMEOUT = 5
_READ_TIMEOUT    = 10

# ---------------------------------------------------------------------------
# Typed response models (mirrors the OpenAPI schemas)
# ---------------------------------------------------------------------------

class Employee(BaseModel):
    id: int
    firstname: str
    lastname: str
    username: str
    teamname: str


class Ticket(BaseModel):
    id: int
    title: str
    description: str
    priority: str
    status: str                  # OPEN | PENDING | DONE
    customer_id: int
    customer_name: str
    tags: list[str] = []
    sla_due_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class SystemInfo(BaseModel):
    ip: str
    port: int
    username: str
    os: str
    notes: Optional[str] = None


class CustomerSystem(BaseModel):
    ticket_id: int
    customer_id: int
    system: SystemInfo


class Customer(BaseModel):
    id: int
    company_name: str
    firstname: str
    lastname: str
    system: SystemInfo


class ActivityCreate(BaseModel):
    ticket_id: int
    start_datetime: datetime
    end_datetime: datetime
    summary: str
    root_cause: str
    actions_taken: str
    commands_summary: str
    validation_result: str
    description: Optional[str] = None


class Activity(BaseModel):
    id: int
    team_id: int
    team_name: str
    employee_id: int
    ticket_id: int
    start_datetime: datetime
    end_datetime: datetime
    summary: Optional[str] = None
    root_cause: Optional[str] = None
    actions_taken: Optional[str] = None
    commands_summary: Optional[str] = None
    validation_result: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Internal HTTP helper with retry + structured error handling
# ---------------------------------------------------------------------------

class ERPError(Exception):
    """Raised for all Phoenix API errors."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Phoenix ERP {status_code}: {detail}")


class ERPNotFound(ERPError):
    pass


class ERPUnauthorized(ERPError):
    pass


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=PHOENIX_BASE_URL,
        headers=_HEADERS,
        timeout=httpx.Timeout(connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=10.0, pool=5.0),
    )


async def _request(method: str, path: str, **kwargs) -> dict:
    """
    Execute an HTTP request against Phoenix with exponential-backoff retries.
    Raises ERPUnauthorized, ERPNotFound, or ERPError on failure.
    """
    last_exc: Exception = RuntimeError("No attempts made")

    for attempt in range(_MAX_RETRIES):
        try:
            async with _client() as client:
                resp = await client.request(method, path, **kwargs)

            if resp.status_code == 401:
                raise ERPUnauthorized(401, "Invalid or missing PHOENIX_API_TOKEN")

            if resp.status_code == 404:
                raise ERPNotFound(404, f"Resource not found: {path}")

            if resp.status_code == 422:
                raise ERPError(422, f"Validation error: {resp.text}")

            if resp.status_code >= 500:
                # Server error — worth retrying
                raise ERPError(resp.status_code, f"Server error: {resp.text}")

            resp.raise_for_status()
            return resp.json()

        except (ERPUnauthorized, ERPNotFound, ERPError) as exc:
            # Auth / validation / 4xx — no point retrying
            if isinstance(exc, ERPError) and exc.status_code < 500:
                raise
            last_exc = exc
        except httpx.TimeoutException as exc:
            last_exc = ERPError(0, f"Request timed out: {exc}")
        except httpx.RequestError as exc:
            last_exc = ERPError(0, f"Network error: {exc}")

        if attempt < _MAX_RETRIES - 1:
            wait = _RETRY_BACKOFF * (2 ** attempt)
            logger.warning("Phoenix request failed (attempt %d/%d), retrying in %.1fs — %s",
                           attempt + 1, _MAX_RETRIES, wait, last_exc)
            await asyncio.sleep(wait)

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------

async def get_me() -> Employee:
    """Return the logged-in technician."""
    data = await _request("GET", "/api/v1/me")
    return Employee(**data)


async def list_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    sort: Optional[str] = "date",
) -> list[Ticket]:
    """
    Return all tickets assigned to this team.

    Args:
        status:   Filter by OPEN | PENDING | DONE (omit for all).
        priority: Filter by priority string, e.g. "high".
        sort:     One of date | priority | status (default: date).
    """
    params: dict = {}
    if status:
        params["status"] = status
    if priority:
        params["priority"] = priority
    if sort:
        params["sort"] = sort

    data = await _request("GET", "/api/v1/me/tickets", params=params)
    return [Ticket(**t) for t in data]


async def get_ticket(ticket_id: int) -> Ticket:
    """Return a single ticket by ID."""
    data = await _request("GET", f"/api/v1/tickets/{ticket_id}")
    return Ticket(**data)


async def get_customer_system(ticket_id: int) -> CustomerSystem:
    """Return the SSH target (ip, port, username, os, notes) for a ticket."""
    data = await _request("GET", f"/api/v1/tickets/{ticket_id}/customer-system")
    return CustomerSystem(**data)


async def get_customer(customer_id: int) -> Customer:
    """Return customer details including their system info."""
    data = await _request("GET", f"/api/v1/customers/{customer_id}")
    return Customer(**data)


async def patch_ticket_status(ticket_id: int, status: str) -> Ticket:
    """
    Set a ticket's status.

    Args:
        ticket_id: The ticket to update.
        status:    One of OPEN | PENDING | DONE.
    """
    if status not in {"OPEN", "PENDING", "DONE"}:
        raise ValueError(f"Invalid status '{status}' — must be OPEN, PENDING, or DONE")
    data = await _request(
        "PATCH",
        f"/api/v1/tickets/{ticket_id}/status",
        json={"status": status},
    )
    return Ticket(**data)


async def create_activity(payload: ActivityCreate) -> Activity:
    """
    Write the completed activity log back to Phoenix.
    This is the graded documentation step — fill every field carefully.
    """
    data = await _request(
        "POST",
        "/api/v1/activities/create",
        json=payload.model_dump(mode="json"),
    )
    return Activity(**data)


async def reset_me() -> dict:
    """Clear all team activities and reboot VMs. Use with care."""
    return await _request("POST", "/api/v1/me/reset")