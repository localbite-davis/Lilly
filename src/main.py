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

# Include Routers
app.include_router(twilio_voice.router, prefix="/api/twilio/voice", tags=["Twilio Voice"])
app.include_router(twilio_sms.router, prefix="/api/twilio/sms", tags=["Twilio SMS"])
app.include_router(doctor_portal.router, prefix="/api/portal", tags=["Doctor Portal"])

# Mount Person 4's Dashboard UI
app.mount("/", StaticFiles(directory="dashboard", html=True), name="dashboard")

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "Lily"}
