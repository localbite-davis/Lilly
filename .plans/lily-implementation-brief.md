# Lily — Full Implementation Brief
**HackDavis 2026** · Internal team use only

Contains all design decisions, workflow, architecture, stack choices, and role assignments.

---

## Table of Contents

1. [What We Are Building](#1-what-we-are-building)
2. [Core Design Decisions](#2-core-design-decisions)
3. [Lily's Capabilities](#3-lilys-capabilities)
4. [The Three Tiers](#4-the-three-tiers)
5. [Full Call Workflow](#5-full-call-workflow)
6. [Technical Stack](#6-technical-stack)
7. [Scope Discipline for the Hackathon](#7-scope-discipline-for-the-hackathon)
8. [The Demo Script](#8-the-demo-script-90-seconds)
9. [Team Roles](#9-team-roles)
10. [The Pitch](#10-the-pitch-4-minutes)
11. [Safety and Ethics Statements](#11-safety-and-ethics-statements)

---

## 1. What We Are Building

Lily is a voice AI companion accessible via a standard phone call — no app, no internet, no data plan required on the caller's side.

She serves pregnant women and new mothers in US maternity deserts (counties with no OB hospital, no OB, and no birth center) from whenever they first call through 12 months postpartum.

She is simultaneously:
- A medical-grade triage system with a deterministic rules engine
- A knowledgeable companion who gives real, practical help
- A memory keeper who builds a living picture of each patient
- A care coordinator who warm-handoffs to doctors and emergency services
- A proactive check-in system that reaches out at high-risk windows

> **The fundamental design principle:** Lily is an aunt who happens to have medical expertise. The medical expertise does not make her cold or clinical. The warmth does not make her medically vague. Both are always present. Memory is the thread that ties them together.

---

## 2. Core Design Decisions

> **Read before coding anything.**

### 2.1 Phone Call, Not App
- Lily is accessed via a Twilio phone number
- The caller needs zero data, zero apps, zero internet
- Internet lives on our servers, not on her phone
- **Latency budget: full STT → LLM → TTS loop under 800ms** or the call feels broken. This is the single highest risk. Derisk it first. Get a working voice loop before any other feature.

### 2.2 Caller ID as Primary Key
- When a call arrives, the first action is always a caller ID lookup
- If found: load full context, greet by name, proceed
- If not found: offer registration or verbal login flow

### 2.3 Verbal Login for Unknown Numbers
- Maria may call from a borrowed phone, sister's phone, or with a dead battery
- Lily asks: name + due date or baby's birthday
- Match against records. Confirm with one low-stakes detail.
- If no match: treat as new caller, offer registration

### 2.4 Registration is Conversational, Not a Form
- No pre-registration required. Maria can dial cold.
- Lily collects intake data through natural conversation
- **Minimum viable intake:** name, due date or baby DOB, language preference, callback number, emergency contact name + number, and whether she has a home BP cuff
- Consent is explicit and spoken. Lily explains what is stored, what is shared (only with treating doctors and emergency services on active cases), and what is never shared (insurance, ICE, police, custody). Maria verbally confirms.

### 2.5 Memory is the Product
- Every call enriches Maria's record
- Lily never asks the same question twice if she can help it
- Memory includes: medical facts, life context, emotional state trends, support system changes, appointment history, what doctors have said, what standing orders exist, what equipment she has at home, what has and hasn't worked for her
- When Lily references past context it feels like a friend remembering, not a system retrieving. Use natural language: *"Last week you mentioned..."* not *"According to your record..."*

### 2.6 The Line Lily Does Not Cross

| Lily CAN | Lily CANNOT |
|---|---|
| Comfort coach, educate, navigate resources | Diagnose |
| Validate and listen | Prescribe anything new |
| Give evidence-based self-care suggestions | Adjust existing medication dosages |
| Explain medical information in plain language | Tell Maria not to seek care when she asks if she should |
| Activate standing orders a doctor explicitly wrote | Make the final triage classification on a borderline case |
| Surface past doctor recommendations | Override the rules engine |

> **Rule of thumb:** Anything a well-informed doula, a knowledgeable aunt, or a nurse-line script would clear in 10 seconds is fine. Anything requiring a medical license is not.

### 2.7 The Rules Engine is Deterministic
- The LLM owns the conversation. **The rules engine owns the final tier classification.**
- This is non-negotiable. It makes the system auditable, defensible, and trustworthy.
- The rules engine accepts both numerical inputs (when available) AND symptom-cluster inputs (when no numbers). Either can independently trigger escalation.
- If the rules engine fires on HIGH, no LLM output overrides it. The call goes to emergency services. Period.
- Rules are grounded in ACOG's Urgent Maternal Warning Signs (publicly available — cite them by name in the pitch).

### 2.8 Doctor Review is System-Managed, Not Patient-Managed
- When a case is hand-up, Maria waits. She does not call back. She does not do anything.
- The system owns the timer and the auto-escalation. Putting burden on a stressed patient is a design failure.
- 20-minute SLA for doctor response
- If no response: auto-escalate to hand-off (emergency tier), system calls Maria back with instructions and ER address

### 2.9 Lily Stays on the Line During Emergencies
- High-tier calls do not end with *"call 911"*
- Lily stays with Maria, conferences in 911, delivers the SBAR, contacts her emergency contact, calls ahead to L&D, and coaches Maria through what to say to paramedics
- **This is the detail that makes the project human**

### 2.10 The Year-Long Companion Relationship
- Lily does not disappear after the birth
- Proactive check-ins are scheduled at: first week postpartum, 2 weeks (most missed warning signs surface here), 6 weeks, 3 months, 6 months, 9 months, 12 months
- Maria can also call anytime
- EPDS postpartum depression screening is woven into postpartum check-ins conversationally, not as a survey read-aloud
- The relationship built during low-stakes calls is what makes Maria pick up the phone when something is actually wrong

---

## 3. Lily's Capabilities

### 3.1 Physical Comfort Coaching *(in-call, real-time)*
- Breathing techniques: 4-7-8, box breathing, paced breathing for early contractions
- Position guidance for back pain, hip pain, swelling (left-side lie, pillow placement)
- Grounding techniques for anxiety and panic: 5-4-3-2-1 sensory
- Hydration and nutrition prompting
- Gentle movement coaching: pelvic tilts, cat-cow, stretching
- Warm/cold compress guidance
- Nipple care, latch troubleshooting *(breastfeeding is a massive unmet need — doulas charge $200/hr for this)*
- Newborn soothing techniques: 5 S's, swaddling, paced feeding

### 3.2 Emotional Support
- Active listening without redirecting to solutions prematurely
- Normalizing common pregnancy and postpartum experiences
- Distinguishing baby blues from PPD in conversation
- Helping Maria articulate what she actually needs
- Coaching hard conversations (partner, family, employer)
- Flagging when emotional state crosses into clinical territory and routing appropriately, never making Maria feel surveilled

### 3.3 Education on Demand
- Plain-language explanation of any pregnancy/postpartum term
- What to expect at each type of appointment
- What her test results mean (in general terms, not diagnosis)
- Normal vs. concerning symptom ranges for each gestational stage
- Medication safety questions (general: *"is Tylenol ok while breastfeeding"* — not dosage adjustment for existing conditions)
- Newborn care basics: sleep, feeding, umbilical cord, jaundice

### 3.4 Logistical and Navigational Help
- WIC enrollment and office locations
- Free breast pump through insurance (most plans cover 100%)
- Medicaid pregnancy coverage extension
- FMLA paperwork guidance
- SNAP / food assistance
- Local doula collectives and maternal support groups
- Medicaid non-emergency medical transportation *(huge — most patients in maternity deserts don't know this exists)*
- Baby supply closets and donation programs
- Appointment prep: what questions to ask
- Appointment debrief: what did they say, anything unclear

### 3.5 Standing Order Activation
- If Dr. Chen previously wrote: *"patient may use X for Y situation"* and that situation is present, Lily surfaces it
- Lily **never** invents a protocol. She surfaces existing authorization.
- If no standing order exists for the situation: hand-up tier
- Doctors write standing orders via the dashboard during quiet moments, not only in response to active cases

### 3.6 Memory as Active Care

> *"Last week you mentioned the baby was kicking less in the evenings — has that gotten better or worse?"*
>
> *"You told me your mom was flying in Tuesday — is she there?"*
>
> *"Three weeks ago you said you were dreading the postpartum visit — how did it go?"*
>
> *"You haven't mentioned sleep in a while. How is it?"*

This is not a feature. This is the product. Everything else enables this.

---

## 4. The Three Tiers

> **The LLM gathers information conversationally. The rules engine classifies. Never the other way around.**

### Tier 1 — HANDLE *(Lily manages autonomously)*

**Triggers** — all of the following must be true:
- No ACOG Urgent Maternal Warning Signs present
- BP within normal range if a reading is available (< 140 systolic AND < 90 diastolic)
- No severe symptom cluster
- Mood/emotional concern within normal new-parent range
- Case involves common pregnancy/postpartum discomfort: nausea, fatigue, mild swelling, Braxton Hicks, sleep disruption, breastfeeding difficulty, mild anxiety, general questions, logistical help

**What Lily does:**
- Provides comfort coaching, education, navigation as appropriate
- Activates relevant standing orders if they exist and apply
- Logs full conversation to Maria's record
- Schedules follow-up SMS for next morning: *"How are you feeling?"*
- Tells Maria when to call back: *"If the headache gets worse or you start seeing spots, call me right away."*

**What Lily does not do:**
- Prescribe or recommend anything new
- Diagnose
- Dismiss symptoms she logged — they inform future calls

---

### Tier 2 — HAND-UP *(Voluntary doctor review required)*

**Triggers** — any one of the following is sufficient:

| Category | Trigger |
|---|---|
| Numerical | BP 140–159 systolic OR 90–109 diastolic |
| Numerical | HR > 120 (wearable or self-report with symptoms) |
| Numerical | SpO₂ < 94% (wearable) |
| Symptom cluster | 2+ ACOG Urgent Warning Signs without severe features |
| Mental health | EPDS score 10–12 (moderate range) |
| Mental health | Expressed inability to cope, persistent intrusive thoughts, isolation, feeling unsafe |
| Uncertainty | Lily cannot confidently classify the case with available info |

**What Lily does:**
1. Tells Maria calmly what is happening and the timeline: *"I want a doctor to take a quick look at this. I'll have them review your case and call you back within 20 minutes."*
2. Ends the call gracefully.
3. Sends Maria an SMS immediately with case summary, callback window, and nearest ER address as fallback.
4. Builds and pushes a structured case packet to the doctor queue:
   - Patient name, gestational/postpartum stage
   - All vitals reported (numerical and symptom-based)
   - ACOG warning signs present with timestamps
   - Lily's tentative assessment
   - Specific forced-choice question for the doctor
   - Three action buttons: **[Approve Lily's rec]** · **[Escalate now]** · **[Add note]**
5. Starts a 20-minute server-side countdown.

**Auto-escalation** *(system-managed, not patient-managed)*:
- If no doctor responds within 20 minutes → Lily calls Maria back automatically
- *"I wasn't able to reach a doctor in time. To be safe, please head to the nearest ER now. I'm texting you the address and calling ahead to let them know you're coming."*
- System calls the ER, delivers SBAR, texts emergency contact

**When doctor responds:**
- Lily calls Maria back within 2 minutes
- Delivers decision in her own voice, in Maria's language
- Conferences in facility if escalation is recommended
- Texts Maria: visit summary, doctor's note, address
- Texts emergency contact if escalation

---

### Tier 3 — HAND-OFF *(Emergency services activated)*

**Triggers** — any one of the following is sufficient:

| Category | Trigger |
|---|---|
| Numerical | BP ≥ 160 systolic OR ≥ 110 diastolic |
| Severe symptoms | Visual changes + headache (any severity) |
| Severe symptoms | Chest pain or shortness of breath |
| Severe symptoms | Seizure or loss of consciousness |
| Severe symptoms | Heavy vaginal bleeding (soaking > 1 pad/hour) |
| Severe symptoms | Decreased fetal movement at or after 36 weeks |
| Severe symptoms | Signs of stroke: face drooping, arm weakness, speech difficulty |
| Severe symptoms | Severe epigastric / RUQ pain |
| Mental health | Active suicidal ideation with plan or intent |
| Mental health | Expressed immediate danger to self or baby |
| Uncertainty override | Cannot classify AND Maria sounds in acute distress → always escalate |

**What Lily does:**
1. Does not pause to verify. Acts immediately.
2. Tells Maria calmly and directly: *"Maria, what you're describing needs emergency care right now. I'm going to stay on the line with you while we get you help. Don't hang up."*
3. Initiates a three-way call with 911.
4. Delivers a structured SBAR when dispatch picks up: *"I'm calling on behalf of [name], [gestational stage] pregnant, at [address on file]. She is reporting [symptoms]. Please dispatch."*
5. While on hold / awaiting dispatch: stays with Maria, keeps her calm, asks her to unlock the front door, tells her what to say to paramedics.
6. In parallel (server-side, automatic):
   - Texts Maria's emergency contact: name, what's happening, address
   - Identifies nearest L&D, calls intake, delivers SBAR with ETA
   - Sends Maria's record summary to the receiving facility
7. Stays on the line until 911 confirms dispatch or EMTs arrive.
8. Next morning: Lily calls to follow up.

**What Lily does NOT do at this tier:**
- Give specific medical advice ("take this medication")
- Allow the LLM to second-guess the rules engine classification
- End the call and leave Maria alone

---

## 5. Full Call Workflow

### Call Arrives

```
Twilio receives call → Server fires immediately → Caller ID lookup

  FOUND:                              NOT FOUND:
  Load full patient context           Lily answers generically
  Greet by name                       ↓
  Proceed to Conversation Loop        "Have we talked before?"
                                      ↓
                                  YES → Verbal login (name + due date)
                                        Match → load context
                                        No match → treat as new caller
                                  NO  → Registration Flow
```

### Registration Flow

Lily explains the service and asks for consent in two sentences. She explains what is stored, what is shared (only treating doctors and emergency services on active cases), and what is never shared (insurance, ICE, police, custody).

**If no consent:** Lily can still help this call anonymously, but cannot remember for next time. Offer again at the end of the call.

**If consent given, collect conversationally:**
- First name (and nickname if preferred)
- Currently pregnant or recently given birth?
- Due date (if pregnant) or baby's birthday (if postpartum)
- Language preference
- Best callback number
- Emergency contact: name and number
- Home blood pressure cuff? (yes/no)
- Wearable device for heart rate? (yes/no)

Save record → confirm back in one sentence → transition directly into: *"So what's going on today?"*

### Conversation Loop

```
Maria speaks
    → STT transcribes
    → LLM processes
    → Tool calls fire (memory write, symptom log, vitals log, etc.)
    → LLM generates response
    → TTS speaks
    → Maria hears
```

**Hard technical constraint: under 800ms end-to-end.**

**LLM's job during conversation:**
- Be Lily: warm, knowledgeable, remembering, unhurried
- Work through relevant clinical questions naturally (not as a checklist — as a friend who happens to know medicine)
- Call tools to log everything structured in the background
- Ask the BP question when relevant: *"Do you have your cuff handy? Can you take a reading? I'll wait."*
- Ask about wearable data if she has one
- Check for incoming vitals SMS if wearable is paired

### Wearable Sync

```
Wearable → Bluetooth → phone → SMS to Lily's Twilio number
Format: "HR:88 SpO2:97 ts:1715286000"
Server polls for vitals SMS during active session
LLM tool: read_vitals_sms() → returns latest reading if present
```

> **In demo:** teammate manually sends this SMS mid-call to simulate.

### BP Cuff Self-Report

- **If Maria has a cuff:** ask her to take a reading, wait, log it.
- **If no cuff:** Lily switches to symptom-cluster triage. Structured questions: headache (location, severity, duration), visual changes, hand/face swelling (new or changed), epigastric pain, fetal movement, dizziness. Lily never pretends to know the BP — she escalates on the symptom pattern because she cannot confirm the BP.

> **Pitch framing:** *"Lily escalates on uncertainty, not only on confirmed numbers. That's the safer design."*

### Classification

After gathering sufficient information, LLM calls:

```python
classify_case(symptoms=[], vitals={}, history={}, flags=[])
```

This is a **pure Python rules function** — no LLM inference inside it. Returns:

```python
{
    "tier": "handle" | "hand_up" | "hand_off",
    "reason": str,
    "uncertainty": bool,
    "next_action": str
}
```

### Between Calls — Proactive Check-ins

**During pregnancy:**
- Weekly check-in: brief, conversational, mood + physical update
- Appointment follow-up: 24hrs after any appointment she mentioned

**Postpartum schedule:**

| Timing | Focus |
|---|---|
| Day 3 | Emotional check-in, hemorrhage warning signs, baby feeding, sleep |
| Week 1 | EPDS screening woven in conversationally |
| Week 2 | EPDS again, physical recovery, infection/DVT warning signs |
| Week 6 | Full check-in (mirrors postpartum visit topics) |
| Months 3, 6, 9, 12 | Mood, physical recovery, parenting support, resource navigation |

Each proactive call references last conversation memory, builds on the relationship, and logs to record. Maria can redirect or end it anytime.

---

## 6. Technical Stack

### Telephony
| Component | Tool |
|---|---|
| Voice (programmable, media streams) | Twilio Voice |
| SMS (vitals ingest, patient summaries, emergency contact) | Twilio SMS |
| Three-way calling (warm handoffs) | Twilio Conference |
| Outbound calls (proactive check-ins, callbacks) | Twilio Programmable Outbound |

### Speech-to-Text
- **Primary:** ElevenLabs Scribe (streaming, with WebRTC VAD)
- **Confidence scores:** low confidence on a critical symptom word triggers Lily to confirm: *"I want to make sure I heard you right — did you say [word]?"*

### LLM
- **Primary:** `claude-sonnet-4-6` — low TTFT, strong tool-calling
- **Validator:** OpenBioLLM-70B (Saama AI, Llama 3-based) — ground-truth clinical validator for medical claims
- System prompt defines Lily's personality, capabilities, limits, and available tools
- Tool-calling handles all structured actions (memory write, classification call, vitals ingest, etc.)
- LLM is stateless between turns — full conversation history + patient context is passed on every call

### Text-to-Speech
- **Primary:** ElevenLabs Flash v2.5 (lowest latency, streaming)
- One consistent voice for Lily across all calls
- Optimize for latency over voice quality in v1

### Rules Engine
```python
# Pure Python — no LLM, no inference, fully deterministic
def classify_case(symptoms: list, vitals: dict, history: dict, flags: list) -> dict:
    ...
    return {
        "tier": "handle" | "hand_up" | "hand_off",
        "reason": str,
        "uncertainty": bool,
        "next_action": str
    }
```
- ~50–80 lines total
- Numerical thresholds + symptom cluster thresholds from ACOG
- Tested independently of the LLM pipeline
- Auditable by any clinician

### Database Schema

| Table | Key Fields |
|---|---|
| `patients` | id, phone, name, due_date, baby_dob, language, emergency_contact, has_bp_cuff, has_wearable |
| `conversations` | id, patient_id, start_time, end_time, tier_reached, summary, flags_for_next_call |
| `symptoms_log` | id, conversation_id, symptom, value, source (self_report/sms_vitals/wearable), timestamp |
| `vitals_log` | id, patient_id, bp_systolic, bp_diastolic, hr, spo2, source, timestamp |
| `standing_orders` | id, patient_id, doctor_id, condition, intervention, created_at, active |
| `doctor_queue` | id, patient_id, conversation_id, case_packet, status (pending/claimed/responded/escalated), response |
| `doctors` | id, name, npi, specialty, active |

### Doctor Dashboard
- React frontend, single view
- Case queue: cards auto-refresh every 15 seconds
- Each card: patient name, gestational stage, structured packet, countdown timer, three action buttons
- One free-text field for doctor note
- Standing order creation form (simple: condition + intervention)

### Backend
- Python + FastAPI
- WebSocket for Twilio media streams
- Async throughout (latency-critical)
- Twilio webhooks: incoming call, SMS received

### Hosting *(hackathon)*
- Cloudflare tunnel or ngrok for local tunnel to Twilio webhooks
- fly.io / Railway free tier for quick deploy

---

## 7. Scope Discipline for the Hackathon

### Build This Weekend ✓
- [ ] Twilio voice number that answers with Lily's voice
- [ ] Caller ID lookup + context loading
- [ ] New caller registration flow (conversational)
- [ ] Verbal login for unknown numbers
- [ ] Conversation loop: STT → LLM → TTS under 800ms
- [ ] Memory enrichment during every call
- [ ] BP cuff self-report flow
- [ ] Simulated wearable vitals via SMS
- [ ] Rules engine: all three tiers with numerical + symptom inputs
- [ ] Handle tier: comfort coaching + standing order surfacing
- [ ] Hand-up tier: case packet generation, doctor queue push, 20-minute countdown, auto-escalation failsafe
- [ ] Hand-off tier: 911 conference, SBAR delivery, emergency contact SMS, L&D call-ahead
- [ ] Doctor dashboard: queue view, case cards, three-button action
- [ ] Patient SMS after every call: summary + next steps
- [ ] Emergency contact SMS when tier 2 auto-escalates or tier 3 fires
- [ ] Demo script: one call that starts as comfort coaching and escalates to hand-up mid-call

### Mock for the Demo *(show it exists, don't build it)*
- Proactive check-in scheduling (show one scheduled future call in the DB or dashboard)
- Standing orders written by doctor (hardcode one for demo patient)
- Facility directory (hardcode Mercy Regional)

### Pitch as Next Steps *(don't build, do mention)*
- Spanish language support
- Real wearable Bluetooth pairing
- Real facility directory + on-call schedule integration
- NPPES NPI verification for doctor signup
- HIPAA compliance certification *(say: designed for, not certified)*
- EPDS formal postpartum depression screening module

---

## 8. The Demo Script *(90 seconds)*

| Role | Person |
|---|---|
| Maria (caller) | Person A — on phone, calling the Lily number |
| Doctor dashboard | Person B — laptop visible to judges |
| Server / logs | Person C — monitors in background, invisible to judges |
| Presenter | Narrates one sentence before the call starts |

### Setup *(10 seconds)*
> *"Maria is 32 weeks pregnant in rural Mississippi. The nearest OB closed in 2018. She's had a headache for two hours and her hands feel puffy. She's not sure if it's worth the 90-minute drive. She calls the number a doula gave her."*

### The Call *(60 seconds)*
1. Maria calls. Lily greets her by name *(she's called before)*.
2. Lily asks what's going on. Maria describes the headache, swelling.
3. Lily asks warm follow-up questions. Maria mentions no visual changes.
4. Lily asks: *"Do you have your cuff handy?"* Maria takes a reading: **"148 over 94."**
5. Person C sends the wearable vitals SMS mid-call (`HR:102`). Lily says: *"I also see your heart rate is a little elevated from your device — that's useful."*
6. Lily says: *"Maria, I want a doctor to look at this before I give you a recommendation. I'll call you back within 20 minutes."*

### Doctor Dashboard *(15 seconds)*
- Person B turns laptop to judges.
- Case card has appeared: Maria's packet, specific question, 20-minute timer counting down.
- Person B taps **[Escalate to L&D immediately]**.

### Callback *(15 seconds)*
> *"Maria, I heard back from Dr. Chen. She wants you to go to Mercy Regional tonight. I'm texting you and your sister the address right now. They know you're coming."*

### Close *(5 seconds)*
> *"No app. No data plan. Any phone. That was Lily."*

---

## 9. Team Roles

### Role 1 — Voice Pipeline Lead
**Owns:** Twilio setup, STT integration, TTS integration, latency

> **First task:** Get a working voice loop (Twilio answers → STT → echo back with TTS) within the first 2 hours. Everything else depends on this. Do not move to features until latency is under 800ms.

**Key tasks:**
- Twilio programmable voice: incoming call webhook
- ElevenLabs Scribe streaming STT
- ElevenLabs Flash TTS streaming back through Twilio
- Twilio Conference wiring for three-way calls
- Twilio outbound call trigger (for callbacks)
- Twilio SMS ingest webhook (for vitals)
- Streaming architecture: WebSocket

**Dependencies others need from you:**
- Working call handler they can hook their LLM logic into
- SMS ingest endpoint they can poll from

---

### Role 2 — LLM + Memory Lead
**Owns:** Lily's personality, system prompt, tool definitions, memory schema, knowledge graph read/write, conversation logic

**Key tasks:**
- Design Lily's system prompt: who she is, what she can/can't do, tone, the line she doesn't cross
- Define all LLM tools:
  - `get_patient_context(phone_number)`
  - `register_patient(name, due_date, ...)`
  - `log_symptom(symptom, value, source)`
  - `log_vitals(bp_systolic, bp_diastolic, hr, spo2, source)`
  - `read_vitals_sms(session_id)`
  - `classify_case(symptoms, vitals, history)`
  - `get_standing_orders(patient_id)`
  - `end_session(summary, flags, next_checkin)`
- Database schema design + SQLite setup
- Memory enrichment logic
- Verbal login matching logic
- Conversation history management

**Lily's personality notes for the prompt:**
- She is warm but not saccharine
- She remembers everything and references it naturally
- She does not read from checklists — she asks follow-up questions based on what Maria just said
- She never says "I am an AI" unless directly asked
- She never rushes a caller
- She is the most knowledgeable person Maria has ever talked to about her pregnancy, and also the most available

---

### Role 3 — Rules Engine + Triage Lead
**Owns:** `classify_case()` function, all tier logic, auto-escalation timer, doctor queue management, failsafe systems

**Key tasks:**
- Implement `classify_case()` as a pure Python function (no LLM calls inside it — deterministic only)
- Numerical thresholds from ACOG (see Section 4)
- Symptom cluster thresholds from ACOG
- Case packet builder: structured JSON for doctor queue
- Doctor queue database operations: push, claim, respond
- 20-minute countdown timer with auto-escalation trigger
- Auto-escalation: fires Lily outbound call to Maria
- Test every tier trigger independently before integrating

**Required test cases:**

| Input | Expected Tier |
|---|---|
| BP 148/94 + 2 symptoms | `hand_up` |
| BP 162/108 | `hand_off` |
| No BP + 2 warning sign symptoms | `hand_up` |
| No BP + 0 symptoms + routine question | `handle` |
| No BP + severe symptom cluster | `hand_off` |
| Timer expiry with no doctor response | auto-escalate |

---

### Role 4 — Dashboard + Demo Lead
**Owns:** Doctor dashboard UI, demo script execution, pitch deck, SMS outputs, README

**Key tasks:**

*Dashboard:*
- React app, single view
- Case queue: cards auto-refresh every 15 seconds
- Each card: patient name, gestational stage, structured packet, countdown timer, three action buttons
- One free-text field for doctor note
- Standing order creation form (condition + intervention)
- Connect to backend API for queue poll and action submission

*SMS outputs:*
- Patient summary SMS after every call
- Emergency contact SMS on tier 2 auto-escalate and tier 3
- Formatting: plain text, short, clear, with address when relevant

*Demo:*
- Own the demo script (Section 8). Practice it. Time it. Know every beat.
- Prepare the demo patient record in the database
- Prepare the hardcoded standing order for demo patient
- Prepare the wearable SMS to send mid-call
- Own the pitch deck (4–5 slides max: problem → solution → demo → why it's safe → what's next)

---

**Team size adjustments:**
- **3 people:** Merge Role 3 into Role 2. Rules engine is ~80 lines and can be written in an hour once the schema exists.
- **2 people:** Voice Pipeline + Dashboard / LLM + Rules. Cut proactive check-ins and standing orders from v1 demo entirely.

---

## 10. The Pitch *(4 minutes)*

### Minute 1 — The Problem
Open with a real composite story:
> *"In April 2023, a woman we'll call Maria gave birth in rural Mississippi. Three days later, at home, she had a seizure from postpartum eclampsia. The nearest OB hospital had closed in 2018. The ambulance took 47 minutes. She didn't make it."*

Then: 22 per 100,000. Triple peer nations. Black women at nearly 3× the rate — a gap that holds even at the highest income and education levels.

> *This is not a healthcare gap. It is a justice gap.*

### Minute 2 — The Solution
> *"We built a phone number. Not an app — a phone number. Any phone. No data. No English required. Maria dials. Lily answers. She already knows Maria — she's been talking to her since week 12. She knows whether Maria has a BP cuff. She knows the baby's name. She knows the headache was worse on Tuesday. Because Lily remembers everything."*

### Minute 3 — The Demo
Run the demo from Section 8. No narration needed during the call. The demo narrates itself.

### Minute 4 — Why It's Safe + What's Next
> *"Lily doesn't diagnose. She pattern-matches ACOG's published warning signs. Every escalation decision goes through a rules engine any clinician can read. And when she's uncertain, she doesn't guess — she routes to a human, every time, within 20 minutes, or she auto-escalates. The human is always in the loop.*
>
> *Next: Spanish, which covers the Rio Grande Valley, California's Central Valley, Florida's interior. Then real wearable pairing. Then a pilot with a rural maternal health organization."*

Close:
> *"Geography should not determine survival. Lily is a phone number. Any phone. Any language. Free. For the mothers America has decided it can lose."*

---

## 11. Safety and Ethics Statements
*For Devpost, README, and judge Q&A*

**On diagnosis:**
> *"Lily does not diagnose. She identifies symptom patterns that match ACOG's published Urgent Maternal Warning Signs and routes to the appropriate human or emergency service. The word 'diagnosis' does not appear in our codebase."*

**On HIPAA:**
> *"Lily is designed for HIPAA compliance — encrypted storage, minimum necessary data collection, explicit verbal consent at registration, no data shared with insurance or immigration. We are not certified. We would pursue certification as the first step before any real deployment."*

**On AI judgment:**
> *"The LLM handles conversation. The rules engine handles triage classification. They do not share that responsibility. The rules engine is deterministic Python, auditable by any clinician, grounded in ACOG guidelines. It cannot be overridden by the LLM."*

**On the companion relationship:**
> *"Maria can pause or stop her relationship with Lily at any time, verbally, in any call. Her data is hers — she receives a full record after every call by SMS. We do not share her data with employers, insurers, ICE, or any government agency. We tell her this at registration and periodically throughout the relationship."*

**On replacing clinicians:**
> *"Lily does not replace a clinician. She is the thing that gets Maria to a clinician. In a maternity desert, that gap — between a symptom at 2am and a clinician who can act on it — is where people die. Lily closes the gap. She does not replace what's on the other side of it."*
