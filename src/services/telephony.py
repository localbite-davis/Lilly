import os
from twilio.rest import Client

def trigger_emergency_callback(patient_phone_number: str):
    """
    Initiates an outbound phone call to the patient when a HAND-UP case auto-escalates
    or when a doctor explicitly hits the 'Escalate to L&D' button.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "mock_sid")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "mock_token")
    twilio_number = os.getenv("TWILIO_PHONE_NUMBER", "+1234567890")
    
    print(f"📞 [TWILIO] Dialing out to {patient_phone_number} for EMERGENCY ESCALATION...")

    # Skip actual Twilio API call if keys aren't real (prevents crash during local dev)
    if account_sid == "mock_sid" or account_sid == "your_twilio_account_sid":
        print("   -> Mocked successfully. (Configure real Twilio keys to dial actual phone).")
        return

    client = Client(account_sid, auth_token)
    
    # In a real app, this URL points to a TwiML endpoint that says:
    # "Maria, I wasn't able to reach the doctor, so we are going to treat this as an emergency..."
    try:
        call = client.calls.create(
            to=patient_phone_number,
            from_=twilio_number,
            url="http://demo.twilio.com/docs/voice.xml" # Placeholder for Lily's TTS response
        )
        print(f"   -> Call initiated successfully! Call SID: {call.sid}")
    except Exception as e:
        print(f"   -> Failed to initiate call: {e}")
