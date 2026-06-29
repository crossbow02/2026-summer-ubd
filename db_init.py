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
    db_path = "/Users/crossbow02/Desktop/2026 유바디 여름 가족선교/database.db"
    excel_path = "/Users/crossbow02/Desktop/2026 유바디 여름 가족선교/2026년 유바디 2마을 여름 사역 참가 가정.xlsx"
    
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
        role TEXT DEFAULT 'user'
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
    
    conn.commit()
    print("Database tables created successfully.")
    
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
        
        # Determine role (정다운 is admin)
        role = 'user'
        if adult1_name == '정다운':
            role = 'admin'
            
        cursor.execute("""
        INSERT INTO users (group_num, adult1_name, adult1_phone, adult1_last4, adult2_name, adult2_phone, adult2_last4, children, role)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (group_num, adult1_name, adult1_phone, adult1_last4, adult2_name, adult2_phone, adult2_last4, children_json, role))
        user_count += 1
        
    conn.commit()
    conn.close()
    print(f"Successfully loaded {user_count} families into the database.")

if __name__ == "__main__":
    init_db()
