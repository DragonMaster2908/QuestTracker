import os
from flask import Flask, render_template, request, jsonify, send_from_directory
from supabase import create_client
from dotenv import load_dotenv
from pywebpush import webpush, WebPushException
import json

# Initialize Flask
app = Flask(__name__)

# Load Environment Variables
load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

# VAPID Keys for Notifications
VAPID_PRIVATE = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_EMAIL = os.environ.get("VAPID_EMAIL")

# --- DATABASE HELPERS ---

def load_data(user_email):
    response = supabase.table('player_save').select('save_data').eq('user_email', user_email).execute()
    if response.data and len(response.data) > 0:
        return response.data[0]['save_data']
    
    new_save = {
        "player": {"level": 1, "hp": 100, "max_hp": 100, "current_xp": 0},
        "daily": {}, "weekly": {}, "todo": {}, "subscription": None
    }
    supabase.table('player_save').insert({'user_email': user_email, 'save_data': new_save}).execute()
    return new_save

def save_data(data, user_email):
    supabase.table('player_save').update({'save_data': data}).eq('user_email', user_email).execute()

# --- SECURITY HELPER ---

def get_verified_email():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    try:
        user = supabase.auth.get_user(token)
        return user.user.email
    except Exception:
        return None

# --- AUTH & WEB ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('templates', 'manifest.json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('templates', 'sw.js')

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    req = request.json
    try:
        supabase.auth.sign_up({"email": req.get("email"), "password": req.get("password")})
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/auth/login', methods=['POST'])
def login():
    req = request.json
    try:
        res = supabase.auth.sign_in_with_password({"email": req.get("email"), "password": req.get("password")})
        return jsonify({"status": "success", "token": res.session.access_token, "email": req.get("email")})
    except Exception:
        return jsonify({"status": "error"}), 401

# --- TASK ENGINE (With Gamification) ---

@app.route('/api/data', methods=['GET'])
def get_data():
    email = get_verified_email()
    if not email: return jsonify({"status": "error"}), 401
    return jsonify(load_data(email))

@app.route('/api/task/toggle', methods=['POST'])
def toggle_task():
    email = get_verified_email()
    if not email: return jsonify({"status": "error"}), 401
    
    data = load_data(email)
    req = request.json
    cat, t_name, state = req.get("category"), req.get("task_name"), req.get("state")
    
    if cat in data and t_name in data[cat]:
        current_state = data[cat][t_name].get("state", 0)
        data[cat][t_name]["state"] = state
        
        # XP Math Logic
        if current_state != 1 and state == 1:
            diff = data[cat][t_name].get("difficulty", "Medium")
            xp_map = {"Trivial": 5, "Easy": 10, "Medium": 20, "Hard": 40, "Epic": 100}
            data["player"]["current_xp"] += xp_map.get(diff, 20)
            
            # Level up math: $XP_{max} = 100 \times 1.10^{(level-1)}$
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

# --- NOTIFICATION ENGINE ---

@app.route('/api/save-subscription', methods=['POST'])
def save_subscription():
    email = get_verified_email()
    if not email: return jsonify({"status": "error"}), 401
    data = load_data(email)
    data['subscription'] = request.json
    save_data(data, email)
    return jsonify({"status": "success"})

# This route is called by an external Cron Job (like cron-job.org)
@app.route('/api/cron/check-reminders', methods=['GET'])
def check_reminders():
    # In a real build, you'd loop through all users here. 
    # For now, this is the logic to send a test ping.
    return jsonify({"status": "ready"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)