# Lily — Project Abstract
**HackDavis 2026**

---

The United States has a maternal mortality rate of roughly **22 deaths per 100,000 live births** — more than triple the rate of peer wealthy nations. Black women die at nearly three times the rate of white women, a gap that holds even when controlling for income and education. The counties losing maternity care fastest — the Mississippi Delta, the Black Belt, tribal lands, the Rio Grande Valley — are the ones America has long been willing to let crumble. In these maternity deserts, the difference between a survivable complication and a preventable death is often whether someone with clinical knowledge and genuine care can be reached in the next four hours.

**Lily is a phone number any mother can call.** No app. No smartphone. No data plan. No English required. Any phone, including a flip phone, including with zero data left in the month.

But Lily is more than a triage line. She is the medical expert, the doula, the navigator, the aunt, and the trusted friend that women in maternity deserts have never had access to — and she remembers everything. Every conversation builds on the last. Every detail Maria shares — her symptoms, her home life, her fears, what her doctor said at her last visit, whether she has a BP cuff — becomes part of Lily's growing picture of Maria. Memory is the foundation of real care. Lily is built on it.

When Maria calls, Lily meets her where she is. If she needs a breathing exercise at 3am, Lily coaches her through it. If she needs to understand what "effaced" means before tomorrow's appointment, Lily explains it in plain language. If she needs someone to listen while she cries, Lily listens. If she needs help finding a WIC office, Lily finds it. If she needs to know whether what she's feeling is normal, Lily tells her honestly.

And when something is wrong — when the symptoms cross a threshold, when the numbers are alarming, when Lily's clinical knowledge tells her this cannot wait — **Lily acts.**

---

## The Three Tiers

Lily's triage architecture runs on three tiers, governed by a rules engine grounded in ACOG's published Urgent Maternal Warning Signs:

### HANDLE
Lily manages the case herself. Comfort coaching, evidence-based self-care, education, navigation, and — where a doctor has previously written a standing order for this patient — activation of that protocol.

### HAND-UP
The case has a clinical question Lily cannot answer alone. Lily routes to a queue of volunteer physicians who review a structured case packet and respond within 20 minutes. Lily calls Maria back with the doctor's decision. If no doctor responds in time, the system auto-escalates — **Maria is never left waiting by a silent queue.**

### HAND-OFF
The case is an emergency. Lily stays on the line, conferences in 911 and the nearest L&D, delivers a structured SBAR handoff, texts Maria's emergency contact, and walks Maria through what to tell the paramedics when they arrive. **She does not leave her.**

---

The companion relationship does not pause between calls. Lily checks in proactively at the highest-risk windows across pregnancy and the first twelve months postpartum — the period when most pregnancy-related deaths actually occur and when the healthcare system most aggressively disengages.

Every design choice in Lily is an ethical commitment:

| Design Choice | Reason |
|---|---|
| Voice over apps | The universal interface is the one she already trusts |
| SMS-based vitals over cloud sync | Her data plan ran out |
| Deterministic rules over opaque AI judgment | The women whose lives depend on this deserve transparency |
| Warm handoffs over automated rerouting | Someone should stay with her |
| Full record returned to Maria by SMS after every call | Most health tech extracts data from underserved women and gives them nothing back |

---

> *Geography should not determine survival. Lily is the lowest-tech possible safety net — a phone number, any phone, any language, free — for the mothers America has decided it can lose.*
