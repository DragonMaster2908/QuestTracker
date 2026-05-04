import os
import json
from datetime import datetime
from supabase import create_client
from pywebpush import webpush, WebPushException
from dotenv import load_dotenv

# Load Environment Variables
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_EMAIL = os.environ.get("VAPID_EMAIL")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_push(subscription, title, body):
    """Sends the actual push notification to the browser/phone."""
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{VAPID_EMAIL}"}
        )
        print(f"Sent: {title}")
    except WebPushException as ex:
        print(f"Push failed: {ex}")
        if ex.response and ex.response.json():
            print(ex.response.json())

def check_reminders():
    """Scans all users and sends alerts for pending tasks."""
    print(f"Running check at {datetime.now().strftime('%H:%M')}")
    
    # 1. Get all player saves
    response = supabase.table('player_save').select('save_data, user_email').execute()
    
    for row in response.data:
        data = row['save_data']
        email = row['user_email']
        subscription = data.get('subscription')
        
        # If they haven't clicked "Enable Alerts", skip them
        if not subscription:
            continue

        # 2. Check Daily Tasks
        dailies = data.get("daily", {})
        for t_name, details in dailies.items():
            if details.get("state") != 1:  # Only if NOT completed
                target_time = details.get("target_time")
                if target_time:
                    # Very simple check: If the target time matches the current hour/minute
                    if target_time == datetime.now().strftime("%H:%M"):
                        send_push(subscription, "Daily Quest Due!", f"Time to tackle: {t_name}")

        # You can add similar logic here for Weeklies and To-Dos!

if __name__ == "__main__":
    check_reminders()
