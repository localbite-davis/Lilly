# 🏁 Hackathon Task Delegation: 4-Person Split

To move as fast as possible without stepping on each other's toes, the backend and frontend work is divided into four distinct roles. You should assign one person to each role.

---

## 🎧 Role 1: Voice Pipeline Lead (Twilio & Streaming)
**Your Goal:** Make the phone call sub-second and reliable.
**Working Directory:** `src/api/routes/` and `src/services/`

**Milestones:**
- [ ] **Hour 2:** Set up the Twilio number. Create an "Echo Loop" using Deepgram STT and ElevenLabs TTS (call the number, it repeats what you say).
- [ ] **Hour 6:** Replace the "Echo Loop" with Claude. Log the latency (target < 800ms).
- [ ] **Hour 12:** Implement "Barge-in" (if Maria interrupts Lily, stop the TTS stream).
- [ ] **Hour 18:** Implement Twilio outbound calls (so Lily can call Maria back) and a mocked 3-way conference call.

---

## 🧠 Role 2: LLM & Memory Lead (The Brain)
**Your Goal:** Give Lily empathy, strict adherence to tools, and a memory.
**Working Directory:** `src/core/agent/` and `src/core/memory/`

**Milestones:**
- [ ] **Hour 2:** Get the Claude Sonnet 4.6 API working via a CLI test (no voice needed).
- [ ] **Hour 6:** Write the System Prompt (`prompts.py`). Ensure Claude calls the `log_symptom` and `log_vitals` tools properly.
- [ ] **Hour 12:** Implement the verbal login flow ("Hi, what's your name and due date?").
- [ ] **Hour 18:** Write the `end_session` summarizer. After a call ends, Claude should write a 3-sentence summary and save it to Pinecone/Neon DB.

---

## ⚕️ Role 3: Rules Engine & Triage Lead (The Safety Net)
**Your Goal:** Build the deterministic logic so the LLM doesn't make medical decisions.
**Working Directory:** `src/core/triage/` and `src/workers/`

**Milestones:**
- [x] **Hour 2:** Build the core logic in `rules_engine.py`. Write 3 pytest tests to ensure ACOG rules trigger correctly.
- [x] **Hour 6:** Expand to all 9 core test cases (e.g. BP 148/94 + headache -> HAND-UP). Expose `classify_case` as a tool for the LLM.
- [x] **Hour 12:** Build the Neon DB persistent timer for the 20-minute SLA (`ticker.py`).
- [x] **Hour 18:** Wire the auto-escalation so that if 20 minutes pass, it automatically triggers an outbound call to Maria.


---

## 💻 Role 4: Dashboard & Demo Lead (The Doctor Portal)
**Your Goal:** Give the doctors a UI, and make sure the 90-second demo is flawless.
**Working Directory:** React frontend (create a new folder) and `src/main.py` endpoints

**Milestones:**
- [ ] **Hour 2:** Scaffold a basic React dashboard with hardcoded data.
- [ ] **Hour 6:** Wire the dashboard to `/api/queue` to pull live data from Role 3's triage engine.
- [ ] **Hour 12:** Implement the 3 decision buttons: `Approve`, `Escalate to L&D`, and `Send Note`.
- [ ] **Hour 18:** **DEMO PREP.** Seed the database with a fake patient ("Maria", 32 weeks, has a BP cuff). Prepare the SMS text for the wearable fallback.

---

### 🚨 The "Gate" Rule
Do not merge into the next block of hours until everyone has finished their current block. At **Hour 18**, everyone stops coding new features and you do your first end-to-end dry run of the 90-second demo script.
