import os
import csv
import time
from datetime import datetime
import threading
import webbrowser
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from flask import Flask, request, jsonify, render_template, send_from_directory, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'autoscore-v2-super-secret-key'

# --- 1. 환경 설정 및 폴더/파일 자동 생성 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
GRAPHS_DIR = os.path.join(BASE_DIR, 'graphs')
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

CSV_FILE = os.path.join(DATA_DIR, 'autoscore.csv')
USERS_FILE = os.path.join(DATA_DIR, 'users.csv')

for directory in [DATA_DIR, RESULTS_DIR, GRAPHS_DIR, TEMPLATE_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['userid', 'password_hash'])

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'userid', 'subject', 'qcnt', 'ac', 'wrong', 'timer', 'qpm', 'mpq', 'accuracy'])

# --- 2. 상태 관리 ---
session_state = {
    "start_time": None,
    "is_running": False
}

active_users = {}

# --- 3. 라우팅 ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/graphs/<path:filename>')
def serve_graphs(filename):
    return send_from_directory(GRAPHS_DIR, filename)

@app.route('/results/<path:filename>')
def serve_results(filename):
    return send_from_directory(RESULTS_DIR, filename)

# --- 4. 인증(Auth) API ---
@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    if 'userid' in session:
        return jsonify({"logged_in": True, "userid": session['userid']})
    return jsonify({"logged_in": False})

@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    data = request.get_json()
    userid = data.get('userid', '').strip()
    password = data.get('password', '')
    
    if not userid or len(password) < 4:
        return jsonify({"success": False, "error": "아이디와 4자리 이상의 비밀번호를 입력하세요."}), 400

    with open(USERS_FILE, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['userid'] == userid:
                return jsonify({"success": False, "error": "이미 존재하는 아이디입니다."}), 400
                
    hashed_pwd = generate_password_hash(password)
    with open(USERS_FILE, mode='a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([userid, hashed_pwd])
        
    return jsonify({"success": True, "message": "회원가입이 완료되었습니다."})

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json()
    userid = data.get('userid', '').strip()
    password = data.get('password', '')
    
    with open(USERS_FILE, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['userid'] == userid and check_password_hash(row['password_hash'], password):
                session['userid'] = userid
                return jsonify({"success": True, "userid": userid})
                
    return jsonify({"success": False, "error": "아이디 또는 비밀번호가 일치하지 않습니다."}), 401

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    userid = session.pop('userid', None)
    if userid in active_users:
        del active_users[userid]
    return jsonify({"success": True})

# --- 5. 앱 핵심 API ---

# ★ 신규 기능: 내 누적 과목 목록 가져오기
@app.route('/api/subjects', methods=['GET'])
def api_subjects():
    if 'userid' not in session: 
        return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401
    
    current_user = session['userid']
    subjects = set()
    
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('userid') == current_user and row.get('subject'):
                    subjects.add(row.get('subject'))
                    
    return jsonify({"success": True, "subjects": list(subjects)})

@app.route('/api/start', methods=['POST'])
def api_start():
    if 'userid' not in session: return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401
    data = request.get_json()
    subject = data.get('subject', '').strip()
    if not subject: return jsonify({"success": False, "error": "과목을 입력해주세요."}), 400
        
    current_user = session['userid']
    now = time.time()
    
    session_state["start_time"] = now
    session_state["is_running"] = True
    
    active_users[current_user] = {
        "subject": subject,
        "start_time": now
    }
    
    return jsonify({"success": True})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    if 'userid' not in session: return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401
    if not session_state["is_running"] or session_state["start_time"] is None:
        return jsonify({"success": False, "error": "타이머가 실행 중이 아닙니다."}), 400
        
    current_user = session['userid']
    elapsed_time = time.time() - session_state["start_time"]
    
    session_state["is_running"] = False
    session_state["start_time"] = None
    
    if current_user in active_users:
        del active_users[current_user]
        
    return jsonify({"success": True, "timer": elapsed_time})

@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    if 'userid' not in session: 
        return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401
        
    current_user = session['userid']
    data = request.get_json()
    subject = data.get('subject', '').strip()
    
    try:
        qcnt = int(data.get('qcnt', 0))
        ac = int(data.get('ac', 0))
        timer = float(data.get('timer', 0.0))
    except ValueError:
        return jsonify({"success": False, "error": "숫자를 입력해주세요."}), 400
        
    if qcnt < 1: return jsonify({"success": False, "error": "문제 수는 1 이상입니다."}), 400
    if ac < 0 or ac > qcnt: return jsonify({"success": False, "error": "정답 수를 확인하세요."}), 400
    timer = max(timer, 0.001)
    
    wrong = qcnt - ac
    accuracy = (ac / qcnt) * 100
    qpm = qcnt / (timer / 60)
    mpq = timer / qcnt
    
    now = datetime.now()
    date_str_csv = now.strftime('%Y-%m-%d')
    date_str_file = now.strftime('%Y-%m-%d_%H-%M-%S')
    
    with open(CSV_FILE, mode='a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([date_str_csv, current_user, subject, qcnt, ac, wrong, timer, qpm, mpq, accuracy])
        
    txt_filename = f"{current_user}_{date_str_file}.txt"
    report_content = f"================================\n        AUTOSCORE V2\n================================\n사용자         : {current_user}\n과목           : {subject}\n[RESULT]\n문제 수        : {qcnt}\n정답 수        : {ac}\n오답 수        : {wrong}\n정답률         : {accuracy:.2f}%\n[TIME]\n총 소요 시간   : int({timer//60})분 int({timer%60})초\n분당 문제 수   : {qpm:.2f}문제\n1문제당 시간   : {mpq:.2f}초\n================================"
    with open(os.path.join(RESULTS_DIR, txt_filename), mode='w', encoding='utf-8') as f:
        f.write(report_content)
        
    generate_graphs(current_user)
    
    return jsonify({
        "success": True,
        "results": {
            "subject": subject, "qcnt": qcnt, "ac": ac, "wrong": wrong,
            "accuracy": accuracy, "timer": timer, "qpm": qpm, "mpq": mpq, "txt_file": txt_filename
        }
    })

@app.route('/api/dashboard', methods=['GET'])
def api_dashboard():
    if 'userid' not in session: return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    current_user = session['userid']
    records = []
    subject_time = {}
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_total = 0.0
    
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('userid') == current_user:
                    records.append(row)
                    
                    if row.get('date') == today_str:
                        timer_val = float(row.get('timer', 0))
                        today_total += timer_val
                        subj = row.get('subject', '미지정')
                        subject_time[subj] = subject_time.get(subj, 0) + timer_val

    return jsonify({
        "success": True, 
        "records": records, 
        "today_total": today_total,
        "subject_breakdown": subject_time
    })

# --- 열품타 전용 API ---
@app.route('/api/yeolpumta/live', methods=['GET'])
def api_yeolpumta_live():
    now = time.time()
    live_list = []
    for uid, data in active_users.items():
        elapsed = now - data["start_time"]
        live_list.append({
            "userid": uid,
            "subject": data["subject"],
            "elapsed": elapsed
        })
    live_list.sort(key=lambda x: x["elapsed"], reverse=True)
    return jsonify({"success": True, "live_users": live_list})

@app.route('/api/yeolpumta/ranking', methods=['GET'])
def api_yeolpumta_ranking():
    rank_type = request.args.get('type', 'daily') 
    today_str = datetime.now().strftime('%Y-%m-%d')
    user_stats = {}
    
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                uid = row.get('userid')
                if not uid: continue
                
                if rank_type == 'daily' and row.get('date') != today_str:
                    continue
                
                if uid not in user_stats:
                    user_stats[uid] = {"total_timer": 0.0, "total_qcnt": 0, "total_ac": 0}
                
                user_stats[uid]["total_timer"] += float(row['timer'])
                user_stats[uid]["total_qcnt"] += int(row['qcnt'])
                user_stats[uid]["total_ac"] += int(row['ac'])

    ranking_list = []
    for uid, stats in user_stats.items():
        acc = (stats["total_ac"] / stats["total_qcnt"] * 100) if stats["total_qcnt"] > 0 else 0
        ranking_list.append({
            "userid": uid,
            "total_timer": stats["total_timer"],
            "total_qcnt": stats["total_qcnt"],
            "accuracy": acc
        })

    ranking_list.sort(key=lambda x: x["total_timer"], reverse=True)
    return jsonify({"success": True, "ranking": ranking_list})

# --- 6. Matplotlib 그래프 ---
def generate_graphs(userid):
    sessions, accuracies, qpms, mpqs, corrects, wrongs = [], [], [], [], [], []
    try:
        with open(CSV_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            idx = 1
            for row in reader:
                if row.get('userid') == userid:
                    sessions.append(idx)
                    accuracies.append(float(row['accuracy']))
                    qpms.append(float(row['qpm']))
                    mpqs.append(float(row['mpq']))
                    corrects.append(int(row['ac']))
                    wrongs.append(int(row['wrong']))
                    idx += 1
    except Exception: return

    if not sessions: return

    plt.style.use('bmh')
    
    plt.figure(figsize=(6, 4))
    plt.plot(sessions, accuracies, marker='o', color='#4f46e5', linewidth=2)
    plt.title('Accuracy (%)')
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, f'accuracy_{userid}.png'))
    
    plt.figure(figsize=(6, 4))
    plt.plot(sessions, qpms, marker='o', color='#10b981', linewidth=2)
    plt.title('QPM (Questions Per Min)')
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, f'qpm_{userid}.png'))
    
    plt.figure(figsize=(6, 4))
    plt.plot(sessions, mpqs, marker='o', color='#f59e0b', linewidth=2)
    plt.title('MPQ (Sec Per Question)')
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, f'mpq_{userid}.png'))

    plt.figure(figsize=(6, 4))
    width = 0.35
    vis_sessions = sessions[-10:]
    vis_corrects = corrects[-10:]
    vis_wrongs = wrongs[-10:]
    x = range(len(vis_sessions))
    plt.bar([i - width/2 for i in x], vis_corrects, width, label='Correct', color='#3b82f6')
    plt.bar([i + width/2 for i in x], vis_wrongs, width, label='Wrong', color='#ef4444')
    plt.title('Correct vs Wrong (Last 10)')
    plt.xticks(x, vis_sessions)
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, f'correct_wrong_{userid}.png'))
    plt.close('all')

def open_browser():
    time.sleep(1.5)
    webbrowser.open_new("http://127.0.0.1:5000")

if __name__ == '__main__':
    threading.Thread(target=open_browser).start()
    app.run(host='127.0.0.1', port=5000, debug=False)