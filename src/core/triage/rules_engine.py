"""
Deterministic rules engine based on ACOG (American College of Obstetricians and Gynecologists)
Urgent Maternal Warning Signs.
"""

from enum import Enum

class TriageTier(Enum):
    HANDLE = "HANDLE"
    HAND_UP = "HAND_UP"
    HAND_OFF = "HAND_OFF"

# ACOG Urgent Maternal Warning Signs mapped to deterministic rules
ACOG_WARNING_SIGNS = {
    # Hand-Off (Immediate Emergency)
    "seizures": TriageTier.HAND_OFF,
    "heavy_bleeding": TriageTier.HAND_OFF, # Soaking through 1 pad per hour
    "chest_pain": TriageTier.HAND_OFF,
    "shortness_of_breath": TriageTier.HAND_OFF,
    "extreme_pain": TriageTier.HAND_OFF,
    "systolic_bp_over_160": TriageTier.HAND_OFF,
    "diastolic_bp_over_110": TriageTier.HAND_OFF,
    
    # Hand-Up (Consult Physician within 20 mins)
    "fever_over_100_4": TriageTier.HAND_UP,
    "severe_headache_not_going_away": TriageTier.HAND_UP,
    "dizziness": TriageTier.HAND_UP,
    "changes_in_vision": TriageTier.HAND_UP,
    "swelling_in_face_or_hands": TriageTier.HAND_UP,
    "decreased_fetal_movement": TriageTier.HAND_UP,
    "systolic_bp_over_140": TriageTier.HAND_UP,
    "diastolic_bp_over_90": TriageTier.HAND_UP,
}
