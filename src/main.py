import os
from dotenv import load_dotenv

from .nutrition import (
    build_daily_log_notification,
    extract_structured_nutrition,
    should_save_nutrition_log,
)
from .profile import persist_profile_update
from .utils import get_user_record, load_user_history, save_nutrition_log, save_to_history

load_dotenv()

from fastapi import FastAPI, Form, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from apscheduler.schedulers.background import BackgroundScheduler
import google.generativeai as genai

# 1. Config & Credentials
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
print(f"TWILIO_SID: {TWILIO_SID}")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
print(f"GEMINI_API_KEY: {GEMINI_API_KEY}")
# Twilio's universal sandbox number
TWILIO_NUMBER = "whatsapp:+14155238886" 
# Your actual cell phone number
MY_NUMBER = "whatsapp:+17034079779" 

client = Client(TWILIO_SID, TWILIO_TOKEN)
if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY environment variable is not set. "
        "Create a valid API key and set GEMINI_API_KEY in your environment or .env file."
    )

genai.configure(api_key=GEMINI_API_KEY)

# 2. Initialize the AI Agent
model = genai.GenerativeModel(
    model_name="gemini-3.1-flash-lite",
    system_instruction="""
    You are a strict but encouraging personal accountability coach.
    Your job is to track the user's daily habits, specifically focusing on calorie and macro goals:
    1. Ask a new user about their current and goal weight and what timeline they have in mind for their weight loss or gain.
    2. Ask about their height, age, sex, waist circumference to calculate their Basal Metabolic Rate (BMR) and Total Daily Energy Expenditure (TDEE).
    3. Recommend a daily calorie goal based on their TDEE and weight goals, and ask them to confirm it.
    4. Ask the user to log their meals and snacks with as much precision as their able.
    5. Always report back the calories and macros from the user's current response at the top of your response..
    6. Report the daily summary of the user's nutrition logs. The System Notification is based on user's previous nutrition logs.  Be sure to add any new reported calories to the system notification data.
    7. Limit responses to 1500 characters. prioritize step 5 over 6.  
    8. Do not include the system notification in your response.
    9. Do not make nutrition recommendations. Instead, ask the user whether they have any macro targets such as protein, carbs, or fat goals and record them if they share them.
    10. Don't make any judgments about user choices or not meeting calorie goals.
    11. Remind the user to weigh themselves every morning.
    Praise the user for daily reports and ask about any missed meals or snacks. Encourage them to log everything, even if they went over their calorie goal.
    """
)

app = FastAPI()

# 3. The Proactive Cron Job (Daily Check-in)
def send_daily_checkin():
    msg = "Morning! Time for the daily check-in. What's on the schedule today—getting some miles in on the trail, hitting the gym, or a rest day?"
    client.messages.create(
        body=msg,
        from_=TWILIO_NUMBER,
        to=MY_NUMBER
    )

# Schedule the check-in for 8:00 AM every day
# scheduler = BackgroundScheduler()
# scheduler.add_job(send_daily_checkin, 'cron', hour=8, minute=0)
# scheduler.start()

# 4. The Reactive Webhook (Handling your replies)
@app.post("/whatsapp")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...)):
    

    phone_number = From# 1. Pull the historical messages for this specific phone number
    history = load_user_history(From)
    
    # 2. Append the incoming message to the temporary history array for the model
    current_payload = list(history)
    record = get_user_record(From)
    system_notification = build_daily_log_notification(
        record["user_profile"],
        record["nutrition_logs"],
    )
    print(system_notification)
    current_payload.append({"role": "user", "parts": [system_notification, Body]})
    # Pass your incoming WhatsApp text to the AI
    print(Body)
    ai_response = model.generate_content(current_payload)
    print(ai_response.text)
    # 4. Commit this new exchange permanently to our JSON file
    save_to_history(From, Body, ai_response.text)

    nutrition = extract_structured_nutrition(Body, ai_response.text)
    print(nutrition)
    if should_save_nutrition_log(nutrition):
        log_entry = {**nutrition}
        log_entry.pop("is_food_log", None)
        save_nutrition_log(From, log_entry)

    persist_profile_update(
        phone_number=From,
        user_text=Body,
        ai_response=ai_response.text,
    )

    # Format the AI's text into Twilio's required XML response format
    twiml = MessagingResponse()
    twiml.message(ai_response.text)  # Append system instruction for context
    
    return Response(content=str(twiml), media_type="application/xml")
