import asyncio
import paramiko
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="AI Service Desk Autopilot - Backend")

# Открываем CORS для React
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- АВТОРИЗАЦИЯ (Разделение Admin / User) ---
# n8n будет использовать ADMIN_KEY, а фронтенд - USER_KEY
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

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

# --- ХРАНИЛИЩЕ СОСТОЯНИЙ (In-Memory для хакатона) ---
# Хранит текущие предложенные команды
active_proposals: Dict[int, dict] = {}  
# Хранит события asyncio для "заморозки" запросов
approval_events: Dict[int, asyncio.Event] = {} 
# Хранит результаты выполнения SSH
execution_results: Dict[int, str] = {}
# Полный аудит-лог для финала
audit_logs: Dict[int, List[dict]] = {}

# --- СХЕМЫ ДАННЫХ (Pydantic) ---
class ProposeRequest(BaseModel):
    ticket_id: int
    command: str
    target_ip: str  # IP виртуалки, куда нужно будет стучаться

class ApproveRequest(BaseModel):
    command: str  # Фронтенд может прислать измененную команду

# --- УТИЛИТА: ВЫПОЛНЕНИЕ SSH ---
def run_ssh_command(ip: str, command: str) -> str:
    # Защита от опасных команд (Safety Layer - Обязательно для баллов!)
    dangerous_keywords = ["rm -rf", "chmod -R 777", "mkfs"]
    if any(bad in command for bad in dangerous_keywords):
        return "BLOCKED BY SAFETY LAYER: Dangerous command detected."

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # Подключаемся с приватным ключом из папки /keys/
        key = paramiko.RSAKey.from_private_key_file("/keys/your-key.pem")
        
        # Подключение к серверу клиента (пользователь из шаблона .env)
        client.connect(hostname=ip, username="azureuser", pkey=key, timeout=10)
        
        stdin, stdout, stderr = client.exec_command(command, timeout=30)
        output = stdout.read().decode('utf-8') + stderr.read().decode('utf-8')
        client.close()
        return output if output else "[Command executed successfully, no output]"
    except Exception as e:
        return f"SSH Connection Error: {str(e)}"

# ==========================================
# 1. ЭНДПОИНТЫ ДЛЯ n8n (АДМИН)
# ==========================================

@app.post("/api/runs/propose-{stage}")
async def propose_command(stage: str, req: ProposeRequest, api_key: str = Depends(verify_admin)):
    """n8n присылает команду и ЗАВИСАЕТ здесь, пока человек не нажмет Approve"""
    ticket_id = req.ticket_id
    
    # Записываем предложение в память, чтобы фронтенд мог его прочитать
    active_proposals[ticket_id] = {
        "stage": stage,
        "original_command": req.command,
        "target_ip": req.target_ip
    }
    
    # Создаем событие и сбрасываем его
    event = asyncio.Event()
    approval_events[ticket_id] = event
    
    # Инициализируем аудит-лог, если его еще нет
    if ticket_id not in audit_logs:
        audit_logs[ticket_id] = []
        
    # БЭКЕНД ЖДЕТ ЗДЕСЬ (Зависает, не блокируя остальные запросы)
    await event.wait()
    
    # Когда событие сработает (техник нажал Approve), отдаем результат в n8n
    result = execution_results.pop(ticket_id, "No result")
    
    return {"output": result}

@app.get("/api/tickets/{ticket_id}/audit-log")
async def get_audit_log(ticket_id: int, api_key: str = Depends(verify_admin)):
    """n8n запрашивает этот лог в самом конце для генерации отчета"""
    return {"log": audit_logs.get(ticket_id, [])}

# ==========================================
# 2. ЭНДПОИНТЫ ДЛЯ FRONTEND (ПОЛЬЗОВАТЕЛЬ)
# ==========================================

@app.get("/api/tickets/{ticket_id}/proposal")
async def get_current_proposal(ticket_id: int, api_key: str = Depends(verify_user)):
    """Фронтенд поллит этот эндпоинт, чтобы узнать, что предложил ИИ"""
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
    final_command = req.command  # Берем команду, которую (возможно) поправил человек
    
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
    del active_proposals[ticket_id] # Очищаем текущее предложение
    event.set() # <--- ЭТО РАЗМОРОЗИТ n8n!
    
    return {"status": "executed", "output": ssh_output}

@app.post("/api/tickets/{ticket_id}/reject")
async def reject_command(ticket_id: int, api_key: str = Depends(verify_user)):
    """Сисадмин отклоняет команду ИИ"""
    proposal = active_proposals.get(ticket_id)
    if not proposal or ticket_id not in approval_events:
        raise HTTPException(status_code=404, detail="No active proposal")

    # Передаем в n8n информацию об отказе, чтобы Агент придумал что-то другое
    execution_results[ticket_id] = "HUMAN REJECTED THIS COMMAND. Propose a different approach."
    del active_proposals[ticket_id]
    
    # Размораживаем n8n
    approval_events[ticket_id].set()
    return {"status": "rejected"}