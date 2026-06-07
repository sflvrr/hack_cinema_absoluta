"""
Phoenix ERP client.

Тонкий асинхронный клиент к mock-ERP организаторов (Phoenix).
Все эндпоинты реализованы строго по docs/phoenix-openapi.yaml.

Каждый запрос:
  - использует Bearer-токен из .env,
  - имеет таймаут (категория E: error handling + timeouts),
  - бросает httpx.HTTPStatusError на 4xx/5xx (ловится в main.py).
"""

import os
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# --- Конфиг из окружения ---
PHOENIX_BASE_URL = os.getenv("PHOENIX_API_BASE_URL", "").rstrip("/")
PHOENIX_TOKEN = os.getenv("PHOENIX_API_TOKEN", "")

# Таймауты: коннект отдельно от чтения, чтобы зависший ERP не вешал бэкенд.
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)


def _headers() -> Dict[str, str]:
    """Собираем заголовки на каждый запрос (а не один раз при импорте),
    чтобы токен подхватывался даже если .env загрузился позже."""
    token = os.getenv("PHOENIX_API_TOKEN", PHOENIX_TOKEN)
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _base_url() -> str:
    return os.getenv("PHOENIX_API_BASE_URL", PHOENIX_BASE_URL).rstrip("/")


async def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
) -> Any:
    """Единая точка для всех HTTP-вызовов к ERP."""
    base = _base_url()
    if not base:
        raise RuntimeError("PHOENIX_API_BASE_URL не задан в .env")

    url = f"{base}{path}"
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        resp = await client.request(
            method, url, headers=_headers(), params=params, json=json
        )
        resp.raise_for_status()  # 401/404/422 -> исключение, ловим в main.py
        # У некоторых ответов (PATCH/POST) тело может быть пустым — подстрахуемся.
        if resp.content:
            return resp.json()
        return None


# --- ЭНДПОИНТЫ ---

async def get_me() -> Dict[str, Any]:
    """GET /api/v1/me — личность техника (нужно для employee_id в activity)."""
    return await _request("GET", "/api/v1/me")


async def list_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    sort: str = "date",
) -> List[Dict[str, Any]]:
    """GET /api/v1/me/tickets — назначенные тикеты с фильтрами/сортировкой."""
    params: Dict[str, Any] = {"sort": sort}
    if status:
        params["status"] = status
    if priority:
        params["priority"] = priority
    return await _request("GET", "/api/v1/me/tickets", params=params)


async def get_ticket(ticket_id: int) -> Dict[str, Any]:
    """GET /api/v1/tickets/{id} — один тикет."""
    return await _request("GET", f"/api/v1/tickets/{ticket_id}")


async def get_customer_system(ticket_id: int) -> Dict[str, Any]:
    """GET /api/v1/tickets/{id}/customer-system — SSH-таргет (ip, port, username, os, notes)."""
    return await _request("GET", f"/api/v1/tickets/{ticket_id}/customer-system")


async def get_customer(customer_id: int) -> Dict[str, Any]:
    """GET /api/v1/customers/{id} — данные клиента + система."""
    return await _request("GET", f"/api/v1/customers/{customer_id}")


async def patch_ticket_status(ticket_id: int, status: str) -> Dict[str, Any]:
    """PATCH /api/v1/tickets/{id}/status — OPEN / PENDING / DONE."""
    return await _request(
        "PATCH", f"/api/v1/tickets/{ticket_id}/status", json={"status": status}
    )


async def create_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/v1/activities/create — финальный лог работ (графится в категории B)."""
    return await _request("POST", "/api/v1/activities/create", json=payload)


async def reset_me() -> Dict[str, Any]:
    """POST /api/v1/me/reset — сброс активностей и ребут VM (чистый старт)."""
    return await _request("POST", "/api/v1/me/reset")