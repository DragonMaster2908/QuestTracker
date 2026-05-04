import os
from flask import Flask, render_template, request, jsonify
from supabase import create_client
from dotenv import load_dotenv

# Initialize Flask
app = Flask(__name__)

# Load Environment Variables
load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

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
    return jsonify(load_data(email))

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

if __name__ == '__main__':
    # Use the port assigned by the cloud host, or default to 5000
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)