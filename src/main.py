# Load .env BEFORE importing any module that reads env vars at import time
# (e.g. twilio_voice instantiates ElevenLabsTTS which reads ELEVENLABS_API_KEY).
from dotenv import load_dotenv
load_dotenv()

import os
print(f"[lily] ELEVENLABS_API_KEY loaded: {'yes' if os.getenv('ELEVENLABS_API_KEY') else 'NO ✗'}", flush=True)
print(f"[lily] ANTHROPIC_API_KEY  loaded: {'yes' if os.getenv('ANTHROPIC_API_KEY') else 'NO ✗'}", flush=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.routes import twilio_voice, twilio_sms, doctor_portal

app = FastAPI(
    title="Lily API",
    description="Backend for Lily - The Maternal Health Companion",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

# Routes — must be registered before the StaticFiles mount so they aren't shadowed
app.include_router(twilio_voice.router, prefix="/api/twilio/voice", tags=["Twilio Voice"])
app.include_router(twilio_sms.router, prefix="/api/twilio/sms", tags=["Twilio SMS"])
app.include_router(doctor_portal.router, prefix="/api/portal", tags=["Doctor Portal"])

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Lily"}

# StaticFiles must be mounted last — a mount at "/" catches everything not yet matched
app.mount("/", StaticFiles(directory="dashboard", html=True), name="dashboard")
