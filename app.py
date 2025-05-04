import os
import sys
import socket
import threading
import random
import string
import json
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
        filename = os.path.basename(file_path)
        filesize = os.path.getsize(file_path)
        transfer_progress[user_id] = {'status': 'waiting_for_receiver', 'progress': 0}

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 9090))
            s.listen(1)
            conn, addr = s.accept()
            with conn:
                # First send the filename as JSON
                file_info = json.dumps({'filename': filename, 'filesize': filesize}).encode('utf-8')
                # Send the size of the file info first, so receiver knows how much to read
                conn.sendall(len(file_info).to_bytes(4, byteorder='big'))
                conn.sendall(file_info)
                
                # Now send the actual file
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
        transfer_progress[user_id] = {'status': 'connecting', 'progress': 0}

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((sender_ip, 9090))
            
            # First receive the file info size
            info_size_bytes = s.recv(4)
            info_size = int.from_bytes(info_size_bytes, byteorder='big')
            
            # Now receive the file info JSON
            file_info_bytes = b''
            bytes_received = 0
            while bytes_received < info_size:
                chunk = s.recv(min(info_size - bytes_received, 4096))
                if not chunk:
                    raise Exception("Connection closed before receiving complete file info")
                file_info_bytes += chunk
                bytes_received += len(chunk)
            
            file_info = json.loads(file_info_bytes.decode('utf-8'))
            filename = secure_filename(file_info['filename'])
            filesize = file_info['filesize']
            
            # Now receive the actual file
            file_path = os.path.join(save_dir, filename)
            transfer_progress[user_id]['status'] = 'receiving'
            
            with open(file_path, 'wb') as f:
                total_received = 0
                while total_received < filesize:
                    data = s.recv(4096)
                    if not data:
                        break
                    f.write(data)
                    total_received += len(data)
                    transfer_progress[user_id]['progress'] = int((total_received / filesize) * 100)
                    
        transfer_progress[user_id]['status'] = 'done'
        transfer_progress[user_id]['filename'] = filename
    except Exception as e:
        transfer_progress[user_id] = {'status': 'error', 'message': str(e)}


# ========= Routes =========

@app.route('/')
def index():
    try:
        response = supabase.table('users').select("*").execute()
        users = response.data
        if isinstance(users, dict) and 'message' in users:  # Handling error message
            flash(f"Error: {users['message']}", "danger")
            return redirect(url_for('index'))
        return render_template('index.html', users=users)
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")
        return redirect(url_for('index'))
    
    
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
    if not user_id:
        return jsonify({'error': 'Not logged in'}), 401
        
    key = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    try:
        supabase.table('users').update({'pairing_key': key}).eq("id", user_id).execute()
        return jsonify({'pairing_key': key})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/pair', methods=['POST'])
def pair():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not logged in'}), 401
        
    target_key = request.json.get('pairing_key')
    if not target_key:
        return jsonify({'error': 'No pairing key provided'}), 400

    try:
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
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/file_sharing')
def file_sharing():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    try:
        user = supabase.table('users').select("*").eq("id", user_id).single().execute().data
        partner = None
        if user.get('paired_with_id'):
            partner = supabase.table('users').select("*").eq("id", user['paired_with_id']).single().execute().data

        return render_template('file_sharing.html', user=user, partner=partner)
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")
        return redirect(url_for('login'))

@app.route('/start_send', methods=['POST'])
def start_send():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not logged in'}), 401
        
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    filename = secure_filename(file.filename)
    os.makedirs('temp', exist_ok=True)
    temp_path = os.path.join('temp', filename)
    
    try:
        file.save(temp_path)
        threading.Thread(target=send_file_to_partner, args=(temp_path, user_id)).start()
        return jsonify({'status': 'sending'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/start_receive', methods=['POST'])
def start_receive():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not logged in'}), 401
        
    save_dir = request.json.get('save_dir')
    if not save_dir:
        save_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
    
    try:
        user_data = supabase.table('users').select("partner_ip").eq("id", user_id).single().execute().data
        sender_ip = user_data.get('partner_ip')
        
        if not sender_ip:
            return jsonify({'error': 'Partner IP not found'}), 404
            
        threading.Thread(target=receive_file_from_sender, args=(save_dir, sender_ip, user_id)).start()
        return jsonify({'status': 'connecting'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/progress')
def progress():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Not logged in'}), 401
        
    return jsonify(transfer_progress.get(user_id, {}))

# Edit user
@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    if request.method == 'POST':
        updates = {
            "username": request.form['username'],
            "email": request.form['email']
        }
        if request.form['password']:
            updates['password'] = generate_password_hash(request.form['password'])

        try:
            supabase.table('users').update(updates).eq("id", id).execute()
            flash("User details updated successfully!", "success")
            return redirect(url_for('index'))
        except Exception as e:
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for('edit', id=id))

    try:
        user = supabase.table('users').select("*").eq("id", id).single().execute().data
        return render_template('edit.html', user=user)
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")
        return redirect(url_for('index'))

# Delete user
@app.route('/delete/<int:id>', methods=['GET', 'POST'])
def delete(id):
    try:
        supabase.table('users').delete().eq("id", id).execute()
        flash("User deleted successfully", "success")
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for('index'))


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