from typing import List, Dict, Optional, Literal
from dataclasses import dataclass
from src.core.triage.rules_engine import RULES

@dataclass
class TriageInput:
    symptoms: List[str]
    vitals: Dict[str, float]
    gestational_weeks: Optional[int]
    postpartum_days: Optional[int]
    flags: List[str]

@dataclass
class TriageOutput:
    tier: Literal["handle", "hand_up", "hand_off"]
    reason: str
    triggered_rules: List[str]
    uncertainty: bool
    next_action: str

def classify_case(triage_input: TriageInput) -> TriageOutput:
    """
    Evaluates extracted symptoms against deterministic ACOG rules.
    This prevents LLM hallucinations in critical medical decisions.
    """
    highest_tier = "handle"
    triggered_rule_ids = []
    citations = []

    # Map tier severity
    tier_weight = {"handle": 1, "hand_up": 2, "hand_off": 3}

    v = triage_input.vitals or {}
    s = triage_input.symptoms or []
    f = triage_input.flags or []

    for rule in RULES:
        if rule.fires_when(v, s, f):
            triggered_rule_ids.append(rule.id)
            citations.append(rule.cite)
            if tier_weight[rule.tier] > tier_weight[highest_tier]:
                highest_tier = rule.tier

    reason = "Routine case, handled safely."
    next_action = "Provide comfort and education."
    uncertainty = False

    if highest_tier == "hand_off":
        reason = f"Emergency symptoms detected: {', '.join(citations)}"
        next_action = "Initiate 911 conference and emergency contacts."
    elif highest_tier == "hand_up":
        reason = f"Clinical review required: {', '.join(citations)}"
        next_action = "Route to physician queue (20 min SLA)."
        
    if "maria_unable_to_classify" in f:
        uncertainty = True

    return TriageOutput(
        tier=highest_tier,
        reason=reason,
        triggered_rules=triggered_rule_ids,
        uncertainty=uncertainty,
        next_action=next_action
    )
