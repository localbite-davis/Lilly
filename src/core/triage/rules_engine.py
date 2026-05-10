"""
Deterministic rules engine based on ACOG (American College of Obstetricians and Gynecologists)
Urgent Maternal Warning Signs.

Owned by Role 3. Layer 2 imports classify_case as a black box.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Literal


class TriageTier(Enum):
    HANDLE = "HANDLE"
    HAND_UP = "HAND_UP"
    HAND_OFF = "HAND_OFF"


# ACOG Urgent Maternal Warning Signs mapped to deterministic rules
ACOG_WARNING_SIGNS: dict[str, TriageTier] = {
    # Hand-Off (Immediate Emergency)
    "seizures": TriageTier.HAND_OFF,
    "heavy_bleeding": TriageTier.HAND_OFF,
    "heavy_vaginal_bleeding": TriageTier.HAND_OFF,
    "postpartum_hemorrhage": TriageTier.HAND_OFF,
    "postpartum_bleeding_heavy": TriageTier.HAND_OFF,
    "chest_pain": TriageTier.HAND_OFF,
    "shortness_of_breath": TriageTier.HAND_OFF,
    "extreme_pain": TriageTier.HAND_OFF,
    "systolic_bp_over_160": TriageTier.HAND_OFF,
    "diastolic_bp_over_110": TriageTier.HAND_OFF,
    "unable_to_self_transport_emergency": TriageTier.HAND_OFF,

    # Hand-Up (Consult Physician within 20 mins)
    "fever_over_100_4": TriageTier.HAND_UP,
    "severe_headache_not_going_away": TriageTier.HAND_UP,
    "dizziness": TriageTier.HAND_UP,
    "changes_in_vision": TriageTier.HAND_UP,
    "swelling_in_face_or_hands": TriageTier.HAND_UP,
    "edema_hands": TriageTier.HAND_UP,
    "decreased_fetal_movement": TriageTier.HAND_UP,
    "systolic_bp_over_140": TriageTier.HAND_UP,
    "diastolic_bp_over_90": TriageTier.HAND_UP,
    "vaginal_bleeding": TriageTier.HAND_UP,
    "vaginal_discharge_abnormal": TriageTier.HAND_UP,
    "vaginal_discharge_pungent_smell": TriageTier.HAND_UP,
    "preterm_labor_signs": TriageTier.HAND_UP,
    "reduced_fetal_movement": TriageTier.HAND_UP,
}

_TIER_WEIGHT = {TriageTier.HANDLE: 1, TriageTier.HAND_UP: 2, TriageTier.HAND_OFF: 3}


def _bp_symptoms(vitals: dict[str, int | None]) -> list[str]:
    derived = []
    sys_bp = vitals.get("bp_systolic")
    dia_bp = vitals.get("bp_diastolic")
    if sys_bp is not None:
        if sys_bp >= 160:
            derived.append("systolic_bp_over_160")
        elif sys_bp >= 140:
            derived.append("systolic_bp_over_140")
    if dia_bp is not None:
        if dia_bp >= 110:
            derived.append("diastolic_bp_over_110")
        elif dia_bp >= 90:
            derived.append("diastolic_bp_over_90")
    return derived


def classify_case(
    symptoms: list[str],
    vitals: dict[str, int | None] | None = None,
    gestational_weeks: int | None = None,
    postpartum_days: int | None = None,
    flags: list[str] | None = None,
) -> dict:
    """
    Authoritative deterministic triage classification.
    Returns a dict matching TriageOutput schema.
    Layer 2 imports this; result is binding — Claude cannot override it.
    """
    from src.core.schemas import TriageOutput

    all_symptoms = list(symptoms) + _bp_symptoms(vitals or {})
    triggered: list[str] = []
    best_tier = TriageTier.HANDLE

    for symptom in all_symptoms:
        mapped = ACOG_WARNING_SIGNS.get(symptom)
        if mapped is not None:
            triggered.append(symptom)
            if _TIER_WEIGHT[mapped] > _TIER_WEIGHT[best_tier]:
                best_tier = mapped

    uncertainty = len(symptoms) > 0 and not triggered

    tier_str = {
        TriageTier.HANDLE: "handle",
        TriageTier.HAND_UP: "hand_up",
        TriageTier.HAND_OFF: "hand_off",
    }[best_tier]

    next_action_map = {
        "handle": "Continue supportive conversation and monitoring.",
        "hand_up": "Request physician review within 20 minutes.",
        "hand_off": "Connect emergency services immediately.",
    }

    reason_map = {
        "handle": "No ACOG warning signs detected.",
        "hand_up": f"ACOG warning signs present: {', '.join(triggered)}",
        "hand_off": f"ACOG emergency signs present: {', '.join(triggered)}",
    }

    return TriageOutput(
        tier=tier_str,
        reason=reason_map[tier_str],
        triggered_rules=triggered,
        uncertainty=uncertainty,
        next_action=next_action_map[tier_str],
    ).model_dump()


# ---------------------------------------------------------------------------
# Rule dataclass + RULES list — used by evaluator.py (Role 3)
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    id: str
    tier: Literal["handle", "hand_up", "hand_off"]
    fires_when: Callable[[Dict[str, float], List[str], List[str]], bool]
    cite: str


RULES: List[Rule] = [
    # HAND-OFF — Immediate Emergency
    Rule("HIGH_BP_SEVERE", tier="hand_off",
         fires_when=lambda v, s, f: v.get("bp_systolic", 0) >= 160 or v.get("bp_diastolic", 0) >= 110,
         cite="ACOG: severe-range BP"),
    Rule("VISION_PLUS_HEADACHE", tier="hand_off",
         fires_when=lambda v, s, f: "visual_changes" in s and "headache" in s,
         cite="ACOG: vision change with headache"),
    Rule("ACUTE_SYMPTOMS", tier="hand_off",
         fires_when=lambda v, s, f: any(sym in s for sym in ["seizures", "heavy_bleeding", "chest_pain", "shortness_of_breath", "extreme_pain"]),
         cite="ACOG: Acute life-threatening symptom"),
    Rule("ACTIVE_SI", tier="hand_off",
         fires_when=lambda v, s, f: "suicidal_ideation_with_plan" in s,
         cite="ACOG: Active self-harm risk"),
    Rule("UNCERTAINTY_OVERRIDE", tier="hand_off",
         fires_when=lambda v, s, f: "maria_unable_to_classify" in f and "acute_distress" in s,
         cite="Safety Protocol: Uncertainty with distress"),
    # HAND-UP — Consult Physician within 20 mins
    Rule("HIGH_BP_MILD", tier="hand_up",
         fires_when=lambda v, s, f: 140 <= v.get("bp_systolic", 0) < 160 or 90 <= v.get("bp_diastolic", 0) < 110,
         cite="ACOG: mild-range BP"),
    Rule("MILD_SYMPTOM_CLUSTER", tier="hand_up",
         fires_when=lambda v, s, f: len([sym for sym in s if sym in ["headache", "edema_face_hands", "dizziness", "decreased_fetal_movement", "fever_over_100_4"]]) >= 2,
         cite="ACOG: Warning sign cluster"),
    Rule("COPE_UNCERTAINTY", tier="hand_up",
         fires_when=lambda v, s, f: "overwhelmed" in s and "suicidal_ideation_with_plan" not in s,
         cite="ACOG: Mental health evaluation"),
]
