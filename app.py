import os
import json
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'kmla-dashboard-secret-key-2024')

# 사용자 데이터 파일
USERS_FILE = 'users.json'

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    else:
        # 초기 사용자 생성
        users = {
            'admin': generate_password_hash('admin1234')
        }
        save_users(users)
        return users

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        users = load_users()

        if username in users and check_password_hash(users[username], password):
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='아이디 또는 비밀번호가 올바르지 않습니다.')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', username=session['username'])

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if new_password != confirm_password:
            return render_template('change_password.html', error='새 비밀번호가 일치하지 않습니다.')

        users = load_users()
        username = session['username']

        if not check_password_hash(users[username], current_password):
            return render_template('change_password.html', error='현재 비밀번호가 올바르지 않습니다.')

        users[username] = generate_password_hash(new_password)
        save_users(users)

        return render_template('change_password.html', success='비밀번호가 성공적으로 변경되었습니다.')

    return render_template('change_password.html')

if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    app.run(debug=True, port=5001)
