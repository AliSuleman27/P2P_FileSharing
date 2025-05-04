import random
import string
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import sys

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SECRET_KEY'] = 'secretkey'
db = SQLAlchemy(app)

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    pairing_key = db.Column(db.String(120), unique=True, nullable=True)
    paired_with_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    local_ip = db.Column(db.String(120), nullable=True)
    partner_ip = db.Column(db.String(120), nullable=True)

# Home
@app.route('/')
def index():
    users = User.query.all()
    return render_template('index.html', users=users)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password, password):
            flash("Invalid Credentials", "danger")
            return redirect(url_for('login'))

        user.local_ip = request.remote_addr
        db.session.commit()

        session['user_id'] = user.id
        return redirect(url_for('file_sharing'))

    return render_template('login.html')


# Generate pairing key via AJAX
@app.route('/generate_key', methods=['POST'])
def generate_key():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Generate new pairing key
    pairing_key = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    user.pairing_key = pairing_key
    db.session.commit()

    return jsonify({'pairing_key': pairing_key})

@app.route('/pair', methods=['POST'])
def pair():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    target_key = request.json.get('pairing_key')
    user = User.query.get(user_id)
    partner = User.query.filter_by(pairing_key=target_key).first()

    if not partner:
        return jsonify({'error': 'Invalid pairing key'}), 404

    # Capture the user's local IP (if not already captured)
    local_ip = request.remote_addr  # Get the IP of the client making the request

    # Pair both users with each other
    user.paired_with_id = partner.id
    partner.paired_with_id = user.id

    # Exchange local IPs between users
    user.local_ip = local_ip
    partner.local_ip = partner.local_ip  # The partner's IP should already be captured at login

    # Commit changes to the database
    db.session.commit()

    return jsonify({
        'status': 'paired',
        'partner_username': partner.username,
        'partner_ip': partner.local_ip
    })

# File Sharing Page
@app.route('/file_sharing', methods=['GET'])
def file_sharing():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = User.query.get(user_id)
    partner = User.query.get(user.paired_with_id) if user.paired_with_id else None

    return render_template('file_sharing.html', user=user, partner=partner)

# Signup
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        
        new_user = User(username=username, email=email, password=password)
        db.session.add(new_user)
        db.session.commit()
        
        flash("Account created successfully!", "success")
        return redirect(url_for('login'))
    
    return render_template('signup.html')

# Edit User
@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    user = User.query.get(id)
    
    if not user:
        flash("User not found", "danger")
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        user.username = request.form['username']
        user.email = request.form['email']
        if request.form['password']:
            user.password = generate_password_hash(request.form['password'])
        
        db.session.commit()
        flash("User details updated successfully!", "success")
        return redirect(url_for('index'))
    
    return render_template('edit.html', user=user)

# Delete User
@app.route('/delete/<int:id>', methods=['GET', 'POST'])
def delete(id):
    user = User.query.get(id)
    
    if not user:
        flash("User not found", "danger")
        return redirect(url_for('index'))
    
    db.session.delete(user)
    db.session.commit()
    flash("User deleted successfully", "success")
    return redirect(url_for('index'))

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    
    host = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    app.run(host=host, port=port, debug=True)
