from dataclasses import dataclass
from typing import Callable, Dict, List, Literal

@dataclass
class Rule:
    id: str
    tier: Literal["handle", "hand_up", "hand_off"]
    fires_when: Callable[[Dict[str, float], List[str], List[str]], bool]
    cite: str

# Deterministic Rules Engine (ACOG Guidelines)
# Evaluates vitals (v), symptoms (s), and flags (f)
RULES = [
    # ---------------------------------------------------------
    # HAND-OFF (Immediate Emergency, 3-way call to 911)
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    # HAND-UP (Consult Physician within 20 mins)
    # ---------------------------------------------------------
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
