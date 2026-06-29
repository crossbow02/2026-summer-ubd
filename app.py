import os
import sqlite3
import json
import urllib.request
import urllib.parse
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, 'database.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
SLIDES_FOLDER = os.path.join(BASE_DIR, '사역소개 PT')

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB limit

# Create upload folder if not exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Database Self-Migration helper for Target Children and Teams
def migrate_db():
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        
        # 1. Target children table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS target_children (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            photo_path TEXT,
            parents_church TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 2. Team posts table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS team_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_name TEXT NOT NULL,
            author_name TEXT NOT NULL,
            content TEXT NOT NULL,
            file_path TEXT,
            file_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 3. Add team column to users table if not exists
        cursor.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'team' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN team TEXT DEFAULT '미지정'")
            print("Added 'team' column to 'users' table.")
            
        conn.commit()
        conn.close()
        print("Database migrated successfully (target_children, team_posts, and users team column checked).")
    except Exception as e:
        print("Database migration failed:", e)

migrate_db()

# Database helpers
@app.template_filter('list_from_json')
def list_from_json(json_str):
    if not json_str:
        return []
    try:
        return json.loads(json_str)
    except Exception:
        return []

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def execute_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    cur.close()

# Auth Middleware
@app.before_request
def check_login():
    # Allow login, static files, slide service, and git webhooks without login
    allowed_routes = ['login', 'static', 'serve_slide', 'github_webhook']
    if request.endpoint not in allowed_routes and 'user_id' not in session:
        return redirect(url_for('login'))

# Serving presentation slides
@app.route('/slides/<filename>')
def serve_slide(filename):
    return send_from_directory(SLIDES_FOLDER, filename)

# AI generation function
def call_gemini_api(api_key, name, one_liner, motivation, prayers, specialties, children_list):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    children_str = ", ".join(children_list) if children_list else "부부"
    prompt = f"""
역할: 기독교 여름 성경학교 및 아웃리치 선교팀원들의 가정 소개글을 정제하고 매력적인 스토리로 작성하는 전문 작가 및 목회자.
입력 데이터:
- 아빠/가장 성함: {name}
- 자녀 목록: {children_str}
- 우리 가족 한 줄 소개: {one_liner}
- 참여 계기 및 기대: {motivation}
- 우리 가족의 기도제목: {prayers}
- 나누고 싶은 우리 가족의 매력/특기: {specialties}

작성 규칙:
1. 어조: 매우 따뜻하고 은혜로우며, 친근하고 격려가 넘치는 기독교 선교팀 소통 톤으로 작성해줘.
2. 구조: 아래의 4가지 파트로 구분해서 이모지를 적절히 섞어 예쁘게 작성해줘.
   - Part 1: 가족 인사 및 소개 (가족의 한 줄 소개를 자연스럽게 녹여내고, 자녀들과 아내를 소개)
   - Part 2: 선교에 임하는 기대와 마음 (참여 계기와 기대를 풍성하고 감동적으로 서술)
   - Part 3: 우리의 매력과 은사 (가족의 특기와 매력을 선교팀원들과 나누는 기쁨으로 표현)
   - Part 4: 중보기도 요청 (기도제목을 정리하며 중보기도를 부탁함)
3. 출력 형식: 마크다운(Markdown) 형식을 사용해서 소제목과 강조 표시(**) 등을 사용해 읽기 편하게 해줘. HTML 태그는 사용하지 마.
4. 분량: 800자 내외로 풍성하고 자연스러운 하나의 편지글처럼 다듬어줘.
"""

    req_data = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    
    headers = {'Content-Type': 'application/json'}
    req = urllib.request.Request(
        url,
        data=json.dumps(req_data).encode('utf-8'),
        headers=headers,
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = json.loads(response.read().decode('utf-8'))
            text = res_body['candidates'][0]['content']['parts'][0]['text']
            return text
    except Exception as e:
        print("Gemini API call failed, falling back to local synthesis:", e)
        return None

def generate_local_ai_text(name, one_liner, motivation, prayers, specialties, children_list):
    children_str = ", ".join(children_list) if children_list else "부부"
    children_part = f" 사랑하는 자녀들({children_str})과 함께" if children_list else " 믿음의 동역자인 부부가 함께"
    
    intro = f"""### 🌟 우리 가족을 소개합니다!
안녕하세요, 선교팀 여러분! 저희는 **{name} 성도님** 가정입니다. 
저희 가정은 이번 사역을 준비하며 **"{one_liner}"**라는 고백을 마음에 새겼습니다.{children_part} 이번 여름 8월 15~16일, 둔포성결교회의 고려인 아이들을 만나 예수님의 귀한 사랑을 나눌 생각에 벌써부터 마음이 설레고 기쁩니다.

### 💖 사역에 임하는 우리의 마음
{motivation}
하나님께서 예비하신 은혜를 기대하며, 저희 가정을 통해 고려인 아이들과 가정이 주님께 더 가까이 나아가는 마중물이 되기를 간절히 기도합니다.

### 🎨 우리 가족의 특별한 매력 & 은사
{specialties}
선교팀원들과 함께 기쁨으로 어우러져 서로를 돕고, 필요한 곳에서 묵묵히 동역하는 따뜻한 손길이 되겠습니다!

### 🙏 함께 마음 모아주실 기도제목
저희 가정이 선교지에서 지치지 않고 기쁨으로 사역할 수 있도록 아래 기도제목을 두고 함께 중보해주시길 부탁드립니다.
1. **성령 충만한 사역:** 고려인 아이들과 예배드릴 때 성령님의 깊은 만남이 있게 하소서.
2. **영육의 강건함:** 사역 기간 동안 날씨와 환경 속에 온 가족의 건강을 지켜주소서.
3. **가정의 기도:** {prayers}

러시아계 고려인 사역을 섬기는 모든 팀원들을 축복합니다. 현장에서 주님의 사랑으로 기쁘게 동역하길 원합니다. 함께해주셔서 감사합니다! 😊"""
    return intro

# Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
        
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        # Check against database
        user = query_db("""
            SELECT * FROM users 
            WHERE (adult1_name = ? AND adult1_last4 = ?) 
               OR (adult2_name = ? AND adult2_last4 = ?)
        """, (username, password, username, password), one=True)
        
        if user:
            session['user_id'] = user['id']
            # Store the matching logged in name (in case Adult 2 logged in)
            if user['adult1_name'] == username:
                session['name'] = user['adult1_name']
                session['phone'] = user['adult1_phone']
            else:
                session['name'] = user['adult2_name']
                session['phone'] = user['adult2_phone']
            session['role'] = user['role']
            session['group_num'] = user['group_num']
            return redirect(url_for('dashboard'))
        else:
            error = "이름 또는 비밀번호(전화번호 뒤 4자리)가 일치하지 않습니다."
            
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def dashboard():
    # Roster Stats and Families
    users = query_db("""
        SELECT u.*, p.photo_path, (p.user_id IS NOT NULL) as has_intro 
        FROM users u 
        LEFT JOIN family_profiles p ON u.id = p.user_id
        ORDER BY u.group_num, u.adult1_name
    """)
    
    # Calculate statistics
    total_families = len(users)
    completed_intros = sum(1 for u in users if u['has_intro'])
    completion_rate = round((completed_intros / total_families) * 100) if total_families > 0 else 0
    
    # Count adult & kids totals
    total_adults = 0
    total_kids = 0
    
    # Sex ratios calculation
    male_adult_names = ['김민웅', '조성필', '김종대', '허슬기', '신호상', '이재한', '김정휘', '이준구', '최중근', '박우성', '서재영', '허무길', '염태한', '정다운', '김진석', '이현민']
    male_kids = ['조민율', '류지우', '허윤', '허겸', '신하선', '이세온', '최온유', '허이안', '정유호', '김우주']
    
    male_adults = 0
    female_adults = 0
    male_kids_count = 0
    female_kids_count = 0
    
    import re
    for u in users:
        total_adults += 1 if u['adult1_name'] else 0
        total_adults += 1 if u['adult2_name'] else 0
        
        # Gender counts
        if u['adult1_name']:
            if u['adult1_name'] in male_adult_names:
                male_adults += 1
            else:
                female_adults += 1
        if u['adult2_name']:
            if u['adult2_name'] in male_adult_names:
                male_adults += 1
            else:
                female_adults += 1
                
        kids = json.loads(u['children']) if u['children'] else []
        total_kids += len(kids)
        
        for kid in kids:
            k_name = re.sub(r'\(.*?\)', '', kid).strip()
            if k_name in male_kids:
                male_kids_count += 1
            else:
                female_kids_count += 1
        
    return render_template('families.html', 
                           users=users, 
                           total_families=total_families, 
                           completed_intros=completed_intros, 
                           completion_rate=completion_rate,
                           total_adults=total_adults,
                           total_kids=total_kids,
                           male_adults=male_adults,
                           female_adults=female_adults,
                           male_kids=male_kids_count,
                           female_kids=female_kids_count,
                           current_user_id=session.get('user_id'),
                           current_name=session.get('name'))

@app.route('/intro')
def intro():
    # Ministry Slideshow Page
    # Gather slides from folder
    slides = []
    if os.path.exists(SLIDES_FOLDER):
        files = os.listdir(SLIDES_FOLDER)
        # Filter files ending with jpeg, jpg, png
        slide_files = [f for f in files if f.lower().endswith(('.jpeg', '.jpg', '.png'))]
        # Sort slides by name
        slide_files.sort()
        slides = slide_files
    return render_template('intro.html', slides=slides)

@app.route('/family/edit', methods=['GET', 'POST'])
def family_edit():
    user_id = session['user_id']
    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    profile = query_db("SELECT * FROM family_profiles WHERE user_id = ?", (user_id,), one=True)
    
    if request.method == 'POST':
        one_liner = request.form.get('one_liner', '').strip()
        motivation = request.form.get('motivation', '').strip()
        prayers = request.form.get('prayers', '').strip()
        specialties = request.form.get('specialties', '').strip()
        team = request.form.get('team', '미지정').strip()
        
        # Save team selection to users table
        execute_db("UPDATE users SET team = ? WHERE id = ?", (team, user_id))
        
        # Photo handling
        photo_path = profile['photo_path'] if profile else None
        file = request.files.get('family_photo')
        if file and file.filename != '':
            filename = secure_filename(f"family_{user_id}_{int(datetime.now().timestamp())}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            photo_path = f"/static/uploads/{filename}"
            
        # Get AI Intro text (dynamic generate)
        ai_intro_text = request.form.get('ai_intro_text', '').strip()
        if not ai_intro_text:
            # Fallback if Javascript didn't generate beforehand
            children_list = json.loads(user['children']) if user['children'] else []
            api_key = os.environ.get('GEMINI_API_KEY')
            if api_key:
                ai_intro_text = call_gemini_api(api_key, user['adult1_name'], one_liner, motivation, prayers, specialties, children_list)
            if not ai_intro_text:
                ai_intro_text = generate_local_ai_text(user['adult1_name'], one_liner, motivation, prayers, specialties, children_list)
        
        # Update or Insert
        if profile:
            execute_db("""
                UPDATE family_profiles 
                SET one_liner = ?, motivation = ?, prayers = ?, specialties = ?, photo_path = ?, ai_intro_text = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (one_liner, motivation, prayers, specialties, photo_path, ai_intro_text, user_id))
        else:
            execute_db("""
                INSERT INTO family_profiles (user_id, one_liner, motivation, prayers, specialties, photo_path, ai_intro_text)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, one_liner, motivation, prayers, specialties, photo_path, ai_intro_text))
            
        return redirect(url_for('gallery'))
        
    return render_template('family_edit.html', user=user, profile=profile)

@app.route('/family/generate', methods=['POST'])
def family_generate():
    user_id = session['user_id']
    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    
    data = request.json or {}
    one_liner = data.get('one_liner', '').strip()
    motivation = data.get('motivation', '').strip()
    prayers = data.get('prayers', '').strip()
    specialties = data.get('specialties', '').strip()
    
    children_list = json.loads(user['children']) if user['children'] else []
    
    # Try calling Gemini API if key is present
    api_key = os.environ.get('GEMINI_API_KEY')
    ai_text = None
    if api_key:
        ai_text = call_gemini_api(api_key, user['adult1_name'], one_liner, motivation, prayers, specialties, children_list)
        
    if not ai_text:
        ai_text = generate_local_ai_text(user['adult1_name'], one_liner, motivation, prayers, specialties, children_list)
        
    return jsonify({'ai_text': ai_text})

@app.route('/gallery')
def gallery():
    # Fetch profiles with user details, likes count, comments count, and checking if current user liked
    current_user_id = session['user_id']
    
    profiles = query_db("""
        SELECT p.*, u.adult1_name, u.adult2_name, u.children, u.group_num,
               (SELECT COUNT(*) FROM likes WHERE profile_id = p.user_id) as likes_count,
               (SELECT COUNT(*) FROM likes WHERE profile_id = p.user_id AND user_id = ?) as has_liked
        FROM family_profiles p
        JOIN users u ON p.user_id = u.id
        ORDER BY p.created_at DESC
    """, (current_user_id,))
    
    # Fetch all comments for these profiles
    comments = query_db("""
        SELECT c.*, u.id as user_id 
        FROM comments c
        LEFT JOIN users u ON c.author_name = u.adult1_name OR c.author_name = u.adult2_name
        ORDER BY c.created_at ASC
    """)
    
    # Group comments by profile_id
    comments_by_profile = {}
    for c in comments:
        pid = c['profile_id']
        if pid not in comments_by_profile:
            comments_by_profile[pid] = []
        comments_by_profile[pid].append(c)
        
    # Format children JSON in python for easy rendering
    formatted_profiles = []
    for p in profiles:
        p_dict = dict(p)
        p_dict['kids'] = json.loads(p['children']) if p['children'] else []
        p_dict['comments_list'] = comments_by_profile.get(p['user_id'], [])
        formatted_profiles.append(p_dict)
        
    return render_template('gallery.html', profiles=formatted_profiles, current_user_id=current_user_id, current_name=session['name'])

@app.route('/family/<int:id>/like', methods=['POST'])
def family_like(id):
    user_id = session['user_id']
    # Check if already liked
    like = query_db("SELECT * FROM likes WHERE profile_id = ? AND user_id = ?", (id, user_id), one=True)
    
    if like:
        execute_db("DELETE FROM likes WHERE profile_id = ? AND user_id = ?", (id, user_id))
        liked = False
    else:
        execute_db("INSERT INTO likes (profile_id, user_id) VALUES (?, ?)", (id, user_id))
        liked = True
        
    likes_count = query_db("SELECT COUNT(*) as count FROM likes WHERE profile_id = ?", (id,), one=True)['count']
    return jsonify({'liked': liked, 'likes_count': likes_count})

@app.route('/family/<int:id>/comment', methods=['POST'])
def family_comment(id):
    author_name = session['name']
    content = request.form.get('content', '').strip()
    
    if content:
        execute_db("INSERT INTO comments (profile_id, author_name, content) VALUES (?, ?, ?)", (id, author_name, content))
        
    return redirect(url_for('gallery'))

@app.route('/family/<int:id>/comment/delete/<int:comment_id>', methods=['POST'])
def delete_comment(id, comment_id):
    # Ensure current user is authorized (admin, comment author, or family profile owner)
    comment = query_db("SELECT * FROM comments WHERE id = ?", (comment_id,), one=True)
    if not comment:
        return redirect(url_for('gallery'))
        
    user_id = session['user_id']
    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    
    # Authorized names
    authorized_names = [user['adult1_name'], user['adult2_name']] if user else []
    
    # Owner of profile
    is_profile_owner = (user_id == id)
    is_comment_author = (comment['author_name'] in authorized_names)
    is_admin = (session.get('role') == 'admin')
    
    if is_profile_owner or is_comment_author or is_admin:
        execute_db("DELETE FROM comments WHERE id = ?", (comment_id,))
        
    return redirect(url_for('gallery'))

# Target Children routes
@app.route('/target-children')
def target_children():
    rows = query_db("SELECT * FROM target_children ORDER BY name")
    children = [dict(row) for row in rows]
    is_admin = (session.get('role') == 'admin')
    return render_template('target_children.html', children=children, is_admin=is_admin)

@app.route('/target-children/add', methods=['POST'])
def target_children_add():
    if session.get('role') != 'admin':
        return redirect(url_for('target_children'))
        
    name = request.form.get('name', '').strip()
    age = request.form.get('age', '').strip()
    age = int(age) if age.isdigit() else None
    gender = request.form.get('gender', '').strip()
    parents_church = request.form.get('parents_church', '모름').strip()
    notes = request.form.get('notes', '').strip()
    
    photo_path = None
    file = request.files.get('photo')
    if file and file.filename != '':
        filename = secure_filename(f"child_{int(datetime.now().timestamp())}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        photo_path = f"/static/uploads/{filename}"
        
    execute_db("""
        INSERT INTO target_children (name, age, gender, photo_path, parents_church, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, age, gender, photo_path, parents_church, notes))
    
    return redirect(url_for('target_children'))

@app.route('/target-children/edit/<int:id>', methods=['POST'])
def target_children_edit(id):
    if session.get('role') != 'admin':
        return redirect(url_for('target_children'))
        
    child = query_db("SELECT * FROM target_children WHERE id = ?", (id,), one=True)
    if not child:
        return redirect(url_for('target_children'))
        
    name = request.form.get('name', '').strip()
    age = request.form.get('age', '').strip()
    age = int(age) if age.isdigit() else None
    gender = request.form.get('gender', '').strip()
    parents_church = request.form.get('parents_church', '모름').strip()
    notes = request.form.get('notes', '').strip()
    
    photo_path = child['photo_path']
    file = request.files.get('photo')
    if file and file.filename != '':
        filename = secure_filename(f"child_{id}_{int(datetime.now().timestamp())}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        photo_path = f"/static/uploads/{filename}"
        
    execute_db("""
        UPDATE target_children 
        SET name = ?, age = ?, gender = ?, photo_path = ?, parents_church = ?, notes = ?
        WHERE id = ?
    """, (name, age, gender, photo_path, parents_church, notes, id))
    
    return redirect(url_for('target_children'))

@app.route('/target-children/delete/<int:id>', methods=['POST'])
def target_children_delete(id):
    if session.get('role') != 'admin':
        return redirect(url_for('target_children'))
        
    execute_db("DELETE FROM target_children WHERE id = ?", (id,))
    return redirect(url_for('target_children'))

# Team Board routes
@app.route('/team-boards', methods=['GET', 'POST'])
def team_boards():
    current_user_id = session['user_id']
    user = query_db("SELECT * FROM users WHERE id = ?", (current_user_id,), one=True)
    
    # Default to user's assigned team if valid, else default to '성경학교팀'
    user_team = user['team'] if user['team'] in ['성경학교팀', '식사준비팀', '예배팀'] else '성경학교팀'
    selected_team = request.args.get('team', user_team)
    if selected_team not in ['성경학교팀', '식사준비팀', '예배팀']:
        selected_team = '성경학교팀'
        
    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        file = request.files.get('file')
        
        file_path = None
        file_name = None
        if file and file.filename != '':
            file_name = secure_filename(file.filename)
            saved_filename = f"team_{selected_team}_{int(datetime.now().timestamp())}_{file_name}"
            file_path_full = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)
            file.save(file_path_full)
            file_path = f"/static/uploads/{saved_filename}"
            
        if content or file_path:
            author_name = session['name']
            execute_db("""
                INSERT INTO team_posts (team_name, author_name, content, file_path, file_name)
                VALUES (?, ?, ?, ?, ?)
            """, (selected_team, author_name, content, file_path, file_name))
            
        return redirect(url_for('team_boards', team=selected_team))
        
    # Fetch posts for this team
    posts = query_db("""
        SELECT * FROM team_posts 
        WHERE team_name = ? 
        ORDER BY created_at DESC
    """, (selected_team,))
    
    posts_list = [dict(p) for p in posts]
    
    # Fetch all members of this team
    team_members = query_db("""
        SELECT group_num, adult1_name, adult2_name, children 
        FROM users 
        WHERE team = ?
        ORDER BY group_num, adult1_name
    """, (selected_team,))
    
    formatted_members = []
    for m in team_members:
        m_dict = dict(m)
        m_dict['kids'] = json.loads(m['children']) if m['children'] else []
        formatted_members.append(m_dict)
        
    return render_template('team_boards.html',
                           posts=posts_list,
                           selected_team=selected_team,
                           team_members=formatted_members,
                           user_team=user['team'],
                           is_admin=(session.get('role') == 'admin'),
                           current_name=session['name'])

@app.route('/team-boards/delete/<int:post_id>', methods=['POST'])
def delete_team_post(post_id):
    post = query_db("SELECT * FROM team_posts WHERE id = ?", (post_id,), one=True)
    if not post:
        return redirect(url_for('team_boards'))
        
    user_id = session['user_id']
    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    authorized_names = [user['adult1_name'], user['adult2_name']] if user else []
    
    is_author = (post['author_name'] in authorized_names)
    is_admin = (session.get('role') == 'admin')
    
    if is_author or is_admin:
        if post['file_path']:
            try:
                full_path = os.path.join(BASE_DIR, post['file_path'].lstrip('/'))
                if os.path.exists(full_path):
                    os.remove(full_path)
            except Exception as e:
                print("Failed to delete team post file:", e)
                
        execute_db("DELETE FROM team_posts WHERE id = ?", (post_id,))
        
    return redirect(url_for('team_boards', team=post['team_name']))

# Continuous Deployment Webhook from GitHub
@app.route('/github-webhook', methods=['POST'])
def github_webhook():
    # Simple token check for security
    token = request.args.get('token')
    expected_token = os.environ.get('WEBHOOK_TOKEN') or 'yubadi_secret_token_1234'
    if token != expected_token:
        return jsonify({'status': 'unauthorized'}), 403
        
    import subprocess
    try:
        # 1. Run git pull
        result = subprocess.run(
            ['git', 'pull'], 
            cwd=BASE_DIR, 
            capture_output=True, 
            text=True, 
            check=True
        )
        
        # 2. Trigger Reload on PythonAnywhere by touching the WSGI file
        wsgi_status = "Not on PythonAnywhere"
        parts = BASE_DIR.split(os.sep)
        if len(parts) >= 3 and parts[1] == 'home':
            username = parts[2]
            wsgi_path = f"/var/www/{username}_pythonanywhere_com_wsgi.py"
            if os.path.exists(wsgi_path):
                os.utime(wsgi_path, None)  # updates modification time (touch)
                wsgi_status = f"WSGI touched: {wsgi_path}"
            else:
                wsgi_status = f"WSGI not found: {wsgi_path}"
                
        return jsonify({
            'status': 'success',
            'git_output': result.stdout,
            'wsgi_status': wsgi_status
        })
    except Exception as e:
        return jsonify({
            'status': 'failed',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)
