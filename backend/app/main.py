import os
import sys
import asyncio
import logging
from typing import Dict, List, Any, Optional

# --- 1. Грузим .env ПЕРВЫМ делом, чтобы токены были доступны при импорте erp ---
from dotenv import load_dotenv

load_dotenv()

# --- 2. Импорт ERP-клиента (поддержка запуска и как пакет, и как скрипт) ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from app import erp
    from app.ssh_runner import run_ssh_command
    from app.safety import check_command
except ImportError:
    from . import erp
    from .ssh_runner import run_ssh_command
    from .safety import check_command

import httpx
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Service Desk Autopilot - Backend")

# CORS: по умолчанию только фронтенд; можно расширить через ALLOWED_ORIGINS.
_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- АВТОРИЗАЦИЯ (ключи из окружения, с дефолтами для локалки) ---
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

ADMIN_KEY = os.getenv("BACKEND_ADMIN_KEY", "dev-admin-key")
USER_KEY = os.getenv("BACKEND_USER_KEY", "dev-user-key")

# Сколько секунд держим HTTP-запрос от n8n в ожидании решения техника.
APPROVAL_WAIT_TIMEOUT = int(os.getenv("APPROVAL_WAIT_TIMEOUT", "600"))


def verify_admin(api_key: str = Security(api_key_header)):
    if api_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    return api_key


def verify_user(api_key: str = Security(api_key_header)):
    if api_key not in (ADMIN_KEY, USER_KEY):
        raise HTTPException(status_code=403, detail="Access denied.")
    return api_key


# --- ХРАНИЛИЩЕ СОСТОЯНИЙ (In-Memory) ---
active_proposals: Dict[int, Dict[str, Any]] = {}
approval_events: Dict[int, asyncio.Event] = {}
execution_results: Dict[int, str] = {}
audit_logs: Dict[int, List[Dict[str, Any]]] = {}


def _cleanup_ticket_state(ticket_id: int) -> None:
    """Чистим всё временное состояние по тикету (proposal + event)."""
    active_proposals.pop(ticket_id, None)
    approval_events.pop(ticket_id, None)


# --- СХЕМЫ ДАННЫХ (Pydantic) ---
class ProposeRequest(BaseModel):
    ticket_id: int
    command: str
    target_ip: str


class ApproveRequest(BaseModel):
    command: str


class StatusRequest(BaseModel):
    status: str


class ActivityRequest(BaseModel):
    ticket_id: int
    start_datetime: str
    end_datetime: str
    summary: Optional[str] = None
    root_cause: Optional[str] = None
    actions_taken: Optional[str] = None
    commands_summary: Optional[str] = None
    validation_result: Optional[str] = None
    description: Optional[str] = None


def _erp_error(e: Exception) -> HTTPException:
    """Преобразуем ошибку httpx в аккуратный HTTP-ответ наружу."""
    if isinstance(e, httpx.HTTPStatusError):
        return HTTPException(status_code=e.response.status_code, detail=e.response.text)
    return HTTPException(status_code=502, detail=f"ERP error: {e}")


# ==========================================
# ЭНДПОИНТЫ
# ==========================================

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/me")
async def get_me(api_key: str = Depends(verify_user)):
    try:
        return {"status": "ok", "me": await erp.get_me()}
    except Exception as e:
        logger.error(f"ERP /me error: {e}")
        raise _erp_error(e)


@app.get("/api/tickets")
async def get_all_tickets(api_key: str = Depends(verify_user)):
    """Список тикетов из ERP (для фронтенда)."""
    try:
        tickets = await erp.list_tickets()
        return {"status": "ok", "tickets": tickets}
    except Exception as e:
        logger.error(f"Ошибка получения тикетов из ERP: {e}")
        return {"status": "error", "tickets": [], "detail": str(e)}


@app.get("/api/tickets/{ticket_id}/customer-system")
async def customer_system(ticket_id: int, api_key: str = Depends(verify_user)):
    """SSH-таргет тикета (ip/port/username/os). Зовётся и фронтом, и n8n."""
    try:
        return await erp.get_customer_system(ticket_id)
    except Exception as e:
        logger.error(f"ERP customer-system error: {e}")
        raise _erp_error(e)


@app.patch("/api/tickets/{ticket_id}/status")
async def set_status(ticket_id: int, req: StatusRequest, api_key: str = Depends(verify_user)):
    """Смена статуса тикета в ERP (OPEN/PENDING/DONE)."""
    try:
        return await erp.patch_ticket_status(ticket_id, req.status)
    except Exception as e:
        logger.error(f"ERP status error: {e}")
        raise _erp_error(e)


@app.post("/api/activities/create")
async def create_activity(req: ActivityRequest, api_key: str = Depends(verify_user)):
    """Финальный лог работ -> ERP. Пустые поля не отправляем."""
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        return await erp.create_activity(payload)
    except Exception as e:
        logger.error(f"ERP create_activity error: {e}")
        raise _erp_error(e)


@app.post("/api/reset")
async def reset(api_key: str = Depends(verify_admin)):
    """Сброс активностей и ребут VM (только admin)."""
    try:
        return await erp.reset_me()
    except Exception as e:
        logger.error(f"ERP reset error: {e}")
        raise _erp_error(e)


@app.post("/api/runs/propose-{stage}")
async def propose_command(stage: str, req: ProposeRequest, api_key: str = Depends(verify_admin)):
    """
    n8n предлагает команду и «замирает» здесь до решения техника.
    Если за APPROVAL_WAIT_TIMEOUT секунд никто не ответил — возвращаем таймаут
    и чистим состояние, чтобы не осталась протухшая команда.
    """
    ticket_id = req.ticket_id

    # Превентивная safety-проверка — чтобы заведомо опасное даже не показывать.
    allowed, reason = check_command(req.command)

    active_proposals[ticket_id] = {
        "stage": stage,
        "original_command": req.command,
        "target_ip": req.target_ip,
        "safety_ok": allowed,
        "safety_reason": reason,
    }
    event = asyncio.Event()
    approval_events[ticket_id] = event
    audit_logs.setdefault(ticket_id, [])

    try:
        await asyncio.wait_for(event.wait(), timeout=APPROVAL_WAIT_TIMEOUT)
    except asyncio.TimeoutError:
        _cleanup_ticket_state(ticket_id)
        execution_results.pop(ticket_id, None)
        return {"output": "TIMEOUT: технику не дали подтверждение вовремя.", "timed_out": True}

    result = execution_results.pop(ticket_id, "No result")
    return {"output": result}


class StartRunRequest(BaseModel):
    ticket_id: int
    webhook_url: str


@app.post("/api/runs/start")
async def start_run(req: StartRunRequest, api_key: str = Depends(verify_user)):
    """
    Прокси: фронт зовёт этот эндпоинт, бэкенд POST'ит в n8n webhook.
    Server-to-server -> никакого CORS, в отличие от запроса из браузера.
    """
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)) as client:
            resp = await client.post(req.webhook_url, json={"ticket_id": req.ticket_id})
            resp.raise_for_status()
            body = resp.json() if resp.content else None
        return {"status": "started", "n8n_response": body}
    except httpx.HTTPStatusError as e:
        logger.error(f"n8n webhook вернул ошибку: {e.response.status_code} {e.response.text}")
        raise HTTPException(status_code=502, detail=f"n8n ответил {e.response.status_code}: {e.response.text}")
    except Exception as e:
        logger.error(f"Не удалось вызвать n8n webhook: {e}")
        raise HTTPException(status_code=502, detail=f"Не удалось достучаться до n8n: {e}")


@app.get("/api/tickets/{ticket_id}/audit-log")
async def get_audit_log(ticket_id: int, api_key: str = Depends(verify_user)):
    return {"log": audit_logs.get(ticket_id, [])}


@app.get("/api/tickets/{ticket_id}/proposal")
async def get_current_proposal(ticket_id: int, api_key: str = Depends(verify_user)):
    proposal = active_proposals.get(ticket_id)
    if not proposal:
        return {"status": "waiting_for_ai", "proposal": None}
    return {"status": "needs_approval", "proposal": proposal}


@app.post("/api/tickets/{ticket_id}/approve")
async def approve_command(ticket_id: int, req: ApproveRequest, api_key: str = Depends(verify_user)):
    proposal = active_proposals.get(ticket_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="No active proposal found")
    event = approval_events.get(ticket_id)
    if not event:
        raise HTTPException(status_code=400, detail="Approval event not found")

    target_ip = proposal["target_ip"]
    final_command = req.command
    ssh_output = run_ssh_command(target_ip, final_command)

    audit_logs.setdefault(ticket_id, []).append({
        "stage": proposal["stage"],
        "ai_proposed": proposal["original_command"],
        "human_executed": final_command,
        "output": ssh_output,
    })

    execution_results[ticket_id] = ssh_output
    _cleanup_ticket_state(ticket_id)
    event.set()
    return {"status": "executed", "output": ssh_output}


@app.post("/api/tickets/{ticket_id}/reject")
async def reject_command(ticket_id: int, api_key: str = Depends(verify_user)):
    proposal = active_proposals.get(ticket_id)
    event = approval_events.get(ticket_id)
    if not proposal or not event:
        raise HTTPException(status_code=404, detail="No active proposal")

    execution_results[ticket_id] = "HUMAN REJECTED THIS COMMAND. Propose a different approach."
    audit_logs.setdefault(ticket_id, []).append({
        "stage": proposal["stage"],
        "ai_proposed": proposal["original_command"],
        "human_executed": None,
        "output": "REJECTED BY HUMAN",
    })
    _cleanup_ticket_state(ticket_id)
    event.set()
    return {"status": "rejected"}
