# -*- coding: utf-8 -*-
"""
SESSION MEMORY & STRUCTURED CANDIDATE PROFILE STORE (ENTERPRISE GRADE)
Хранилище сессионного контекста кандидатов на базе SQLite (по стандартам Tinkoff / Kupibilet).
Исключает 'амнезию' бота и путаницу между кандидатом, мужем, братом и сыном.
"""
import os
import sqlite3
import json
import time
from typing import Optional, Dict, Any

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "candidate_sessions.db")

def init_session_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS candidate_profiles (
        chat_id TEXT PRIMARY KEY,
        candidate_name TEXT,
        target_subject TEXT DEFAULT 'кандидат',
        age INTEGER,
        has_rf_passport INTEGER,
        origin_city TEXT,
        departure_date TEXT,
        phone_number TEXT,
        qualification_status TEXT DEFAULT 'IN_PROGRESS',
        disqualification_reason TEXT,
        deal_id TEXT,
        last_updated INTEGER,
        raw_metadata TEXT
    )
    """)
    conn.commit()
    conn.close()

# Инициализируем БД при импорте
init_session_db()

def get_session_profile(chat_id: str) -> Dict[str, Any]:
    """Возвращает текущую анкету кандидата из SQLite."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM candidate_profiles WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return {
            "chat_id": chat_id,
            "candidate_name": "",
            "target_subject": "кандидат",
            "age": None,
            "has_rf_passport": None,
            "origin_city": None,
            "departure_date": None,
            "phone_number": None,
            "qualification_status": "IN_PROGRESS",
            "disqualification_reason": "",
            "deal_id": "",
            "last_updated": int(time.time()),
            "raw_metadata": "{}"
        }

    return {
        "chat_id": row[0],
        "candidate_name": row[1] or "",
        "target_subject": row[2] or "кандидат",
        "age": row[3],
        "has_rf_passport": bool(row[4]) if row[4] is not None else None,
        "origin_city": row[5] or "",
        "departure_date": row[6] or "",
        "phone_number": row[7] or "",
        "qualification_status": row[8] or "IN_PROGRESS",
        "disqualification_reason": row[9] or "",
        "deal_id": row[10] or "",
        "last_updated": row[11],
        "raw_metadata": row[12] or "{}"
    }

def update_session_profile(chat_id: str = None, **kwargs) -> Dict[str, Any]:
    if chat_id is None:
        chat_id = kwargs.pop('chat_id', None)
    """Обновляет заполненные слоты кандидата в SQLite."""
    current = get_session_profile(chat_id)
    for k, v in kwargs.items():
        if v is not None:
            current[k] = v
    current["last_updated"] = int(time.time())

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO candidate_profiles (
        chat_id, candidate_name, target_subject, age, has_rf_passport,
        origin_city, departure_date, phone_number, qualification_status,
        disqualification_reason, deal_id, last_updated, raw_metadata
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        current["chat_id"],
        current["candidate_name"],
        current["target_subject"],
        current["age"],
        1 if current["has_rf_passport"] is True else (0 if current["has_rf_passport"] is False else None),
        current["origin_city"],
        current["departure_date"],
        current["phone_number"],
        current["qualification_status"],
        current["disqualification_reason"],
        current["deal_id"],
        current["last_updated"],
        current["raw_metadata"]
    ))
    conn.commit()
    conn.close()
    return current

def reset_session_profile(chat_id: str):
    """Сброс профиля при перезапуске диалога."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM candidate_profiles WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()
