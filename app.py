import os
import json
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'kmla-dashboard-secret-key-2024')

# 사용자 데이터 파일
# 데이터 저장 위치 (Render 영구 디스크를 쓰려면 DATA_DIR 환경변수를 디스크 마운트 경로로 지정)
DATA_DIR = os.getenv('DATA_DIR', '.')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
QUICK_FILE = os.path.join(DATA_DIR, 'quick_menu.json')
ADMIN_USER = 'admin'
MAX_QUICK = 8

# 전체 시스템 목록 (대시보드 카드 순서와 동일). 관리자 설정에서 주요 시스템으로 선택 가능
SYSTEMS = [
    {'id': 'auto-mail', 'group': 'school', 'name': '자동 발송 시스템', 'url': 'https://pdf-email-sender-1.onrender.com'},
    {'id': 'student-id', 'group': 'school', 'name': '학생증 재발급', 'url': 'https://knue20-kmla.github.io/Student-ID/'},
    {'id': 'budget', 'group': 'school', 'name': '프로젝트 예산 관리', 'url': 'https://knue20-kmla.github.io/budget'},
    {'id': 'curriculum', 'group': 'school', 'name': 'KMLA 교육과정 체험', 'url': 'https://kmla-curriculum.netlify.app'},
    {'id': 'equipment', 'group': 'school', 'name': '프로젝트 기자재 관리자', 'url': 'https://equipment-manager-redirect.onrender.com'},
    {'id': 'exam-all', 'group': 'school', 'name': '모의고사 분석(전학년)', 'url': 'https://knue20-kmla.github.io/kmla-exam/'},
    {'id': 'minjok-score', 'group': 'school', 'name': '입학 내신 계산기', 'url': 'https://knue20-kmla.github.io/minjok-score/'},
    {'id': 'test-schedule', 'group': 'school', 'name': '정기시험 시간표', 'url': 'https://knue20-kmla.github.io/Test-Schedule/'},
    {'id': 'budget-gas', 'group': 'school', 'name': '예산 관리', 'url': 'https://script.google.com/macros/s/AKfycbx5SIuP6sB4A_n3hTDaV2SJfhAMjeYeul-VYC3uXCPUPnh4JcWVXFKDtODvZCCLwICF/exec'},
    {'id': 'study', 'group': 'class', 'name': '자습 관리 시스템', 'url': 'https://knue20-kmla.github.io/STUDY/'},
    {'id': 'creative', 'group': 'class', 'name': '창의적 체험활동 관리', 'url': 'https://knue20-kmla.github.io/creative-activity/'},
    {'id': 'record-analysis', 'group': 'class', 'name': '생기부 분석 시스템', 'url': 'https://famished-disclose-phonics.ngrok-free.dev/'},
    {'id': 'exam-class', 'group': 'class', 'name': '모의고사 분석 시스템', 'url': 'https://knue20-kmla.github.io/exam-anlysis/login.html'},
    {'id': 'transcript', 'group': 'class', 'name': '학교생활기록부 조회', 'url': 'https://knue20-kmla.github.io/transcript/'},
    {'id': 'eval-plan', 'group': 'subject', 'name': '교수학습평가계획서', 'url': 'https://knue20-kmla.github.io/eval-plan-app/'},
    {'id': 'history-db', 'group': 'subject', 'name': '한국사 수업 DB', 'url': 'https://kmla-history.party'},
    {'id': 'history-question', 'group': 'subject', 'name': '한국사 질문 DB(2026-1)', 'url': 'https://script.google.com/macros/s/AKfycbzaRk2xqq8D8GFPMl6w5m2xWHqGCmsZqOgZsdhF7ARlhkC9bcX8XsaY5yKCyV0kze-1/exec?page=teacher'},
    {'id': 'history-board', 'group': 'subject', 'name': '한국사 질문/수행 DB', 'url': 'https://kmla-history.party/board'},
]
SYSTEM_BY_ID = {s['id']: s for s in SYSTEMS}
GROUP_LABELS = [('school', '학교 업무 시스템'), ('class', '학급 업무 시스템'), ('subject', '교과 업무 시스템')]

# 대시보드 카드에 표시할 아이콘과 한 줄 설명
SYSTEM_META = {
    'auto-mail': ('📧', '성적표·문서를 학생 이메일로 자동 발송'),
    'student-id': ('🎫', '학생증 재발급 신청 관리'),
    'budget': ('💰', '학생 프로젝트 예산 신청 및 관리'),
    'curriculum': ('🧭', '선택 과목과 진로를 연계해 보는 교육과정 설계 앱'),
    'equipment': ('🧰', '기자재 등록, 대여·반납 승인 관리'),
    'exam-all': ('📈', '1~3학년 전체 모의고사 성적 조회·분석'),
    'minjok-score': ('🎓', '2027학년도 1단계 교과성적·출결 점수 계산'),
    'test-schedule': ('📅', '중간·기말고사 시간표 자동 생성과 공유'),
    'budget-gas': ('🧾', '예산 신청·집행 현황 (Apps Script)'),
    'study': ('📚', '학생 자습 기록, 통계, 출석 관리'),
    'creative': ('✨', '창체 활동 기록·조회·통계 관리'),
    'record-analysis': ('📝', '생활기록부 작성·분석 도구'),
    'exam-class': ('📊', '모의고사 성적 분석과 통계'),
    'transcript': ('📋', '학생 생기부 조회와 세특 분석'),
    'eval-plan': ('🗂️', '교과별 교수학습·평가계획서 작성과 내보내기'),
    'history-db': ('📄', '한국사 교과서 이북, 수업 PPT, 게시판'),
    'history-question': ('💬', '질문·수행 글쓰기, 교사 관찰 기록 관리'),
    'history-board': ('🗒️', '반·학생별 질문과 수행평가 확인·관리'),
}
for _s in SYSTEMS:
    _s['icon'], _s['desc'] = SYSTEM_META[_s['id']]

def system_groups():
    return [{'key': key, 'label': label, 'systems': [s for s in SYSTEMS if s['group'] == key]}
            for key, label in GROUP_LABELS]
DEFAULT_QUICK = ['curriculum', 'student-id', 'equipment', 'exam-class', 'test-schedule', 'history-db']

def load_quick_ids():
    if os.path.exists(QUICK_FILE):
        try:
            with open(QUICK_FILE, 'r', encoding='utf-8') as f:
                ids = json.load(f)
            return [i for i in ids if i in SYSTEM_BY_ID][:MAX_QUICK]
        except (ValueError, OSError):
            pass
    return list(DEFAULT_QUICK)

def save_quick_ids(ids):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(QUICK_FILE, 'w', encoding='utf-8') as f:
        json.dump(ids, f, ensure_ascii=False)

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
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        if session['username'] != ADMIN_USER:
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return render_template('landing.html')

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
    quick_ids = load_quick_ids()
    quick_systems = [SYSTEM_BY_ID[i] for i in quick_ids]
    return render_template('dashboard.html', username=session['username'],
                           is_admin=session['username'] == ADMIN_USER,
                           quick_systems=quick_systems,
                           groups=system_groups())

@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    success = None
    error = None
    if request.method == 'POST':
        chosen = set(request.form.getlist('quick'))
        ids = [s['id'] for s in SYSTEMS if s['id'] in chosen]
        if len(ids) > MAX_QUICK:
            error = '주요 시스템은 최대 %d개까지 선택할 수 있습니다.' % MAX_QUICK
        else:
            save_quick_ids(ids)
            success = '주요 시스템 설정이 저장되었습니다.'
    selected = set(load_quick_ids())
    groups = system_groups()
    return render_template('admin_settings.html', groups=groups, selected=selected,
                           max_quick=MAX_QUICK, success=success, error=error)

@app.route('/history-question')
def history_question_student():
    return render_template('history_question_student.html')

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
