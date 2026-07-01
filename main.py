import os
import json
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Form, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from apscheduler.schedulers.background import BackgroundScheduler
import google.generativeai as genai

# 1. Config & Credentials
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
# Twilio's universal sandbox number
TWILIO_NUMBER = "whatsapp:+14155238886" 
# Your actual cell phone number
MY_NUMBER = "whatsapp:+17034079779" 

client = Client(TWILIO_SID, TWILIO_TOKEN)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# 2. Initialize the AI Agent
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    system_instruction="""
    You are a strict but encouraging personal accountability coach.
    Your job is to track the user's daily habits, specifically focusing on:
    1. Distance running and training mileage.
    2. Weight training sessions.
    3. General nutrition and macros.
    Keep your responses punchy, text-friendly, and actionable.
    """
)
# Keeps conversation history in memory while the server runs
chat = model.start_chat(history=[]) 

app = FastAPI()
HISTORY_FILE = "whatsapp_history.json"

# 3. The Proactive Cron Job (Daily Check-in)
def send_daily_checkin():
    msg = "Morning! Time for the daily check-in. What's on the schedule today—getting some miles in on the trail, hitting the gym, or a rest day?"
    client.messages.create(
        body=msg,
        from_=TWILIO_NUMBER,
        to=MY_NUMBER
    )

# Schedule the check-in for 8:00 AM every day
scheduler = BackgroundScheduler()
scheduler.add_job(send_daily_checkin, 'cron', hour=8, minute=0)
scheduler.start()

# 4. The Reactive Webhook (Handling your replies)
@app.post("/whatsapp")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...)):

    phone_number = From# 1. Pull the historical messages for this specific phone number
    history = load_user_history(From)
    
    # 2. Append the incoming message to the temporary history array for the model
    current_payload = list(history)
    current_payload.append({"role": "user", "parts": [Body]})
    # Pass your incoming WhatsApp text to the AI
    print(Body)
    ai_response = model.generate_content(current_payload)
    print(ai_response.text)

    # 4. Commit this new exchange permanently to our JSON file
    save_to_history(From, Body, ai_response.text)
    
    # Format the AI's text into Twilio's required XML response format
    twiml = MessagingResponse()
    twiml.message(ai_response.text)
    
    return Response(content=str(twiml), media_type="application/xml")

# --- HELPER FUNCTIONS FOR JSON STORAGE ---
def load_user_history(phone_number: str) -> list:
    """Loads chat history for a specific phone number from the JSON file."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
            return data.get(phone_number, [])
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def save_to_history(phone_number: str, user_msg: str, ai_msg: str):
    """Appends the new exchange to the JSON file, creating it if missing."""
    data = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = {}

    if phone_number not in data:
        data[phone_number] = []

    # Format strictly to match Gemini's expected content structure
    data[phone_number].append({"role": "user", "parts": [user_msg]})
    data[phone_number].append({"role": "model", "parts": [ai_msg]})

    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=4)
# ----------------------------------------
