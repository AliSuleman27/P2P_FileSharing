import random
import string
import socket
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client, Client
import sys

# Supabase config
SUPABASE_URL = 'https://tifjokcxqabavfqngbyq.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRpZmpva2N4cWFiYXZmcW5nYnlxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDYzNTU4MDMsImV4cCI6MjA2MTkzMTgwM30.LyNUwHyjUvPhqrcBv6YREBo5ok5rmLjOdsiJMv2ZaeA'
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secretkey'


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # Connect to a remote DNS server to determine the local IP
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception as e:
        return None


# Home
@app.route('/')
def index():
    try:
        response = supabase.table('users').select("*").execute()
        users = response.data
        if 'message' in users:  # Handling error message
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

            # Get the local IP using the function
            local_ip = get_local_ip()
            if local_ip:
                # Save the local IP address to Supabase
                supabase.table('users').update({
                    "local_ip": local_ip
                }).eq("id", user['id']).execute()

            flash("Login successful!", "success")
            return redirect(url_for('file_sharing'))

        except Exception as e:
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for('login'))

    return render_template('login.html')
    

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        try:
            # Insert into Supabase table 'users'
            response = supabase.table('users').insert({
                'username': username,
                'email': email,
                'password': password
            }).execute()

            # Check if there's an error message in the response data
            if isinstance(response.data, list) and len(response.data) == 0:
                flash("Error: Failed to create user.", "danger")
                return redirect(url_for('signup'))

            if "message" in response.data:  # Checking for any error message
                flash(f"Error: {response.data['message']}", "danger")
                return redirect(url_for('signup'))

            flash("Account created successfully!", "success")
            return redirect(url_for('login'))

        except Exception as e:
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for('signup'))

    return render_template('signup.html')

# Generate pairing key
@app.route('/generate_key', methods=['POST'])
def generate_key():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    pairing_key = ''.join(random.choices(string.ascii_letters + string.digits, k=8))

    try:
        supabase.table('users').update({
            "pairing_key": pairing_key
        }).eq("id", user_id).execute()

        flash("Pairing key generated!", "success")
    except Exception as e:
        flash(f'Error generating pairing key: {str(e)}', 'danger')

    return jsonify({'pairing_key': pairing_key})

# Pair users
@app.route('/pair', methods=['POST'])
def pair():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    target_key = request.json.get('pairing_key')

    try:
        partner_resp = supabase.table('users').select("*").eq("pairing_key", target_key).single().execute()
        if not partner_resp.data:
            return jsonify({'error': 'Invalid pairing key'}), 404

        partner = partner_resp.data
        partner_id = partner['id']
        partner_ip = partner['local_ip']

        # Update both users
        supabase.table('users').update({
            "paired_with_id": partner_id,
            "partner_ip" : partner_ip 
        }).eq("id", user_id).execute()

        return jsonify({
            'status': 'paired',
            'partner_username': partner['username'],
            'partner_ip': partner['local_ip']
        })

    except Exception as e:
        return jsonify({'error': f'Error pairing users: {str(e)}'}), 500

# File sharing page
@app.route('/file_sharing', methods=['GET'])
def file_sharing():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    try:
        user_resp = supabase.table('users').select("*").eq("id", user_id).single().execute()
        user = user_resp.data

        partner = None
        if user.get('paired_with_id'):
            partner_resp = supabase.table('users').select("*").eq("id", user['paired_with_id']).single().execute()
            partner = partner_resp.data

        return render_template('file_sharing.html', user=user, partner=partner)

    except Exception as e:
        flash(f"Error: {str(e)}", "danger")
        return redirect(url_for('login'))

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

if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    app.run(host=host, port=port, debug=True)
