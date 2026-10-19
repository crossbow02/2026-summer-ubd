import os
import sqlite3

DATABASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'zone_survey.db')


def init_schema(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS zones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL,
        name TEXT NOT NULL,
        sort INTEGER DEFAULT 0,
        leader_names TEXT,
        token TEXT NOT NULL UNIQUE,
        submitted_at TEXT
    );
    CREATE TABLE IF NOT EXISTS zone_families (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        zone_id INTEGER NOT NULL REFERENCES zones(id),
        sort INTEGER DEFAULT 0,
        role_prev TEXT,
        husband_name TEXT, husband_birth TEXT, husband_phone TEXT,
        wife_name TEXT, wife_birth TEXT, wife_phone TEXT,
        children_json TEXT DEFAULT '[]',
        children_raw TEXT,
        ref_att_m TEXT, ref_att_f TEXT,
        sheet_memo TEXT,
        original_json TEXT,
        info_confirmed INTEGER DEFAULT 0,
        attendance TEXT,
        next_status TEXT,
        note TEXT,
        added_by_leader INTEGER DEFAULT 0,
        updated_at TEXT
    );
    ''')
    conn.commit()


def connect():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn
