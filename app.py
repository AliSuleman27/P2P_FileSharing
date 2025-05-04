import os
import sys
import socket
import threading
import random
import string
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from supabase import create_client, Client

# Supabase config
SUPABASE_URL = 'https://tifjokcxqabavfqngbyq.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRpZmpva2N4cWFiYXZmcW5nYnlxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDYzNTU4MDMsImV4cCI6MjA2MTkzMTgwM30.LyNUwHyjUvPhqrcBv6YREBo5ok5rmLjOdsiJMv2ZaeA'
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'yoursecret'
transfer_progress = {}

# ========= File Transfer Logic =========

def send_file_to_partner(file_path, user_id):
    try:
        filesize = os.path.getsize(file_path)
        transfer_progress[user_id] = {'status': 'waiting_for_receiver', 'progress': 0}

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 9090))
            s.listen(1)
            conn, addr = s.accept()
            with conn:
                transfer_progress[user_id]['status'] = 'sending'
                with open(file_path, 'rb') as f:
                    sent = 0
                    while True:
                        data = f.read(4096)
                        if not data:
                            break
                        conn.sendall(data)
                        sent += len(data)
                        transfer_progress[user_id]['progress'] = int((sent / filesize) * 100)
        transfer_progress[user_id]['status'] = 'done'
    except Exception as e:
        transfer_progress[user_id] = {'status': 'error', 'message': str(e)}

def receive_file_from_sender(save_dir, sender_ip, user_id):
    try:
        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, f"received_file_{user_id}")
        transfer_progress[user_id] = {'status': 'connecting', 'progress': 0}

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((sender_ip, 9090))
            with open(file_path, 'wb') as f:
                total_received = 0
                while True:
                    data = s.recv(4096)
                    if not data:
                        break
                    f.write(data)
                    total_received += len(data)
                    transfer_progress[user_id]['progress'] = int((total_received / (10 * 1024 * 1024)) * 100)  # estimate
        transfer_progress[user_id]['status'] = 'done'
    except Exception as e:
        transfer_progress[user_id] = {'status': 'error', 'message': str(e)}

# ========= Routes =========

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        try:
            response = supabase.table('users').select("*").eq("username", username).single().execute()
            user = response.data
            if not user or not check_password_hash(user['password'], password):
                flash("Invalid credentials", "danger")
                return redirect(url_for('login'))

            session['user_id'] = user['id']
            local_ip = get_local_ip()
            if local_ip:
                supabase.table('users').update({"local_ip": local_ip}).eq("id", user['id']).execute()
            return redirect(url_for('file_sharing'))

        except Exception as e:
            flash(f"Login error: {str(e)}", "danger")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        try:
            supabase.table('users').insert({
                'username': username,
                'email': email,
                'password': password
            }).execute()
            flash("Account created successfully!", "success")
            return redirect(url_for('login'))

        except Exception as e:
            flash(f"Signup error: {str(e)}", "danger")
            return redirect(url_for('signup'))

    return render_template('signup.html')

@app.route('/generate_key', methods=['POST'])
def generate_key():
    user_id = session.get('user_id')
    key = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    supabase.table('users').update({'pairing_key': key}).eq("id", user_id).execute()
    return jsonify({'pairing_key': key})

@app.route('/pair', methods=['POST'])
def pair():
    user_id = session.get('user_id')
    target_key = request.json.get('pairing_key')

    partner_resp = supabase.table('users').select("*").eq("pairing_key", target_key).single().execute()
    if not partner_resp.data:
        return jsonify({'error': 'Invalid pairing key'}), 404

    partner = partner_resp.data
    supabase.table('users').update({
        "paired_with_id": partner['id'],
        "partner_ip": partner['local_ip']
    }).eq("id", user_id).execute()

    return jsonify({
        'status': 'paired',
        'partner_username': partner['username'],
        'partner_ip': partner['local_ip']
    })

@app.route('/file_sharing')
def file_sharing():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = supabase.table('users').select("*").eq("id", user_id).single().execute().data
    partner = None
    if user.get('paired_with_id'):
        partner = supabase.table('users').select("*").eq("id", user['paired_with_id']).single().execute().data

    return render_template('file_sharing.html', user=user, partner=partner)

@app.route('/start_send', methods=['POST'])
def start_send():
    user_id = session.get('user_id')
    file = request.files['file']
    filename = secure_filename(file.filename)
    os.makedirs('temp', exist_ok=True)
    temp_path = os.path.join('temp', filename)
    file.save(temp_path)

    threading.Thread(target=send_file_to_partner, args=(temp_path, user_id)).start()
    return jsonify({'status': 'sending'})

@app.route('/start_receive', methods=['POST'])
def start_receive():
    user_id = session.get('user_id')
    save_dir = request.json.get('save_dir')
    sender_ip = supabase.table('users').select("partner_ip").eq("id", user_id).single().execute().data.get('partner_ip')

    threading.Thread(target=receive_file_from_sender, args=(save_dir, sender_ip, user_id)).start()
    return jsonify({'status': 'connecting'})

@app.route('/progress')
def progress():
    user_id = session.get('user_id')
    return jsonify(transfer_progress.get(user_id, {}))

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return None

if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else '0.0.0.0'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    app.run(host=host, port=port, debug=True)
