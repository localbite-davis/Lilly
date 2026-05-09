from typing import List, Dict
from src.core.triage.rules_engine import ACOG_WARNING_SIGNS, TriageTier

class TriageEvaluator:
    """
    Evaluates extracted symptoms against deterministic ACOG rules.
    This prevents LLM hallucinations in critical medical decisions.
    """
    
    @staticmethod
    def evaluate_symptoms(symptoms: List[str], vitals: Dict[str, float] = None) -> TriageTier:
        """
        Returns the highest triage tier based on symptoms and vitals.
        """
        highest_tier = TriageTier.HANDLE
        
        # Check standard symptoms
        for symptom in symptoms:
            if symptom in ACOG_WARNING_SIGNS:
                tier = ACOG_WARNING_SIGNS[symptom]
                if tier == TriageTier.HAND_OFF:
                    return TriageTier.HAND_OFF # Highest severity, immediate return
                if tier == TriageTier.HAND_UP:
                    highest_tier = TriageTier.HAND_UP
                    
        # Check vitals if provided
        if vitals:
            sys_bp = vitals.get("systolic_bp")
            dia_bp = vitals.get("diastolic_bp")
            
            if sys_bp is not None:
                if sys_bp >= 160: return TriageTier.HAND_OFF
                if sys_bp >= 140: highest_tier = TriageTier.HAND_UP
                
            if dia_bp is not None:
                if dia_bp >= 110: return TriageTier.HAND_OFF
                if dia_bp >= 90: highest_tier = TriageTier.HAND_UP
                
            temp = vitals.get("temperature")
            if temp is not None and temp >= 100.4:
                highest_tier = TriageTier.HAND_UP if highest_tier != TriageTier.HAND_OFF else TriageTier.HAND_OFF

        return highest_tier
