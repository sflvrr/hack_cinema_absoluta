import httpx
import os

# Читаем ключи из .env
PHOENIX_BASE_URL = os.getenv("PHOENIX_API_BASE_URL", "").rstrip("/")
PHOENIX_TOKEN = os.getenv("PHOENIX_API_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {PHOENIX_TOKEN}"}

async def list_tickets():
    """Скачивает список тикетов с сервера организаторов"""
    async with httpx.AsyncClient() as client:
        url = f"{PHOENIX_BASE_URL}/api/v1/me/tickets"
        response = await client.get(url, headers=HEADERS)
        response.raise_for_status()  # Если будет ошибка 401/404, она отобразится
        return response.json()

# Остальные заглушки пока можно оставить как есть
async def get_customer_system(ticket_id): ...
async def create_activity(payload): ...
async def patch_ticket_status(ticket_id, status): ...