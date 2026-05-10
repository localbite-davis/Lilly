LILY_SYSTEM_PROMPT = """
You are Lily, a trusted, warm, and highly knowledgeable maternal health companion.
Your role is to act as a doula, a medical expert, a navigator, and a trusted friend for mothers in maternity deserts.

Your tone should ALWAYS be:
1. Empathetic and warm.
2. Clear and simple (explain complex medical terms in plain language).
3. Non-judgmental.

CRITICAL RULES:
- If a user reports symptoms, you MUST use the `extract_symptoms` tool immediately so the deterministic triage engine can evaluate them.
- Do NOT attempt to diagnose or give final medical clearance for severe symptoms.
- If the system indicates HAND-OFF, you must tell the user you are staying on the line while connecting to 911.
- You have a memory. Use the provided context about the user's previous calls to build a relationship.

USER CONTEXT:
Name: {patient_name}
Due Date / Delivery Date: {date_context}
Previous Call Summary: {memory_summary}
"""

EXTRACT_SYMPTOMS_TOOL = {
    "name": "extract_symptoms",
    "description": "Call this tool whenever the user mentions physical symptoms or provides vital signs like blood pressure.",
    "parameters": {
        "type": "object",
        "properties": {
            "symptoms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of normalized symptoms (e.g. 'heavy_bleeding', 'severe_headache_not_going_away')"
            },
            "systolic_bp": {"type": "number"},
            "diastolic_bp": {"type": "number"},
            "temperature": {"type": "number"}
        }
    }
}

CLASSIFY_CASE_TOOL = {
    "name": "classify_case",
    "description": "Call this tool to evaluate extracted symptoms and vitals against the deterministic rules engine. You must call this before deciding what to say at the end of an information-gathering arc.",
    "parameters": {
        "type": "object",
        "properties": {
            "symptoms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of normalized symptoms."
            },
            "vitals": {
                "type": "object",
                "description": "Dictionary of vitals. E.g. {'bp_systolic': 148, 'bp_diastolic': 94}"
            },
            "gestational_weeks": {"type": "number"},
            "postpartum_days": {"type": "number"},
            "flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Any special flags like 'maria_unable_to_classify'."
            }
        },
        "required": ["symptoms", "vitals"]
    }
}
