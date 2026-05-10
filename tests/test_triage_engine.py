import pytest
from src.core.triage.evaluator import classify_case, TriageInput, TriageOutput

def test_1_mild_bp_and_symptom_cluster_is_hand_up():
    """BP 148/94 + headache + edema -> hand_up"""
    input_data = TriageInput(
        symptoms=["headache", "edema_face_hands"],
        vitals={"bp_systolic": 148, "bp_diastolic": 94},
        gestational_weeks=32, postpartum_days=None, flags=[]
    )
    result = classify_case(input_data)
    assert result.tier == "hand_up"
    assert "HIGH_BP_MILD" in result.triggered_rules

def test_2_severe_bp_is_hand_off():
    """BP 162/108 -> hand_off"""
    input_data = TriageInput(
        symptoms=[],
        vitals={"bp_systolic": 162, "bp_diastolic": 108},
        gestational_weeks=32, postpartum_days=None, flags=[]
    )
    result = classify_case(input_data)
    assert result.tier == "hand_off"
    assert "HIGH_BP_SEVERE" in result.triggered_rules

def test_3_vision_and_headache_is_hand_off():
    """No BP + headache + vision changes -> hand_off"""
    input_data = TriageInput(
        symptoms=["headache", "visual_changes"],
        vitals={},
        gestational_weeks=32, postpartum_days=None, flags=[]
    )
    result = classify_case(input_data)
    assert result.tier == "hand_off"
    assert "VISION_PLUS_HEADACHE" in result.triggered_rules

def test_4_two_warning_signs_is_hand_up():
    """No BP + 2 ACOG warning signs -> hand_up"""
    input_data = TriageInput(
        symptoms=["dizziness", "decreased_fetal_movement"],
        vitals={},
        gestational_weeks=32, postpartum_days=None, flags=[]
    )
    result = classify_case(input_data)
    assert result.tier == "hand_up"
    assert "MILD_SYMPTOM_CLUSTER" in result.triggered_rules

def test_5_zero_symptoms_is_handle():
    """No BP + 0 symptoms + 'I'm just tired' -> handle"""
    input_data = TriageInput(
        symptoms=["tiredness"], # Not a warning sign
        vitals={},
        gestational_weeks=32, postpartum_days=None, flags=[]
    )
    result = classify_case(input_data)
    assert result.tier == "handle"
    assert len(result.triggered_rules) == 0

def test_6_chest_pain_is_hand_off():
    """No BP + chest pain -> hand_off"""
    input_data = TriageInput(
        symptoms=["chest_pain"],
        vitals={},
        gestational_weeks=32, postpartum_days=None, flags=[]
    )
    result = classify_case(input_data)
    assert result.tier == "hand_off"
    assert "ACUTE_SYMPTOMS" in result.triggered_rules

def test_7_active_si_is_hand_off():
    """Mood: 'I can't cope, I think about hurting myself' + plan -> hand_off"""
    input_data = TriageInput(
        symptoms=["suicidal_ideation_with_plan"],
        vitals={},
        gestational_weeks=32, postpartum_days=None, flags=[]
    )
    result = classify_case(input_data)
    assert result.tier == "hand_off"
    assert "ACTIVE_SI" in result.triggered_rules

def test_8_overwhelmed_is_hand_up():
    """Mood: 'I feel really overwhelmed' only -> hand_up"""
    input_data = TriageInput(
        symptoms=["overwhelmed"],
        vitals={},
        gestational_weeks=32, postpartum_days=None, flags=[]
    )
    result = classify_case(input_data)
    assert result.tier == "hand_up"
    assert "COPE_UNCERTAINTY" in result.triggered_rules

def test_9_uncertainty_with_distress_is_hand_off():
    """Lily flag: maria_unable_to_classify + acute distress -> hand_off"""
    input_data = TriageInput(
        symptoms=["acute_distress"],
        vitals={},
        gestational_weeks=32, postpartum_days=None, flags=["maria_unable_to_classify"]
    )
    result = classify_case(input_data)
    assert result.tier == "hand_off"
    assert "UNCERTAINTY_OVERRIDE" in result.triggered_rules
    assert result.uncertainty == True
