import asyncio
import paramiko
import logging
from typing import Dict, List, Any
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import glob

# Настраиваем базовое логирование, чтобы видеть ошибки в консоли Docker
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Service Desk Autopilot - Backend")

# Открываем CORS для React фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- АВТОРИЗАЦИЯ (Разделение Admin / User) ---
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

# Ключи доступа (в реальном проекте их выносят в .env)
ADMIN_KEY = "secret-n8n-admin-key"
USER_KEY = "secret-react-user-key"


def verify_admin(api_key: str = Security(api_key_header)):
    if api_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Access denied. Admin only.")
    return api_key


def verify_user(api_key: str = Security(api_key_header)):
    if api_key not in [ADMIN_KEY, USER_KEY]:
        raise HTTPException(status_code=403, detail="Access denied.")
    return api_key


# --- ХРАНИЛИЩЕ СОСТОЯНИЙ (In-Memory) ---
active_proposals: Dict[int, Dict[str, Any]] = {}
approval_events: Dict[int, asyncio.Event] = {}
execution_results: Dict[int, str] = {}
audit_logs: Dict[int, List[Dict[str, Any]]] = {}


# --- СХЕМЫ ДАННЫХ (Pydantic) ---
class ProposeRequest(BaseModel):
    ticket_id: int
    command: str
    target_ip: str


class ApproveRequest(BaseModel):
    command: str


# --- УТИЛИТА: ВЫПОЛНЕНИЕ SSH ---
def run_ssh_command(ip: str, command: str) -> str:
    # Базовый Safety Layer
    dangerous_keywords = ["rm -rf /", "chmod -R 777", "mkfs"]
    if any(bad in command for bad in dangerous_keywords):
        return "BLOCKED BY SAFETY LAYER: Dangerous command detected."

    # Находим ВСЕ файлы с расширением .pem в папке /keys/
    key_files = glob.glob("/keys/*.pem")

    if not key_files:
        return "SSH Error: Файлы ключей (.pem) не найдены в папке /keys/"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    last_error = ""

    # Перебираем все ключи по очереди
    for key_path in key_files:
        try:
            logger.info(f"Попытка подключения к {ip} с ключом {key_path}...")
            key = paramiko.RSAKey.from_private_key_file(key_path)

            # Пробуем подключиться (таймаут 10 секунд)
            client.connect(hostname=ip, username="azureuser", pkey=key, timeout=10)

            # Если код дошел сюда — ключ подошел! Выполняем команду.
            logger.info(f"Успешное подключение к {ip}! Выполняем команду...")
            stdin, stdout, stderr = client.exec_command(command, timeout=30)
            output = stdout.read().decode('utf-8') + stderr.read().decode('utf-8')
            client.close()

            return output if output.strip() else "[Command executed successfully, no output]"

        except paramiko.AuthenticationException:
            # Если ключ не подошел, ловим ошибку авторизации и пробуем следующий ключ
            last_error = f"Auth failed with {os.basename(key_path)}"
            continue

        except Exception as e:
            # Если ошибка не связана с ключом (например, виртуалка выключена или IP не пингуется)
            # нет смысла перебирать остальные ключи. Выходим с ошибкой.
            logger.error(f"SSH Critical Error for IP {ip}: {str(e)}")
            return f"SSH Connection Error: {str(e)}"

    # Если цикл завершился и ни один ключ не подошел
    return f"SSH Connection Error: Could not authenticate with any key. Last error: {last_error}"


# ==========================================
# БАЗОВЫЕ ЭНДПОИНТЫ
# ==========================================

@app.get("/health")
def health():
    """Эндпоинт для проверки жизнеспособности контейнера Docker"""
    return {"status": "ok"}


# ==========================================
# 1. ЭНДПОИНТЫ ДЛЯ n8n (АДМИН)
# ==========================================

@app.post("/api/runs/propose-{stage}")
async def propose_command(stage: str, req: ProposeRequest, api_key: str = Depends(verify_admin)):
    """n8n присылает команду и ЗАВИСАЕТ здесь, пока человек не нажмет Approve"""
    ticket_id = req.ticket_id

    active_proposals[ticket_id] = {
        "stage": stage,
        "original_command": req.command,
        "target_ip": req.target_ip
    }

    event = asyncio.Event()
    approval_events[ticket_id] = event

    if ticket_id not in audit_logs:
        audit_logs[ticket_id] = []

    # БЭКЕНД ЖДЕТ ЗДЕСЬ (Не блокируя другие запросы)
    await event.wait()

    # Когда событие сработает, отдаем результат
    result = execution_results.pop(ticket_id, "No result")
    return {"output": result}


@app.get("/api/tickets/{ticket_id}/audit-log")
async def get_audit_log(ticket_id: int, api_key: str = Depends(verify_admin)):
    """n8n запрашивает этот лог в самом конце"""
    return {"log": audit_logs.get(ticket_id, [])}


# ==========================================
# 2. ЭНДПОИНТЫ ДЛЯ FRONTEND (ПОЛЬЗОВАТЕЛЬ)
# ==========================================

@app.get("/api/tickets/{ticket_id}/proposal")
async def get_current_proposal(ticket_id: int, api_key: str = Depends(verify_user)):
    """Фронтенд поллит этот эндпоинт"""
    proposal = active_proposals.get(ticket_id)
    if not proposal:
        return {"status": "waiting_for_ai", "proposal": None}
    return {"status": "needs_approval", "proposal": proposal}


@app.post("/api/tickets/{ticket_id}/approve")
async def approve_command(ticket_id: int, req: ApproveRequest, api_key: str = Depends(verify_user)):
    """Сисадмин нажимает Approve/Edit на фронтенде"""
    proposal = active_proposals.get(ticket_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="No active proposal found")

    event = approval_events.get(ticket_id)
    if not event:
        raise HTTPException(status_code=400, detail="Approval event not found")

    target_ip = proposal["target_ip"]
    final_command = req.command

    # 1. Выполняем по SSH
    ssh_output = run_ssh_command(target_ip, final_command)

    # 2. Пишем в Аудит-лог
    audit_logs[ticket_id].append({
        "stage": proposal["stage"],
        "ai_proposed": proposal["original_command"],
        "human_executed": final_command,
        "output": ssh_output
    })

    # 3. Сохраняем результат и снимаем с паузы n8n
    execution_results[ticket_id] = ssh_output
    del active_proposals[ticket_id]

    event.set()  # Размораживаем запрос n8n

    return {"status": "executed", "output": ssh_output}


@app.post("/api/tickets/{ticket_id}/reject")
async def reject_command(ticket_id: int, api_key: str = Depends(verify_user)):
    """Сисадмин отклоняет команду ИИ"""
    proposal = active_proposals.get(ticket_id)
    if not proposal or ticket_id not in approval_events:
        raise HTTPException(status_code=404, detail="No active proposal")

    execution_results[ticket_id] = "HUMAN REJECTED THIS COMMAND. Propose a different approach."
    del active_proposals[ticket_id]

    approval_events[ticket_id].set()
    return {"status": "rejected"}