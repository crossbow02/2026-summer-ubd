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

# 2026 유바디 2마을 여름선교를 위한 기도제목 (기도 릴레이 상단 고정 리스트)
PRAYER_TOPICS = [
    '우리가 만날 아이들을 위해 그리스도의 사랑을 품도록',
    '언어, 문화적 차이를 복음으로 허무는 지혜를 주시도록',
    '우리가 만날 아이들의 마음 문이 열리도록',
    '토요일/주일 사역의 현장과 프로그램이 은혜 가운데 진행되도록',
    '동참하는 가정(부모+자녀)들의 영적 결속과 하나가 되도록',
    '온누리 M센터와 조우현 선교사님(김온유 선교사님), 둔포성결교회 간의 긴밀한 동역이 되도록',
    '선교 이후에 계속적으로 일상의 선교사로 헌신하는 가정이 되도록',
    '물질과 재정이 꼭 필요한 곳에 쓰이며, 부족함 없이 채워지도록',
]

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
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Add phone column to target_children if not exists
        cursor.execute("PRAGMA table_info(target_children)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'phone' not in columns:
            cursor.execute("ALTER TABLE target_children ADD COLUMN phone TEXT")
            print("Added 'phone' column to 'target_children' table.")
        
        # Add new fields if not exists
        for col in ['nationality', 'korean_level', 'source_sheet', 'bible_school', 'water_play']:
            if col not in columns:
                if col in ['bible_school', 'water_play']:
                    cursor.execute(f"ALTER TABLE target_children ADD COLUMN {col} INTEGER DEFAULT 0")
                else:
                    cursor.execute(f"ALTER TABLE target_children ADD COLUMN {col} TEXT")
                print(f"Added '{col}' column to 'target_children' table.")
        
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
        if 'game_high_streak' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN game_high_streak INTEGER DEFAULT 0")
            print("Added 'game_high_streak' column to 'users' table.")
        if 'team2' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN team2 TEXT DEFAULT '미지정'")
            print("Added 'team2' column to 'users' table.")
        if 'is_team_leader' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN is_team_leader INTEGER DEFAULT 0")
            print("Added 'is_team_leader' column to 'users' table.")
        if 'is_team_leader2' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN is_team_leader2 INTEGER DEFAULT 0")
            print("Added 'is_team_leader2' column to 'users' table.")
            
        # 4. Create shared_schedules table
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
        
        # 5. Add end_date column to shared_schedules if not exists
        cursor.execute("PRAGMA table_info(shared_schedules)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'end_date' not in columns:
            cursor.execute("ALTER TABLE shared_schedules ADD COLUMN end_date TEXT")
            print("Added 'end_date' column to 'shared_schedules' table.")
            
        # 6. Ensure family_profiles table exists (safety for Render cold starts)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS family_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            one_liner TEXT,
            motivation TEXT,
            prayers TEXT,
            specialties TEXT,
            photo_path TEXT,
            ai_intro_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)

        # 7. Worship resources table (악보/찬양 자료)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS worship_resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link_url TEXT,
            file_path TEXT,
            resource_type TEXT DEFAULT 'link',
            description TEXT,
            uploaded_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # 8. Add last_page column to users (remembers each user's last visited page)
        cursor.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in cursor.fetchall()]
        if 'last_page' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN last_page TEXT")
            print("Added 'last_page' column to 'users' table.")

        # 9. Prayer relay table (기도 릴레이: 날짜별 담당 가정 + 기도제목 번호 + 가정이 직접 올리는 기도내용)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS prayer_relay (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prayer_date TEXT UNIQUE NOT NULL,
            assigned_family TEXT,
            topic_number INTEGER,
            is_special INTEGER DEFAULT 0,
            prayer_content TEXT,
            posted_by TEXT,
            updated_at TIMESTAMP
        )
        """)

        # Seed the prayer relay calendar (2026/7/13 ~ 8/16) on first run, from 기도릴레이 리스트.png
        cursor.execute("SELECT COUNT(*) FROM prayer_relay")
        if cursor.fetchone()[0] == 0:
            prayer_relay_seed = [
                ('2026-07-13', '김진석/민은숙 가정', 1, 0),
                ('2026-07-14', '정다운/김도희 가정', 2, 0),
                ('2026-07-15', '염대한/김금년 가정', 3, 0),
                ('2026-07-16', '허무길/천지연 가정', 4, 0),
                ('2026-07-17', '김민웅/김혜영 가정', 5, 0),
                ('2026-07-18', '조성필/천예연 가정', 6, 0),
                ('2026-07-19', '김종대/민슬기 가정', 7, 0),
                ('2026-07-20', '권경숙 가정', 8, 0),
                ('2026-07-21', '허슬기/전현주 가정', 1, 0),
                ('2026-07-22', '신호상/민혜인 가정', 2, 0),
                ('2026-07-23', '이재한/이리라 가정', 3, 0),
                ('2026-07-24', '김정휘/방지안 가정', 4, 0),
                ('2026-07-25', '이준구/고은선 가정', 5, 0),
                ('2026-07-26', '최중근/송경민 가정', 6, 0),
                ('2026-07-27', '박우성/송혜린 가정', 7, 0),
                ('2026-07-28', '서재영/장인경 가정', 8, 0),
                ('2026-07-29', '김진석/민은숙 가정', 5, 0),
                ('2026-07-30', '정다운/김도희 가정', 6, 0),
                ('2026-07-31', '염대한/김금년 가정', 7, 0),
                ('2026-08-01', '허무길/천지연 가정', 8, 0),
                ('2026-08-02', '김민웅/김혜영 가정', 1, 0),
                ('2026-08-03', '조성필/천예연 가정', 2, 0),
                ('2026-08-04', '김종대/민슬기 가정', 3, 0),
                ('2026-08-05', '권경숙 가정', 4, 0),
                ('2026-08-06', '허슬기/전현주 가정', 5, 0),
                ('2026-08-07', '신호상/민혜인 가정', 6, 0),
                ('2026-08-08', '이재한/이리라 가정', 7, 0),
                ('2026-08-09', '김정휘/방지안 가정', 8, 0),
                ('2026-08-10', '이준구/고은선 가정', 1, 0),
                ('2026-08-11', '최중근/송경민 가정', 2, 0),
                ('2026-08-12', '박우성/송혜린 가정', 3, 0),
                ('2026-08-13', '서재영/장인경 가정', 4, 0),
                ('2026-08-14', '이현민 목사님', None, 0),
                ('2026-08-15', '여름선교', None, 1),
                ('2026-08-16', '여름선교', None, 1),
            ]
            cursor.executemany("""
                INSERT INTO prayer_relay (prayer_date, assigned_family, topic_number, is_special)
                VALUES (?, ?, ?, ?)
            """, prayer_relay_seed)
            print(f"Successfully seeded {len(prayer_relay_seed)} days into prayer_relay table.")

        # 10. Prayer relay amens (기도제목에 대한 '아멘' 반응)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS prayer_amens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prayer_date TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(prayer_date, user_id)
        )
        """)

        # Check if target_children table is empty (seed default children on first startup)
        cursor.execute("SELECT COUNT(*) FROM target_children")
        children_count = cursor.fetchone()[0]
        if children_count < 55:
            cursor.execute('DELETE FROM target_children')
            cursor.execute("DELETE FROM sqlite_sequence WHERE name='target_children'")
            default_children = [
                ('리야', '초5', '여', '/static/uploads/child_48_리야.jpg', '모름', '🙏 기도제목: 안톤 같은 반 친구가 자꾸 밀고 괴롭혀요.', '010-8294-3133', '키르기스스탄', '중', '출석명단, 기도제목'),
                ('로만', '초3', '여', '/static/uploads/child_49_로만.jpg', '모름', '🙏 기도제목: 타이타닉 타고 싶어요.', '010-8294-3133', '키르기스스탄', '중', '출석명단, 기도제목'),
                ('밀라나', '초6', '여', '/static/uploads/child_3_1782872150_1__6_.jpg', '모름', '🙏 기도제목: 토요일 부모님이 막내를 돌봐줘서 예배에 나오도록, 가족건강', '010-8104-0911', '러시아', '상', '출석명단, 기도제목'),
                ('유노나', '초2', '여', '/static/uploads/child_34_유노나.jpg', '모름', '🙏 기도제목: 하나님, 공부 잘하게 해 주세요.', '010-6597-2014', '러시아', '중', '출석명단, 기도제목'),
                ('넬리', '초5', '여', '/static/uploads/child_50_넬리.jpg', '모름', '🙏 기도제목: 다른 교회 다님, 캠프에만 참여', '010-8338-1704', '카자흐스탄', '중', '출석명단, 기도제목'),
                ('욜라', '초2', '여', '/static/uploads/child_51_욜라.jpg', '모름', '🙏 기도제목: 다른 교회 다님, 캠프에만 참여', '010-8338-1704', '카자흐스탄', '', '출석명단, 기도제목'),
                ('허 베라', '초5', '여', '/static/uploads/child_52_허베라.jpg', '모름', '🙏 기도제목: 엄마, 아빠 건강을 위하여', '010-3234-2551', '우크라이나', '중', '출석명단, 기도제목'),
                ('김 안나', '초6', '여', '/static/uploads/child_35_김안나.jpg', '모름', '🙏 기도제목: 하나님, 항상 도와 주셔서 감사합니다.', '010-2187-0167', '러시아', '중', '출석명단, 기도제목'),
                ('리디야', '초4', '여', '/static/uploads/child_36_리디야.jpg', '모름', '🙏 기도제목: 다친 팔이 빨리 회복되게 해주세요.', '010-8028-1495', '러시아', '중', '출석명단, 기도제목'),
                ('캐롤리나', '초3', '여', '/static/uploads/child_37_캐롤리나.jpg', '모름', '🙏 기도제목: 하나님을 끝까지 사랑해 주세요.', '010-4244-1705', '카자흐스탄', '', '출석명단, 기도제목'),
                ('루슬란', '초4', '남', None, '모름', '🙏 기도제목: 예배에 규칙적으로 잘 나오도록', '010-8414-7343', '카자흐스탄', '상', '출석명단, 기도제목'),
                ('올레그', '초3', '남', None, '모름', '🙏 기도제목: 한국어 습득이 성장하도록', '', '카자흐스탄', '', '출석명단, 기도제목'),
                ('콘스탄틴', '초5', '여', '/static/uploads/child_53_콘스탄틴.jpg', '모름', '🙏 기도제목: 한국어 공부와 수학 이해력을 위하여', '010-5801-0831', '러시아', '중', '출석명단, 기도제목'),
                ('황 니키타', '중1', '남', None, '모름', '🙏 기도제목: 이사한 곳에서 잘 적응하도록', '010-5741-7757', '카자흐스탄', '중', '출석명단, 기도제목'),
                ('바넷사', '초4', '여', '/static/uploads/child_38_신바넷사.jpg', '모름', '🙏 기도제목: 부모님 말씀 더 잘 듣고 우리 가족이 잘 살게 해주세요.', '010-3911-1225', '우즈베키스탄', '', '출석명단, 기도제목'),
                ('로베르트', '초1', '여', '/static/uploads/child_39_신로베르트.jpg', '모름', '🙏 기도제목: 공부를 하고싶어요', '010-3911-1225', '우즈벡(한국)', '', '출석명단, 기도제목'),
                ('박 니키타', '초6', '여', '/static/uploads/child_40_박니키타.jpg', '모름', '🙏 기도제목: 의사의 비전을 가지게 되었어요.', '010-5657-8486', '러시아(한국)', '중', '출석명단, 기도제목'),
                ('박 베로니카', '둔포중2', '여', '/static/uploads/child_47_박베로니카.jpg', '모름', '🙏 기도제목: 기말 시험 잘 준비하도록', '010-5657-8486', '러시아', '상', '출석명단, 기도제목'),
                ('밀라나', '중2', '여', None, '모름', '', '010-5596-8600', '카자흐스타', '', '출석명단'),
                ('마샤(마리아)', '초5', '여', '/static/uploads/child_41_마샤(마리아).jpg', '모름', '🙏 기도제목: 독일, 아메리카 여행을 하도록', '010-82434-2102', '우즈베키스탄', '중', '출석명단, 기도제목'),
                ('슬라바', '중1', '여', '/static/uploads/child_44_슬라바.jpg', '모름', '🙏 기도제목: 시험에 100점을 받고 싶어요.', '010-6465-5352', '카자흐스탄', '상', '출석명단, 기도제목'),
                ('채 빅토르', '테크노 중2', '여', '/static/uploads/child_45_채빅토르.jpg', '모름', '🙏 기도제목: 음식 (요리 제빵사)의 꿈을 위하여', '010-5946-8538', '카자흐스탄', '상', '출석명단, 기도제목'),
                ('밀레나', '초5', '여', '/static/uploads/child_54_밀레나.jpg', '모름', '🙏 기도제목: 지속적으로 예배에 나오도록', '010-6606-5590', '우크라이나', '중', '출석명단, 기도제목'),
                ('벡술탄', '', '모름', None, '모름', '', '010-2748-4443', '카자흐스탄', '중', '출석명단'),
                ('안 안나', '초6', '여', '/static/uploads/child_42_안안나.jpg', '모름', '🙏 기도제목: 건강을 위하여', '010-2225-8425', '우즈베키스탄', '중', '출석명단, 기도제목'),
                ('폴리나', '초4', '여', '/static/uploads/child_55_폴리나.jpg', '모름', '🙏 기도제목: 공부 잘하고 숙제를 잘하고 싶어요, 엄마와 동생 건강', '010-2865-1612', '러시아', '', '출석명단, 기도제목'),
                ('이 예바', '초6', '여', None, '모름', '🙏 기도제목: 한국어 공부와 엄마를 위하요', '010-8210-3882', '', '중', '출석명단, 기도제목'),
                ('비올레타', '초6', '여', None, '모름', '🙏 기도제목: 사춘기 과정을 잘 지내도록', '010-8365-7504', '우즈베키스탄', '중', '출석명단, 기도제목'),
                ('김크세니아', '초6', '여', None, '모름', '🙏 기도제목: 예배에 나오도록', '010-9546-2034', '러시아', '', '출석명단, 기도제목'),
                ('크세니아', '초6', '여', '/static/uploads/child_58_크세니아.jpg', '모름', '', '010-2392-0114', '카자흐스탄', '', '출석명단'),
                ('카밀라', '중2', '여', '/static/uploads/child_46_카밀라.jpg', '모름', '🙏 기도제목: 시험 잘 준비하여 좋은 결과 나오도록', '010-8407-1712', '러시아', '', '출석명단, 기도제목'),
                ('제냐', '초4', '여', None, '모름', '🙏 기도제목: 3월부터 안 나옴', '010-5875-1509', '카자흐스탄', '', '출석명단, 장기결석, 기도제목'),
                ('에릭', '초4', '남', None, '모름', '🙏 기도제목: 3월부터 안 나옴', '010-9980-3066', '카자흐스탄', '', '출석명단, 기도제목'),
                ('데니스', '초5', '남', None, '모름', '🙏 기도제목: 3월부터 안 나옴', '010-8280-3903', '카자흐스탄', '', '출석명단, 기도제목'),
                ('알란', '초4', '남', None, '모름', '🙏 기도제목: 3월부터 안 나옴', '010-8322-7343', '카자흐스탄', '', '출석명단, 기도제목'),
                ('리엔', '초6', '여', '/static/uploads/child_60_리엔.jpg', '모름', '🙏 기도제목: 1월부터 안 나옴', '010-2187-8098', '', '', '출석명단, 기도제목'),
                ('김안나', '초4', '여', '/static/uploads/child_35_김안나.jpg', '모름', '🙏 기도제목: 3월부터 안 나옴', '010-7515-8067', '카자흐스탄', '', '출석명단, 기도제목'),
                ('카리나', '초5', '여', '/static/uploads/child_43_카리나.jpg', '모름', '🙏 기도제목: U.S.A 여행을 위하여 (희망)', '010-8113-2908', '', '', '출석명단, 기도제목'),
                ('샤샤', '중1', '여', '/static/uploads/child_59_샤샤.jpg', '모름', '🙏 기도제목: 돈, 운동', '010-8497-2308', '카자흐스탄', '', '출석명단, 기도제목'),
                ('손 올레샤', '초5', '여', None, '모름', '🙏 기도제목: 3월부터 안 나옴', '010-8380-6090', '러시아', '', '출석명단, 기도제목'),
                ('최 아나스타샤', '초5', '여', None, '모름', '🙏 기도제목: 3월부터 안 나옴', '010-6876-9960', '러시아', '', '출석명단, 기도제목'),
                ('샤샤', '초6', '모름', None, '모름', '', '010-5937-7343', '', '', '출석명단, 장기결석'),
                ('빅토리아', '', '모름', None, '모름', '', '010-7587-4661', '', '', '장기결석'),
                ('다이아나', '', '모름', None, '모름', '', '010-2754-6366', '', '', '장기결석'),
                ('예다슬', '', '모름', None, '모름', '', '010-9103-7886', '', '', '장기결석'),
                ('한 알엑산들', '', '모름', None, '모름', '', '010-8291-1933', '', '', '장기결석'),
                ('도미니크', '', '모름', None, '모름', '', '-', '', '', '장기결석'),
                ('김 거스댜', '', '모름', None, '모름', '', '010-2245-4308', '', '', '장기결석'),
                ('김 막심', '', '모름', None, '모름', '', '010-2352-2607', '', '', '장기결석'),
                ('아델리나', '', '모름', None, '모름', '', '010-9891-0586', '', '', '장기결석'),
                ('막심', '', '모름', None, '모름', '', '-', '', '', '장기결석'),
                ('아르투르', '', '모름', None, '모름', '', '010-5502-1600', '', '', '장기결석'),
                ('미카에', '', '모름', None, '모름', '', '010-2818-7308', '', '', '장기결석'),
                ('스파스', '', '모름', None, '모름', '', '', '', '', '장기결석'),
                ('티무르', '', '모름', None, '모름', '', '', '', '', '장기결석'),
                ('티모피', '초6', '모름', None, '모름', '', '010-4638-3742', '', '', '장기결석'),
                ('소피아', '', '모름', None, '모름', '', '010-8059-5723', '', '', '장기결석'),
                ('아나스타샤', '', '모름', None, '모름', '', '-', '', '', '장기결석'),
                ('알렉세이', '', '모름', None, '모름', '', '010-6529-1407', '', '', '장기결석'),
                ('마트베이', '', '모름', None, '모름', '', '010-4462-2592', '', '', '장기결석'),
                ('비카', '초4', '여', None, '모름', '🙏 기도제목: 친구를 도와주는 비카가 되고, 가족을 위하여', '', '', '', '기도제목'),
                ('다비드', '초2', '남', None, '모름', '🙏 기도제목: 나도 공부를 잘하고 싶어요, 한국어 공부', '', '', '', '기도제목'),
                ('다니엘', '중 1', '남', None, '모름', '🙏 기도제목: 하나님의 자비를 위하여', '', '', '', '기도제목'),
            ]
            cursor.executemany("""
                INSERT INTO target_children (name, grade, gender, photo_path, parents_church, notes, phone, nationality, korean_level, source_sheet)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, default_children)
            print(f"Successfully seeded {len(default_children)} default children into target_children table.")
        # Force update all existing children's genders to '여' and assign corrected photo paths
        # # cursor.execute("UPDATE target_children SET gender = '여'")
        cursor.execute("UPDATE target_children SET photo_path = '/static/uploads/child_41_마샤(마리아).jpg' WHERE name = '마샤(마리아)'")
        cursor.execute("UPDATE target_children SET photo_path = '/static/uploads/child_60_리엔.jpg' WHERE name = '리엔'")

        conn.commit()
        conn.close()
        print("Database migrated successfully (target_children, team_posts, shared_schedules, and users team column checked).")
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

# Remember each user's last visited page, so their next login can resume there
TRACKABLE_ENDPOINTS = {
    'dashboard', 'family_edit', 'gallery', 'intro', 'shared_schedule',
    'target_children', 'game', 'praise_dance', 'team_boards',
}

@app.before_request
def track_last_page():
    if request.method == 'GET' and request.endpoint in TRACKABLE_ENDPOINTS and 'user_id' in session:
        execute_db("UPDATE users SET last_page = ? WHERE id = ?", (request.path, session['user_id']))

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
저희 가정은 이번 사역을 준비하며 **"{one_liner}"**라는 고백을 마음에 새겼습니다.{children_part} 이번 여름 8월 15~16일, 둔포성결교회의 아이들을 만나 예수님의 귀한 사랑을 나눌 생각에 벌써부터 마음이 설레고 기쁩니다.

### 💖 사역에 임하는 우리의 마음
{motivation}
하나님께서 예비하신 은혜를 기대하며, 저희 가정을 통해 둔포 아이들과 가정이 주님께 더 가까이 나아가는 마중물이 되기를 간절히 기도합니다.

### 🎨 우리 가족의 특별한 매력 & 은사
{specialties}
선교팀원들과 함께 기쁨으로 어우러져 서로를 돕고, 필요한 곳에서 묵묵히 동역하는 따뜻한 손길이 되겠습니다!

### 🙏 함께 마음 모아주실 기도제목
저희 가정이 선교지에서 지치지 않고 기쁨으로 사역할 수 있도록 아래 기도제목을 두고 함께 중보해주시길 부탁드립니다.
1. **성령 충만한 사역:** 둔포 아이들과 예배드릴 때 성령님의 깊은 만남이 있게 하소서.
2. **영육의 강건함:** 사역 기간 동안 날씨와 환경 속에 온 가족의 건강을 지켜주소서.
3. **가정의 기도:** {prayers}

둔포 아이들 사역을 섬기는 모든 팀원들을 축복합니다. 현장에서 주님의 사랑으로 기쁘게 동역하길 원합니다. 함께해주셔서 감사합니다! 😊"""
    return intro

def resolve_user_landing_page(user):
    """일반 사용자의 로그인 후 이동 페이지: 마지막 열람 페이지가 있으면 그곳으로,
    없으면 준비 일정표(기도 릴레이 보기)로 안내한다."""
    if user['last_page']:
        return redirect(user['last_page'])
    return redirect(url_for('shared_schedule') + '#prayer-relay')

# Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('dashboard'))
        else:
            user = query_db("SELECT * FROM users WHERE id = ?", (session['user_id'],), one=True)
            return resolve_user_landing_page(user)

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

            # 리다이렉트 결정:
            # 관리자 → 참가 가정 명단(대시보드)
            # 일반 사용자 → 마지막 열람 페이지, 없으면 준비 일정표(기도 릴레이 보기)
            if user['role'] == 'admin':
                return redirect(url_for('dashboard'))
            else:
                return resolve_user_landing_page(user)
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

    return redirect(url_for('gallery') + f'#family-{id}')

@app.route('/family/<int:id>/comment/delete/<int:comment_id>', methods=['POST'])
def delete_comment(id, comment_id):
    # Ensure current user is authorized (admin, comment author, or family profile owner)
    comment = query_db("SELECT * FROM comments WHERE id = ?", (comment_id,), one=True)
    if not comment:
        return redirect(url_for('gallery') + f'#family-{id}')

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

    return redirect(url_for('gallery') + f'#family-{id}')

# Target Children routes
@app.route('/target-children')
def target_children():
    rows = query_db("""
        SELECT * FROM target_children 
        ORDER BY (CASE WHEN photo_path IS NOT NULL AND photo_path != '' THEN 0 ELSE 1 END) ASC, id ASC
    """)
    children = [dict(row) for row in rows]
    is_admin = (session.get('role') == 'admin')
    return render_template('target_children.html', children=children, is_admin=is_admin)

@app.route('/target-children/add', methods=['POST'])
def target_children_add():
    if session.get('role') != 'admin':
        return redirect(url_for('target_children'))
        
    name = request.form.get('name', '').strip()
    grade = request.form.get('grade', '').strip()
    gender = request.form.get('gender', '').strip()
    parents_church = request.form.get('parents_church', '모름').strip()
    notes = request.form.get('notes', '').strip()
    phone = request.form.get('phone', '').strip()
    nationality = request.form.get('nationality', '').strip()
    korean_level = request.form.get('korean_level', '').strip()
    source_sheet = request.form.get('source_sheet', '').strip()
    
    photo_path = None
    file = request.files.get('photo')
    if file and file.filename != '':
        filename = secure_filename(f"child_{int(datetime.now().timestamp())}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        photo_path = f"/static/uploads/{filename}"
        
    execute_db("""
        INSERT INTO target_children (name, grade, gender, photo_path, parents_church, notes, phone, nationality, korean_level, source_sheet)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, grade, gender, photo_path, parents_church, notes, phone, nationality, korean_level, source_sheet))
    
    return redirect(url_for('target_children'))

@app.route('/target-children/edit/<int:id>', methods=['POST'])
def target_children_edit(id):
    if session.get('role') != 'admin':
        return redirect(url_for('target_children'))
        
    child = query_db("SELECT * FROM target_children WHERE id = ?", (id,), one=True)
    if not child:
        return redirect(url_for('target_children'))
        
    name = request.form.get('name', '').strip()
    grade = request.form.get('grade', '').strip()
    gender = request.form.get('gender', '').strip()
    parents_church = request.form.get('parents_church', '모름').strip()
    notes = request.form.get('notes', '').strip()
    phone = request.form.get('phone', '').strip()
    nationality = request.form.get('nationality', '').strip()
    korean_level = request.form.get('korean_level', '').strip()
    source_sheet = request.form.get('source_sheet', '').strip()
    
    photo_path = child['photo_path']
    file = request.files.get('photo')
    if file and file.filename != '':
        filename = secure_filename(f"child_{id}_{int(datetime.now().timestamp())}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        photo_path = f"/static/uploads/{filename}"
        
    execute_db("""
        UPDATE target_children 
        SET name = ?, grade = ?, gender = ?, photo_path = ?, parents_church = ?, notes = ?, phone = ?, nationality = ?, korean_level = ?, source_sheet = ?
        WHERE id = ?
    """, (name, grade, gender, photo_path, parents_church, notes, phone, nationality, korean_level, source_sheet, id))
    
    return redirect(url_for('target_children'))

@app.route('/target-children/delete/<int:id>', methods=['POST'])
def target_children_delete(id):
    if session.get('role') != 'admin':
        return redirect(url_for('target_children'))
        
    execute_db("DELETE FROM target_children WHERE id = ?", (id,))
    return redirect(url_for('target_children'))

@app.route('/target-children/delete-photo/<int:id>', methods=['POST'])
def target_children_delete_photo(id):
    if session.get('role') != 'admin':
        return redirect(url_for('target_children'))
        
    child = query_db("SELECT photo_path FROM target_children WHERE id = ?", (id,), one=True)
    if child and child['photo_path']:
        photo_path = child['photo_path']
        if photo_path.startswith('/static/uploads/'):
            filename = photo_path.replace('/static/uploads/', '')
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception as e:
                    print("Failed to delete physical file:", e)
                    
        execute_db("UPDATE target_children SET photo_path = NULL WHERE id = ?", (id,))
        
    return redirect(url_for('target_children'))

@app.route('/target-children/toggle-attendance/<int:id>', methods=['POST'])
def target_children_toggle_attendance(id):
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': '로그인이 필요합니다.'}), 401
        
    data = request.get_json() or {}
    field = data.get('field')
    value = data.get('value')
    
    if field not in ['bible_school', 'water_play'] or value not in [0, 1]:
        return jsonify({'success': False, 'error': '잘못된 필드 또는 값입니다.'}), 400
        
    execute_db(f"UPDATE target_children SET {field} = ? WHERE id = ?", (value, id))
    return jsonify({'success': True})

# Team Board routes
@app.route('/team-boards', methods=['GET', 'POST'])
def team_boards():
    current_user_id = session['user_id']
    user = query_db("SELECT * FROM users WHERE id = ?", (current_user_id,), one=True)
    
    # Default to user's assigned team if valid, else default to '예배팀'
    user_team = user['team'] if user['team'] in ['예배팀', '식탁교제팀', '성경학교 및 물놀이팀', '행정지원팀'] else '예배팀'
    selected_team = request.args.get('team', user_team)
    if selected_team not in ['예배팀', '식탁교제팀', '성경학교 및 물놀이팀', '행정지원팀']:
        selected_team = '예배팀'
        
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

# ──────────────────────────────────────────
# 찬양 율동 배우기 페이지
# ──────────────────────────────────────────
@app.route('/praise-dance', methods=['GET', 'POST'])
def praise_dance():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    is_admin = session.get('role') == 'admin'

    if request.method == 'POST' and is_admin:
        action = request.form.get('action')

        if action == 'add_resource':
            title = request.form.get('title', '').strip()
            link_url = request.form.get('link_url', '').strip()
            resource_type = request.form.get('resource_type', 'link')  # 'link' or 'file'
            description = request.form.get('description', '').strip()

            file_path = None
            if resource_type == 'file':
                file = request.files.get('resource_file')
                if file and file.filename != '':
                    filename = secure_filename(f"score_{int(datetime.now().timestamp())}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    file_path = f"/static/uploads/{filename}"

            execute_db("""
                INSERT INTO worship_resources (title, link_url, file_path, resource_type, description, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (title, link_url or None, file_path, resource_type, description, session.get('name')))

        elif action == 'delete_resource':
            resource_id = request.form.get('resource_id')
            resource = query_db("SELECT * FROM worship_resources WHERE id = ?", (resource_id,), one=True)
            if resource and resource['file_path']:
                try:
                    full_path = os.path.join(BASE_DIR, resource['file_path'].lstrip('/'))
                    if os.path.exists(full_path):
                        os.remove(full_path)
                except Exception as e:
                    print("Failed to delete resource file:", e)
            execute_db("DELETE FROM worship_resources WHERE id = ?", (resource_id,))

        return redirect(url_for('praise_dance'))

    resources = query_db("SELECT * FROM worship_resources ORDER BY created_at DESC")
    return render_template('praise_dance.html',
                           resources=[dict(r) for r in resources] if resources else [],
                           is_admin=is_admin)

# Shared Schedule routes
@app.route('/shared-schedule', methods=['GET', 'POST'])
def shared_schedule():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        due_date = request.form.get('due_date', '').strip()
        end_date = request.form.get('end_date', '').strip()
        
        if title:
            created_by = session.get('name')
            execute_db("""
                INSERT INTO shared_schedules (title, due_date, end_date, created_by)
                VALUES (?, ?, ?, ?)
            """, (title, due_date or None, end_date or None, created_by))
            
        return redirect(url_for('shared_schedule'))
        
    schedules = query_db("""
        SELECT * FROM shared_schedules
        ORDER BY due_date IS NULL, due_date ASC, created_at ASC
    """)
    schedules_list = [dict(s) for s in schedules]

    # Calculate progress metrics
    total_tasks = len(schedules_list)
    completed_tasks = sum(1 for s in schedules_list if s['is_completed'])
    progress_percentage = round((completed_tasks / total_tasks) * 100) if total_tasks > 0 else 0

    prayer_days = query_db("SELECT * FROM prayer_relay ORDER BY prayer_date ASC")
    amen_counts = {row['prayer_date']: row['cnt'] for row in query_db(
        "SELECT prayer_date, COUNT(*) as cnt FROM prayer_amens GROUP BY prayer_date")}
    user_amened_dates = {row['prayer_date'] for row in query_db(
        "SELECT prayer_date FROM prayer_amens WHERE user_id = ?", (session['user_id'],))}

    prayer_days_list = []
    for p in prayer_days:
        p_dict = dict(p)
        p_dict['amen_count'] = amen_counts.get(p['prayer_date'], 0)
        p_dict['user_amened'] = p['prayer_date'] in user_amened_dates
        prayer_days_list.append(p_dict)

    today_str = datetime.now().strftime('%Y-%m-%d')

    return render_template('shared_schedule.html',
                           schedules=schedules_list,
                           total_tasks=total_tasks,
                           completed_tasks=completed_tasks,
                           progress_percentage=progress_percentage,
                           prayer_topics=PRAYER_TOPICS,
                           prayer_days=prayer_days_list,
                           today_prayer_date=today_str,
                           is_admin=(session.get('role') == 'admin'),
                           current_name=session.get('name'))

@app.route('/prayer-relay/submit', methods=['POST'])
def prayer_relay_submit():
    prayer_date = request.form.get('prayer_date', '').strip()
    content = request.form.get('content', '').strip()

    if prayer_date and content:
        execute_db("""
            UPDATE prayer_relay
            SET prayer_content = ?, posted_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE prayer_date = ?
        """, (content, session.get('name'), prayer_date))

    return redirect(url_for('shared_schedule') + '#prayer-relay')

@app.route('/prayer-relay/amen/<prayer_date>', methods=['POST'])
def prayer_relay_amen(prayer_date):
    user_id = session['user_id']
    existing = query_db(
        "SELECT id FROM prayer_amens WHERE prayer_date = ? AND user_id = ?",
        (prayer_date, user_id), one=True)

    if existing:
        execute_db("DELETE FROM prayer_amens WHERE id = ?", (existing['id'],))
        amened = False
    else:
        execute_db("INSERT INTO prayer_amens (prayer_date, user_id) VALUES (?, ?)", (prayer_date, user_id))
        amened = True

    amen_count = query_db(
        "SELECT COUNT(*) as cnt FROM prayer_amens WHERE prayer_date = ?",
        (prayer_date,), one=True)['cnt']
    return jsonify({'amened': amened, 'amen_count': amen_count})

@app.route('/shared-schedule/toggle/<int:id>', methods=['POST'])
def toggle_schedule(id):
    schedule = query_db("SELECT * FROM shared_schedules WHERE id = ?", (id,), one=True)
    if not schedule:
        return jsonify({'success': False, 'error': 'Not found'}), 404
        
    new_completed = 1 - schedule['is_completed']
    execute_db("UPDATE shared_schedules SET is_completed = ? WHERE id = ?", (new_completed, id))
    
    return jsonify({'success': True, 'is_completed': new_completed})

@app.route('/shared-schedule/delete/<int:id>', methods=['POST'])
def delete_schedule(id):
    schedule = query_db("SELECT * FROM shared_schedules WHERE id = ?", (id,), one=True)
    if not schedule:
        return redirect(url_for('shared_schedule'))
        
    user_id = session['user_id']
    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    authorized_names = [user['adult1_name'], user['adult2_name']] if user else []
    
    is_author = (schedule['created_by'] in authorized_names)
    is_admin = (session.get('role') == 'admin')
    
    if is_author or is_admin or schedule['created_by'] == '준비팀':
        execute_db("DELETE FROM shared_schedules WHERE id = ?", (id,))
        
    return redirect(url_for('shared_schedule'))

# Admin-only operations for family list page
@app.route('/admin/update-family-team', methods=['POST'])
def admin_update_family_team():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
    data = request.get_json() or {}
    family_id = data.get('family_id')
    team = data.get('team')
    which = data.get('which', '1')  # '1' = 성인1, '2' = 성인2
    
    if not family_id or not team:
        return jsonify({'success': False, 'error': 'Invalid request'}), 400
        
    valid_teams = ['미지정', '예배팀', '식탁교제팀', '성경학교 및 물놀이팀', '행정지원팀']
    if team not in valid_teams:
        return jsonify({'success': False, 'error': 'Invalid team name'}), 400
    
    if which == '2':
        execute_db("UPDATE users SET team2 = ? WHERE id = ?", (team, family_id))
    else:
        execute_db("UPDATE users SET team = ? WHERE id = ?", (team, family_id))
    return jsonify({'success': True})

@app.route('/admin/update-family-team-leader', methods=['POST'])
def admin_update_family_team_leader():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
    data = request.get_json() or {}
    family_id = data.get('family_id')
    is_leader = data.get('is_leader', False)
    which = data.get('which', '1')  # '1' = 성인1, '2' = 성인2
    
    if family_id is None:
        return jsonify({'success': False, 'error': 'Invalid request'}), 400
    
    val = 1 if is_leader else 0
    if which == '2':
        execute_db("UPDATE users SET is_team_leader2 = ? WHERE id = ?", (val, family_id))
    else:
        execute_db("UPDATE users SET is_team_leader = ? WHERE id = ?", (val, family_id))
    return jsonify({'success': True})

@app.route('/admin/update-family-role', methods=['POST'])
def admin_update_family_role():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
    data = request.get_json() or {}
    family_id = data.get('family_id')
    role = data.get('role')
    
    if not family_id or not role:
        return jsonify({'success': False, 'error': 'Invalid request'}), 400
        
    if int(family_id) == int(session.get('user_id')):
        return jsonify({'success': False, 'error': '자신의 관리자 권한은 스스로 변경할 수 없습니다.'}), 400
        
    if role not in ['admin', 'user']:
        return jsonify({'success': False, 'error': 'Invalid role'}), 400
        
    execute_db("UPDATE users SET role = ? WHERE id = ?", (role, family_id))
    return jsonify({'success': True})

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

# Kids memory game routes
@app.route('/game')
def game():
    if not session.get('user_id'):
        return redirect(url_for('login'))
        
    user_id = session.get('user_id')
    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    high_streak = user['game_high_streak'] if user else 0
    
    # Get all target children who have photos
    rows = query_db("SELECT id, name, photo_path FROM target_children WHERE photo_path IS NOT NULL AND photo_path != ''")
    children_list = [dict(row) for row in rows]
    
    # Get leaderboard
    leaderboard_rows = query_db("""
        SELECT id, adult1_name, adult2_name, game_high_streak 
        FROM users 
        WHERE game_high_streak > 0 
        ORDER BY game_high_streak DESC, adult1_name ASC 
        LIMIT 10
    """)
    leaderboard = []
    for r in leaderboard_rows:
        name_str = r['adult1_name']
        if r['adult2_name']:
            name_str += f" / {r['adult2_name']}"
        leaderboard.append({
            'name': name_str,
            'streak': r['game_high_streak']
        })
        
    return render_template('game.html', 
                           children=children_list, 
                           high_streak=high_streak, 
                           leaderboard=leaderboard)

@app.route('/game/submit-score', methods=['POST'])
def game_submit_score():
    if not session.get('user_id'):
        return jsonify({'success': False, 'error': '로그인이 필요합니다.'}), 401
        
    user_id = session.get('user_id')
    data = request.get_json() or {}
    
    try:
        score = int(data.get('score', 0))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': '잘못된 점수 데이터입니다.'}), 400
        
    if score < 0:
        return jsonify({'success': False, 'error': '점수는 0 이상이어야 합니다.'}), 400
        
    # Get current user and update if score is higher
    user = query_db("SELECT game_high_streak FROM users WHERE id = ?", (user_id,), one=True)
    if user:
        current_high = user['game_high_streak']
        if current_high is None:
            current_high = 0
            
        if score > current_high:
            execute_db("UPDATE users SET game_high_streak = ? WHERE id = ?", (score, user_id))
            return jsonify({'success': True, 'new_high': True, 'high_streak': score})
        return jsonify({'success': True, 'new_high': False, 'high_streak': current_high})
        
    return jsonify({'success': False, 'error': '사용자를 찾을 수 없습니다.'}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)
