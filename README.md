# Lily 🌸
**The accessible, voice-first maternal health companion for maternity deserts.**

Lily is a phone number. No app. No smartphone. No data plan. No English required. Any pregnant woman or new mother can call Lily to receive empathetic support, plain-language education, and immediate triage grounded in clinical guidelines. 

When a caller reports symptoms, Lily doesn't just guess—she routes them through a deterministic rules engine built on the American College of Obstetricians and Gynecologists (ACOG) Urgent Maternal Warning Signs. If a doctor is needed, Lily loops one in. If it’s an emergency, Lily conferences 911 and stays on the line.

---

## 🛠 Tech Stack
Lily is built for extreme low-latency and maximum accessibility over standard phone lines (PSTN):
- **Telephony & SMS**: Twilio (Voice WebSockets, SMS, Conferencing)
- **Speech-to-Text**: Deepgram (sub-second streaming transcription)
- **The Brain (LLM)**: Anthropic Claude Sonnet 4.6 (Tool-calling, reasoning, empathy)
- **Text-to-Speech**: ElevenLabs (Ultra-low latency human-like voice)
- **Rules Engine**: Pure Python (Deterministic ACOG logic, bypassing LLM hallucinations)
- **Memory**: Pinecone (Vector embeddings for long-term patient context)
- **Database**: PostgreSQL / SQLite (Patient records, session vitals, standing orders)
- **Backend Framework**: Python FastAPI

## 🚀 Architecture Overview
The system relies on a strict separation of concerns between **Conversation** and **Triage**:
1. **The LLM** extracts symptoms from the conversation (e.g., `["headache", "systolic_bp: 148"]`).
2. **The Rules Engine** evaluates the symptoms deterministically, ensuring that medical escalations are safe, auditable, and not subject to AI hallucination.
3. Cases are categorized into three tiers:
   - **HANDLE**: Lily resolves the issue through education and comfort.
   - **HAND-UP**: A volunteer physician is pinged via a dashboard and has 20 minutes to respond.
   - **HAND-OFF**: A severe emergency requiring an immediate 3-way call to 911/L&D.

## 💻 Getting Started (Hackathon Setup)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Environment Variables
Copy `.env.example` to `.env` and fill in your keys:
```env
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
ANTHROPIC_API_KEY=
DEEPGRAM_API_KEY=
ELEVENLABS_API_KEY=
```

### 3. Run the Database
```bash
docker-compose up -d
```

### 4. Start the Application
```bash
uvicorn src.main:app --reload --port 8000
```
*(For Twilio to reach your local server, expose port 8000 using ngrok)*

---
*Built for HackDavis 2026. Because geography should not determine survival.*
