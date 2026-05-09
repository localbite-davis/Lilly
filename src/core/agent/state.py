from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime

class ConversationState(BaseModel):
    """
    Tracks the state of the conversation in real-time during a call.
    """
    call_sid: str
    patient_id: int
    started_at: datetime
    message_history: List[Dict[str, str]] = []
    extracted_symptoms: List[str] = []
    current_triage_tier: str = "HANDLE"
    
    def add_message(self, role: str, content: str):
        self.message_history.append({"role": role, "content": content})
        
    def update_triage_tier(self, new_tier: str):
        # Only escalate, never de-escalate during a call automatically
        tier_weights = {"HANDLE": 1, "HAND_UP": 2, "HAND_OFF": 3}
        if tier_weights.get(new_tier, 1) > tier_weights.get(self.current_triage_tier, 1):
            self.current_triage_tier = new_tier
