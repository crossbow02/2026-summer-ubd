import openpyxl
import sqlite3
import json
import os
import re

def parse_adult(adult_str):
    if not adult_str:
        return None, None, None
    adult_str = str(adult_str).strip()
    if not adult_str:
        return None, None, None
    
    # Expected format: "Name / Phone"
    if "/" in adult_str:
        parts = adult_str.split("/")
        name = parts[0].strip()
        phone = parts[1].strip()
    else:
        # Fallback if delimiter is missing
        name = adult_str
        phone = ""
    
    # Clean phone numbers to get last 4 digits
    last4 = None
    if phone:
        # Extract digits
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 4:
            last4 = digits[-4:]
        else:
            last4 = digits
    
    return name, phone, last4

def init_db():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(base_dir, "database.db")
    
    # Find Excel file dynamically in the same directory to avoid NFC/NFD encoding mismatches
    excel_files = [f for f in os.listdir(base_dir) if f.endswith('.xlsx')]
    if not excel_files:
        raise FileNotFoundError("Excel file (.xlsx) not found in directory.")
    excel_path = os.path.join(base_dir, excel_files[0])
    
    # Remove existing db to re-initialize clean
    if os.path.exists(db_path):
        os.remove(db_path)
        print("Existing database removed.")
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_num INTEGER,
        adult1_name TEXT NOT NULL,
        adult1_phone TEXT,
        adult1_last4 TEXT,
        adult2_name TEXT,
        adult2_phone TEXT,
        adult2_last4 TEXT,
        children TEXT, -- JSON string array
        role TEXT DEFAULT 'user',
        team TEXT DEFAULT '미지정'
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS family_profiles (
        user_id INTEGER PRIMARY KEY,
        one_liner TEXT,
        motivation TEXT,
        prayers TEXT,
        specialties TEXT,
        photo_path TEXT,
        ai_intro_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id INTEGER,
        author_name TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(profile_id) REFERENCES family_profiles(user_id)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS likes (
        profile_id INTEGER,
        user_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(profile_id, user_id),
        FOREIGN KEY(profile_id) REFERENCES family_profiles(user_id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    
    # Create target_children table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS target_children (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        age INTEGER,
        gender TEXT,
        photo_path TEXT,
        parents_church TEXT,
        notes TEXT,
        phone TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Create team_posts table
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

    # Create shared_schedules table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shared_schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        due_date TEXT,
        end_date TEXT,
        is_completed INTEGER DEFAULT 0,
        created_by TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Populate default schedule items
    default_tasks = [
        ('1차 준비 모임 및 오리엔테이션', '2026-07-05', '준비팀'),
        ('여름성경학교 세부 기획 및 공과 교재 준비', '2026-07-20', '준비팀'),
        ('선교 후원금 모금 및 티셔츠 사이즈 취합', '2026-07-30', '준비팀'),
        ('식사 메뉴 확정 및 식재료 구매 조율', '2026-08-01', '준비팀'),
        ('예배 콘티 확정 및 찬양 악보 공유', '2026-08-05', '준비팀'),
        ('선교 준비 최종 점검 및 짐 싸기', '2026-08-10', '준비팀'),
        ('둔포성결교회 여름 선교 사역 출발! 🚀', '2026-08-15', '준비팀')
    ]
    cursor.executemany("""
    INSERT INTO shared_schedules (title, due_date, created_by)
    VALUES (?, ?, ?)
    """, default_tasks)
    
    conn.commit()
    print("Database tables created and default schedule items populated successfully.")
    
    # Read Excel and populate users
    wb = openpyxl.load_workbook(excel_path, read_only=True)
    sheet = wb["Form Responses 1"]
    
    user_count = 0
    for i, row in enumerate(sheet.iter_rows(values_only=True)):
        # Skip header
        if i == 0:
            continue
        
        group_num = row[0]
        # Only parse rows where the first column is a valid district number
        if group_num is None or not isinstance(group_num, int):
            continue
            
        adult1_raw = row[1]
        adult2_raw = row[2]
        
        adult1_name, adult1_phone, adult1_last4 = parse_adult(adult1_raw)
        adult2_name, adult2_phone, adult2_last4 = parse_adult(adult2_raw)
        
        # Collect children details
        children_list = []
        for child_col in row[3:8]: # columns D to H (자녀 1 to 자녀 5)
            if child_col:
                child_str = str(child_col).strip()
                if child_str:
                    children_list.append(child_str)
                    
        children_json = json.dumps(children_list, ensure_ascii=False)
        
        # Determine role (정다운 and 이현민 are admin)
        role = 'user'
        if adult1_name in ['정다운', '이현민']:
            role = 'admin'
            
        cursor.execute("""
        INSERT INTO users (group_num, adult1_name, adult1_phone, adult1_last4, adult2_name, adult2_phone, adult2_last4, children, role)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (group_num, adult1_name, adult1_phone, adult1_last4, adult2_name, adult2_phone, adult2_last4, children_json, role))
        user_count += 1
        
    # Add Pastor 이현민 (담당 목사님, Admin)
    cursor.execute("""
    INSERT INTO users (group_num, adult1_name, adult1_phone, adult1_last4, adult2_name, adult2_phone, adult2_last4, children, role)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (0, '이현민', '010-0000-1953', '1953', None, None, None, '[]', 'admin'))
    user_count += 1
    
    # Seed 30 target children from PDF & Excel list
    default_children = [
        ("밀라나", 13, "여", "초 6\n\n🙏 기도제목: 토요일 부모님이 막내를 돌봐줘서 예배에 나오도록, 가족건강", "010-5596-8600"),
        ("유노나", 9, "여", "초 2\n\n🙏 기도제목: 하나님, 공부 잘하게 해 주세요.", "010-6597-2014"),
        ("김 안나", 13, "여", "초 6\n\n🙏 기도제목: 3월부터 안 나옴", "010-7515-8067"),
        ("리디야", 11, "여", "초 4\n\n🙏 기도제목: 다친 팔이 빨리 회복되게 해주세요.", "010-8028-1495"),
        ("캐롤리나", 10, "여", "초 3\n\n🙏 기도제목: 하나님을 끝까지 사랑해 주세요. ", "010-4244-1705"),
        ("신 바넷사", 11, "여", "초 4\n\n🙏 기도제목: 부모님 말씀 더 잘 듣고 우리 가족이 잘 살게 해주세요.", "010-3911-1225"),
        ("신 로베르트", 8, "여", "초 1\n\n🙏 기도제목: 공부를 하고싶어요", "010-3911-1225"),
        ("박 니키타", 13, "여", "초 6\n\n🙏 기도제목: 의사의 비전을 가지게 되었어요.", "010-5657-8486"),
        ("마샤(마리아)", 12, "여", "초 5\n\n🙏 기도제목: 독일, 아메리카 여행을 하도록", "010-82434-2102"),
        ("안 안나", 13, "여", "초 6\n\n🙏 기도제목: 건강을 위하여", "010-2225-8425"),
        ("카리나", 12, "여", "초 5\n\n🙏 기도제목: U.S.A 여행을 위하여 (희망)", "010-8113-2908"),
        ("슬라바", 14, "여", "중 1\n\n🙏 기도제목: 시험에 100점을 받고 싶어요.", "010-6465-5352"),
        ("채 빅토르", 15, "여", "중 2\n\n🙏 기도제목: 음식 (요리 제빵사)의 꿈을 위하여", "010-5946-8538"),
        ("카밀라", 15, "여", "중 2\n\n🙏 기도제목: 시험 잘 준비하여 좋은 결과 나오도록", "010-8407-1712"),
        ("박 베로니카", 15, "여", "둔포중 2\n\n🙏 기도제목: 기말 시험 잘 준비하도록", "010-5657-8486"),
        ("리야", 12, "여", "초 5\n\n🙏 기도제목: 안톤 같은 반 친구가 자꾸 밀고 괴롭혀요.", "010-8294-3133"),
        ("로만", 9, "여", "초 2\n\n🙏 기도제목: 타이타닉 타고 싶어요.", "010-8294-3133"),
        ("넬리", 12, "여", "초 5\n\n🙏 기도제목: 다른 교회 다님, 캠프에만 참여", "010-8338-1704"),
        ("욜라", 9, "여", "초 2\n\n🙏 기도제목: 다른 교회 다님, 캠프에만 참여", "010-8338-1704"),
        ("허 베라", 12, "여", "초 5\n\n🙏 기도제목: 엄마, 아빠 건강을 위하여", "010-3234-2551"),
        ("콘스탄틴", 12, "여", "초 5\n\n🙏 기도제목: 한국어 공부와 수학 이해력을 위하여", "010-5801-0831"),
        ("밀레나", 12, "여", "초 5\n\n🙏 기도제목: 지속적으로 예배에 나오도록", "010-6606-5590"),
        ("폴리나", 13, "여", "초 6\n\n🙏 기도제목: 공부 잘하고 숙제를 잘하고 싶어요, 엄마와 동생 건강", "010-2865-1612"),
        ("예바", 13, "여", "초 6\n\n🙏 기도제목: 한국어 공부와 엄마를 위하요", "010-8210-3882"),
        ("비올레타", 13, "여", "초 6\n\n🙏 기도제목: 사춘기 과정을 잘 지내도록", "010-8365-7504"),
        ("크세니아", 13, "여", "초 6\n\n🙏 기도제목: 예배에 나오도록", "010-9546-2034"),
        ("샤샤", 14, "여", "중 1\n\n🙏 기도제목: 돈, 운동", "010-5937-7343"),
        ("리엔", 13, "여", "초 6\n\n🙏 기도제목: 1월부터 안 나옴", "010-2187-8098"),
        ("비카", 11, "여", "초 4\n\n🙏 기도제목: 친구를 도와주는 비카가 되고, 가족을 위하여", None),
        ("황 니키타", 15, "여", "중 2\n\n🙏 기도제목: 이사한 곳에서 잘 적응하도록", "010-5741-7757")
    ]
    
    cursor.executemany("""
    INSERT INTO target_children (name, age, gender, photo_path, parents_church, notes, phone)
    VALUES (?, ?, ?, NULL, '모름', ?, ?)
    """, default_children)
    print(f"Successfully seeded {len(default_children)} target children into target_children table.")

    conn.commit()
    conn.close()
    print(f"Successfully loaded {user_count} families (including Pastor) into the database.")

if __name__ == "__main__":
    init_db()
