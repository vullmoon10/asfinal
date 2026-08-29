import os
import csv
import json
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
app.secret_key = 'autoscore-v3-super-secret-key'

# --- 1. 환경 설정 및 폴더/파일 경로 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
GRAPHS_DIR = os.path.join(BASE_DIR, 'graphs')
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

for directory in [DATA_DIR, RESULTS_DIR, GRAPHS_DIR, TEMPLATE_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

CSV_FILE = os.path.join(DATA_DIR, 'autoscore.csv')
USERS_FILE = os.path.join(DATA_DIR, 'users.csv')
STATE_FILE = os.path.join(DATA_DIR, 'active_state.json')
TODO_FILE = os.path.join(DATA_DIR, 'todos.json')
HIDDEN_SUBJECTS_FILE = os.path.join(DATA_DIR, 'hidden_subjects.json')

# --- 2. DB(파일) 초기화 세팅 ---
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['userid', 'password_hash'])

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'userid', 'subject', 'qcnt', 'ac', 'wrong', 'timer', 'qpm', 'mpq', 'accuracy'])

if not os.path.exists(STATE_FILE):
    with open(STATE_FILE, 'w', encoding='utf-8') as f: json.dump({}, f)

if not os.path.exists(TODO_FILE):
    with open(TODO_FILE, 'w', encoding='utf-8') as f: json.dump({}, f)

if not os.path.exists(HIDDEN_SUBJECTS_FILE):
    with open(HIDDEN_SUBJECTS_FILE, 'w', encoding='utf-8') as f: json.dump({}, f)

# --- 3. 기본 화면 및 파일 라우트 ---
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
        for row in csv.DictReader(f):
            if row['userid'] == userid:
                return jsonify({"success": False, "error": "이미 존재하는 아이디입니다."}), 400
    with open(USERS_FILE, mode='a', encoding='utf-8', newline='') as f:
        csv.writer(f).writerow([userid, generate_password_hash(password)])
    return jsonify({"success": True, "message": "가입 완료!"})

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json()
    userid = data.get('userid', '').strip()
    password = data.get('password', '')
    with open(USERS_FILE, mode='r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['userid'] == userid and check_password_hash(row['password_hash'], password):
                session['userid'] = userid
                return jsonify({"success": True, "userid": userid})
    return jsonify({"success": False, "error": "아이디/비밀번호 오류."}), 401

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.pop('userid', None)
    return jsonify({"success": True})

# --- 5. 과목 관리 및 숨김 API ---
@app.route('/api/subjects', methods=['GET'])
def api_subjects():
    if 'userid' not in session: return jsonify({"success": False}), 401
    
    with open(HIDDEN_SUBJECTS_FILE, 'r', encoding='utf-8') as f:
        hidden_db = json.load(f)
    hidden_list = hidden_db.get(session['userid'], [])
    
    subjects = set()
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row.get('userid') == session['userid'] and row.get('subject'):
                    subj = row.get('subject')
                    # 숨김 처리된 과목 및 하위 과목 필터링
                    is_hidden = any(subj == h or subj.startswith(h + '\\') for h in hidden_list)
                    if not is_hidden:
                        subjects.add(subj)
    return jsonify({"success": True, "subjects": list(subjects)})

@app.route('/api/subjects/hide', methods=['POST'])
def api_hide_subject():
    if 'userid' not in session: return jsonify({"success": False}), 401
    uid = session['userid']
    data = request.get_json()
    subject = data.get('subject', '').strip()
    
    with open(HIDDEN_SUBJECTS_FILE, 'r', encoding='utf-8') as f:
        hidden_db = json.load(f)
        
    if uid not in hidden_db: hidden_db[uid] = []
    if subject not in hidden_db[uid]:
        hidden_db[uid].append(subject)
        
    with open(HIDDEN_SUBJECTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(hidden_db, f, ensure_ascii=False)
        
    return jsonify({"success": True})

# --- 6. 타이머 API ---
@app.route('/api/start', methods=['POST'])
def api_start():
    if 'userid' not in session: return jsonify({"success": False}), 401
    data = request.get_json()
    subject = data.get('subject', '').strip()
    
    with open(STATE_FILE, 'r') as f: states = json.load(f)
    # 서버가 꺼져도 시간 측정이 유지되도록 로컬 파일에 백업
    states[session['userid']] = {"subject": subject, "start_time": time.time()}
    with open(STATE_FILE, 'w') as f: json.dump(states, f)
    
    return jsonify({"success": True})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    if 'userid' not in session: return jsonify({"success": False}), 401
    uid = session['userid']
    with open(STATE_FILE, 'r') as f: states = json.load(f)
    
    if uid not in states:
        return jsonify({"success": False, "error": "실행 중인 타이머가 없습니다."}), 400
        
    elapsed = time.time() - states[uid]['start_time']
    del states[uid]
    with open(STATE_FILE, 'w') as f: json.dump(states, f)
    
    return jsonify({"success": True, "timer": elapsed})

# --- 7. 결과 분석 및 대시보드 API ---
@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    if 'userid' not in session: return jsonify({"success": False}), 401
    uid = session['userid']
    data = request.get_json()
    subject = data.get('subject', '').strip()
    qcnt, ac, timer = int(data.get('qcnt', 0)), int(data.get('ac', 0)), float(data.get('timer', 0.0))
    
    if timer <= 0.0: return jsonify({"success": False, "error": "타이머 기록이 없습니다."}), 400
    
    wrong = qcnt - ac
    accuracy = (ac / qcnt) * 100
    qpm = qcnt / (timer / 60)
    mpq = timer / qcnt
    now = datetime.now()
    
    # CSV 저장
    with open(CSV_FILE, mode='a', encoding='utf-8', newline='') as f:
        csv.writer(f).writerow([now.strftime('%Y-%m-%d'), uid, subject, qcnt, ac, wrong, timer, qpm, mpq, accuracy])
    
    # TXT 결과지 생성
    txt_name = f"{uid}_{now.strftime('%Y-%m-%d_%H-%M-%S')}.txt"
    report = f"================================\n        AUTOSCORE V3\n================================\n사용자         : {uid}\n과목           : {subject}\n[RESULT]\n문제 수        : {qcnt}\n정답 수        : {ac}\n오답 수        : {wrong}\n정답률         : {accuracy:.2f}%\n[TIME]\n총 소요 시간   : int({timer//60})분 int({timer%60})초\n분당 문제 수   : {qpm:.2f}문제\n1문제당 시간   : {mpq:.2f}초\n================================"
    with open(os.path.join(RESULTS_DIR, txt_name), mode='w', encoding='utf-8') as f:
        f.write(report)
        
    generate_graphs(uid)
    return jsonify({"success": True, "results": {"subject": subject, "accuracy": accuracy, "qpm": qpm, "timer": timer, "mpq": mpq, "txt_file": txt_name}})

@app.route('/api/dashboard', methods=['GET'])
def api_dashboard():
    if 'userid' not in session: return jsonify({"success": False}), 401
    uid = session['userid']
    records = []
    
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row.get('userid') == uid:
                    records.append(row)
                    
    return jsonify({"success": True, "records": records})

@app.route('/api/records/delete', methods=['POST'])
def api_delete_record():
    if 'userid' not in session: return jsonify({"success": False}), 401
    uid = session['userid']
    data = request.get_json()
    
    target_date = data.get('date')
    target_subject = data.get('subject')
    target_timer = str(data.get('timer'))
    
    rows = []
    deleted = False
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header:
                rows.append(header)
            for row in reader:
                # CSV 구조: ['date', 'userid', 'subject', 'qcnt', 'ac', 'wrong', 'timer', 'qpm', 'mpq', 'accuracy']
                if not deleted and len(row) > 6 and row[1] == uid and row[0] == target_date and row[2] == target_subject and row[6] == target_timer:
                    deleted = True # 딱 하나만 찾아서 삭제합니다.
                    continue
                rows.append(row)
                
        if deleted:
            with open(CSV_FILE, mode='w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                writer.writerows(rows)
            generate_graphs(uid) # 삭제 후 그래프를 다시 그립니다.
            return jsonify({"success": True})
            
    return jsonify({"success": False, "error": "기록을 찾을 수 없습니다."}), 404

# --- 8. 투두(To-Do) 리스트 API ---
@app.route('/api/todos', methods=['GET', 'POST'])
def api_todos():
    if 'userid' not in session: return jsonify({"success": False}), 401
    uid = session['userid']
    
    with open(TODO_FILE, 'r', encoding='utf-8') as f: todos_db = json.load(f)
    if uid not in todos_db: todos_db[uid] = []
        
    if request.method == 'GET':
        return jsonify({"success": True, "todos": todos_db[uid]})
        
    if request.method == 'POST':
        task = request.get_json().get("task", "").strip()
        new_todo = {"id": str(int(time.time() * 1000)), "task": task, "completed": False}
        todos_db[uid].append(new_todo)
        with open(TODO_FILE, 'w', encoding='utf-8') as f: json.dump(todos_db, f, ensure_ascii=False)
        return jsonify({"success": True, "todo": new_todo})

@app.route('/api/todos/<todo_id>', methods=['PUT', 'DELETE'])
def api_todo_action(todo_id):
    if 'userid' not in session: return jsonify({"success": False}), 401
    uid = session['userid']
    
    with open(TODO_FILE, 'r', encoding='utf-8') as f: todos_db = json.load(f)
    if uid not in todos_db: return jsonify({"success": False}), 404
    
    if request.method == 'PUT':
        for t in todos_db[uid]:
            if t['id'] == todo_id:
                t['completed'] = not t['completed']
                break
    elif request.method == 'DELETE':
        todos_db[uid] = [t for t in todos_db[uid] if t['id'] != todo_id]
        
    with open(TODO_FILE, 'w', encoding='utf-8') as f: json.dump(todos_db, f, ensure_ascii=False)
    return jsonify({"success": True})

# --- 9. 열품타(실시간 및 랭킹) API ---
@app.route('/api/yeolpumta/live', methods=['GET'])
def api_yeolpumta_live():
    with open(STATE_FILE, 'r') as f: states = json.load(f)
    now = time.time()
    live = [{"userid": u, "subject": d["subject"], "elapsed": now - d["start_time"]} for u, d in states.items()]
    return jsonify({"success": True, "live_users": sorted(live, key=lambda x: x["elapsed"], reverse=True)})

# --- 10. 그래프 생성 엔진 ---
def generate_graphs(uid):
    sessions, accuracies, qpms = [], [], []
    try:
        with open(CSV_FILE, mode='r', encoding='utf-8') as f:
            idx = 1
            for row in csv.DictReader(f):
                if row.get('userid') == uid:
                    sessions.append(idx)
                    accuracies.append(float(row['accuracy']))
                    qpms.append(float(row['qpm']))
                    idx += 1
    except: return
    if not sessions: return

    plt.style.use('bmh')
    
    plt.figure(figsize=(6, 4))
    plt.plot(sessions, accuracies, marker='o', color='#4f46e5')
    plt.title('Accuracy (%)')
    plt.savefig(os.path.join(GRAPHS_DIR, f'accuracy_{uid}.png'))
    
    plt.figure(figsize=(6, 4))
    plt.plot(sessions, qpms, marker='o', color='#10b981')
    plt.title('QPM (Questions Per Min)')
    plt.savefig(os.path.join(GRAPHS_DIR, f'qpm_{uid}.png'))
    
    plt.close('all') # 메모리 누수 방지용

# --- 서버 구동 ---
def open_browser():
    time.sleep(1.5)
    webbrowser.open_new("http://127.0.0.1:5000")

if __name__ == '__main__':
    threading.Thread(target=open_browser).start()
    app.run(host='127.0.0.1', port=5000, debug=False)