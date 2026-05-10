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

def send_decision_notification(patient_phone: str, decision_type: str, note: str = ""):
    """
    Sends an SMS notification to the patient about the doctor's decision
    on their clinical escalation ticket.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "mock_sid")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "mock_token")
    twilio_number = os.getenv("TWILIO_PHONE_NUMBER", "+1234567890")
    
    if decision_type == "approve":
        message_body = "Lily Update: Your clinical team has reviewed your vitals and symptoms. Your current care plan is authorized. Continue following existing guidance."
    elif decision_type == "escalate":
        message_body = "URGENT Lily Update: Your clinical team has reviewed your case and requested an immediate escalation to Labor & Delivery. Please proceed to your nearest medical center."
    else:
        return

    if note:
        message_body += f"\n\nDoctor Note: {note}"

    print(f"💬 [TWILIO] Sending SMS to {patient_phone}: {message_body}")

    if account_sid == "mock_sid" or account_sid == "your_twilio_account_sid":
        print("   -> Mocked successfully. (Configure real Twilio keys to send actual SMS).")
        return

    client = Client(account_sid, auth_token)
    try:
        msg = client.messages.create(
            to=patient_phone,
            from_=twilio_number,
            body=message_body
        )
        print(f"   -> SMS sent successfully! SID: {msg.sid}")
    except Exception as e:
        print(f"   -> Failed to send SMS: {e}")

def trigger_decision_call(patient_phone: str, decision_type: str, note: str = "", base_url: str | None = None):
    """
    Initiates an outbound call to the patient to relay the doctor's decision
    using Lily's ElevenLabs voice. base_url must be the public Cloudflare/ngrok
    URL so Twilio can reach the TwiML + TTS endpoints.
    """
    import urllib.parse
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "mock_sid")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "mock_token")
    twilio_number = os.getenv("TWILIO_PHONE_NUMBER", "+1234567890")

    if base_url is None:
        base_url = os.getenv("APP_BASE_URL", "http://localhost:8000")

    twiml_url = f"{base_url}/api/twilio/voice/decision/{decision_type}"
    if note:
        twiml_url += f"?note={urllib.parse.quote(note)}"

    print(f"📞 [TWILIO] Triggering decision call to {patient_phone} ({decision_type})...")
    print(f"   -> TwiML URL: {twiml_url}")

    if account_sid in ("mock_sid", "your_twilio_account_sid"):
        print("   -> Mocked. Set real Twilio keys to trigger actual voice call.")
        return

    client = Client(account_sid, auth_token)
    try:
        call = client.calls.create(to=patient_phone, from_=twilio_number, url=twiml_url)
        print(f"   -> Decision call initiated! SID: {call.sid}")
    except Exception as e:
        print(f"   -> Failed to initiate decision call: {e}")
