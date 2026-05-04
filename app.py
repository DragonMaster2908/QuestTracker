import os
import json
from datetime import datetime
import pytz
from flask import Flask, render_template, request, jsonify, send_from_directory
from supabase import create_client
from dotenv import load_dotenv
from pywebpush import webpush, WebPushException

# Initialize Flask
app = Flask(__name__)

# Load Environment Variables
load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

# Notification Keys
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_EMAIL = os.environ.get("VAPID_EMAIL")

# --- DATABASE HELPERS ---

def load_data(user_email):
    # Ask Supabase for the save file belonging to this specific email
    response = supabase.table('player_save').select('save_data').eq('user_email', user_email).execute()
    
    if response.data and len(response.data) > 0:
        return response.data[0]['save_data']
    
    # New user template
    new_save = {
        "player": {"level": 1, "hp": 100, "max_hp": 100, "current_xp": 0},
        "daily": {}, "weekly": {}, "todo": {}
    }
    supabase.table('player_save').insert({
        'user_email': user_email, 
        'save_data': new_save
    }).execute()
    
    return new_save

def save_data(data, user_email):
    supabase.table('player_save').update({'save_data': data}).eq('user_email', user_email).execute()

# --- SECURITY HELPER ---

def get_verified_email():
    """Verifies the JWT token and returns the user's email."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    
    token = auth_header.split(" ")[1]
    try:
        user = supabase.auth.get_user(token)
        return user.user.email
    except Exception:
        return None

# --- WEB ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

# --- AUTHENTICATION ROUTES ---

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    req = request.json
    try:
        supabase.auth.sign_up({"email": req.get("email"), "password": req.get("password")})
        return jsonify({"status": "success", "message": "User created!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/auth/login', methods=['POST'])
def login():
    req = request.json
    try:
        response = supabase.auth.sign_in_with_password({"email": req.get("email"), "password": req.get("password")})
        return jsonify({
            "status": "success", 
            "token": response.session.access_token, 
            "email": req.get("email")
        })
    except Exception:
        return jsonify({"status": "error", "message": "Invalid email or password"}), 401

# --- SECURE API ROUTES ---

@app.route('/api/data', methods=['GET'])
def get_data():
    email = get_verified_email()
    if not email: return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = load_data(email)
    
    # EOD CLEANUP FOR TO-DO TASKS
    today = datetime.now().strftime("%Y-%m-%d")
    todos = data.get("todo", {})
    to_delete = []
    
    for t_name, details in todos.items():
        if details.get("state") == 1:
            comp_date = details.get("completed_date")
            # If it has a date and it is NOT today, mark it for deletion
            if comp_date and comp_date != today:
                to_delete.append(t_name)
    
    # Delete the old ones and save if any were swept
    if to_delete:
        for t_name in to_delete:
            del data["todo"][t_name]
        save_data(data, email)

    return jsonify(data)

@app.route('/api/task/toggle', methods=['POST'])
def toggle_task():
    email = get_verified_email()
    if not email: return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = load_data(email)
    req = request.json
    category, task_name, state = req.get("category"), req.get("task_name"), req.get("state")
    
    if category in data and task_name in data[category]:
        current_state = data[category][task_name].get("state", 0)
        data[category][task_name]["state"] = state
        
        # When checking it off, add today's date so we know when to delete it later
        if state == 1:
            data[category][task_name]["completed_date"] = datetime.now().strftime("%Y-%m-%d")
        
        # Original XP Logic
        if current_state != 1 and state == 1:
            diff = data[category][task_name].get("difficulty", "Medium")
            xp_map = {"Trivial": 5, "Easy": 10, "Medium": 20, "Hard": 40, "Epic": 100}
            data["player"]["current_xp"] += xp_map.get(diff, 20)
            
            max_xp = int(100 * (1.10 ** (data["player"]["level"] - 1)))
            while data["player"]["current_xp"] >= max_xp:
                data["player"]["level"] += 1
                data["player"]["current_xp"] -= max_xp
                data["player"]["max_hp"] += 5
                data["player"]["hp"] = data["player"]["max_hp"] 
                max_xp = int(100 * (1.10 ** (data["player"]["level"] - 1)))
                
        save_data(data, email)
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

@app.route('/api/task/add', methods=['POST'])
def add_task():
    email = get_verified_email()
    if not email: return jsonify({"status": "error"}), 401
    
    data = load_data(email)
    req = request.json
    category, t_name = req.get("category"), req.get("task_name")
    
    if not t_name or t_name in data[category]: return jsonify({"status": "error"}), 400

    new_task = {"state": 0, "difficulty": req.get("difficulty", "Medium")}
    if req.get("target_time"): new_task["target_time"] = req.get("target_time")
    if category == "weekly" and req.get("days"): new_task["days"] = req.get("days")
    if category == "todo" and req.get("target_date"): new_task["target_date"] = req.get("target_date")
        
    data[category][t_name] = new_task
    save_data(data, email)
    return jsonify({"status": "success"})

@app.route('/api/task/delete', methods=['POST'])
def delete_task():
    email = get_verified_email()
    if not email: return jsonify({"status": "error"}), 401
    data = load_data(email)
    req = request.json
    category, t_name = req.get("category"), req.get("task_name")
    if t_name in data[category]:
        del data[category][t_name]
        save_data(data, email)
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

@app.route('/api/task/edit', methods=['POST'])
def edit_task():
    email = get_verified_email()
    if not email: return jsonify({"status": "error"}), 401
    data = load_data(email)
    req = request.json
    cat, old, new = req.get("category"), req.get("old_name"), req.get("new_name")
    
    task_data = data[cat].pop(old)
    task_data["difficulty"] = req.get("difficulty", task_data.get("difficulty"))
    if "target_time" in req: task_data["target_time"] = req.get("target_time")
    if "target_date" in req: task_data["target_date"] = req.get("target_date")
    if "days" in req: task_data["days"] = req.get("days")

    data[cat][new] = task_data
    save_data(data, email)
    return jsonify({"status": "success"})

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('templates', 'manifest.json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('templates', 'sw.js')

@app.route('/api/save-subscription', methods=['POST'])
def save_subscription():
    email = get_verified_email()
    if not email: return jsonify({"status": "error", "message": "Unauthorized"}), 401
    data = load_data(email)
    data['subscription'] = request.json
    save_data(data, email)
    return jsonify({"status": "success", "message": "Subscription saved!"})

# --- PUSH NOTIFICATION ENGINE ---

def send_push(subscription, title, body):
    """Sends the actual alert to the phone."""
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{VAPID_EMAIL}"}
        )
    except WebPushException as ex:
        print("Push failed:", ex)

@app.route('/api/cron/trigger-alerts', methods=['GET'])
def trigger_alerts():
    """This route is pinged every minute by cron-job.org"""
    
    # Optional Security: Only run if the correct secret password is provided in the URL
    secret = request.args.get("key")
    if secret != "ojas_forge_123":
        return jsonify({"status": "unauthorized"}), 401

    # Force the server to use Indian Standard Time (IST)
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    current_time = now.strftime("%H:%M")
    current_date = now.strftime("%Y-%m-%d")
    current_day = now.strftime("%a") # Returns 'Mon', 'Tue', etc.

    # Fetch all users
    response = supabase.table('player_save').select('save_data').execute()
    
    alerts_sent = 0
    for row in response.data:
        data = row['save_data']
        sub = data.get('subscription')
        if not sub: continue # Skip if user hasn't enabled alerts
        
        # 1. Check Daily Tasks
        for t_name, details in data.get("daily", {}).items():
            if details.get("state") != 1 and details.get("target_time") == current_time:
                send_push(sub, "Daily Quest Due!", f"Time to tackle: {t_name}")
                alerts_sent += 1
        
        # 2. Check Weekly Tasks
        for t_name, details in data.get("weekly", {}).items():
            days = details.get("days", [])
            # Only alert if it's not done, it's scheduled for today, AND the time matches
            if details.get("state") != 1 and current_day in days and details.get("target_time") == current_time:
                send_push(sub, "Weekly Quest Due!", f"Scheduled for today: {t_name}")
                alerts_sent += 1
                
        # 3. Check To-Do Tasks
        for t_name, details in data.get("todo", {}).items():
            # Only alert if it's not done, the date matches today, AND the time matches
            if details.get("state") != 1 and details.get("target_date") == current_date and details.get("target_time") == current_time:
                send_push(sub, "Deadline Reached!", f"To-Do due now: {t_name}")
                alerts_sent += 1

    return jsonify({"status": "success", "time_checked": current_time, "alerts_fired": alerts_sent})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
