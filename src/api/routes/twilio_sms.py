from fastapi import APIRouter

router = APIRouter()

@router.post("/webhook")
async def sms_webhook():
    """Stubbed SMS endpoint to prevent Uvicorn crash."""
    return {"status": "ok"}
