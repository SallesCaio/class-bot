"""
Class Bot — Database module
SQLite database for lessons, categories, schedules, and user preferences.
"""

import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "classbot.db"


def get_db() -> sqlite3.Connection:
    """Get SQLite connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize database tables."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            UNIQUE(user_id, name)
        );

        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            category_id INTEGER,
            level TEXT DEFAULT 'iniciante',
            objective TEXT DEFAULT '',
            content TEXT DEFAULT '',
            activities TEXT DEFAULT '',
            evaluation TEXT DEFAULT '',
            materials TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            date TEXT,
            time TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (category_id) REFERENCES categories(id)
        );

        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            lesson_id INTEGER NOT NULL,
            scheduled_date TEXT NOT NULL,
            scheduled_time TEXT NOT NULL,
            notified_1h INTEGER DEFAULT 0,
            notified_15min INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (lesson_id) REFERENCES lessons(id)
        );

        CREATE INDEX IF NOT EXISTS idx_lessons_user ON lessons(user_id);
        CREATE INDEX IF NOT EXISTS idx_lessons_category ON lessons(category_id);
        CREATE INDEX IF NOT EXISTS idx_lessons_date ON lessons(date);
        CREATE INDEX IF NOT EXISTS idx_schedules_user ON schedules(user_id);
        CREATE INDEX IF NOT EXISTS idx_schedules_date ON schedules(scheduled_date);
    """)

    # Insert default categories for new users
    conn.commit()
    conn.close()


# --- User operations ---

def upsert_user(user_id: int, username: str, first_name: str):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
        (user_id, username, first_name)
    )
    conn.commit()
    conn.close()


def get_user(user_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# --- Category operations ---

def add_category(user_id: int, name: str) -> int:
    conn = get_db()
    cursor = conn.execute(
        "INSERT OR IGNORE INTO categories (user_id, name) VALUES (?, ?)",
        (user_id, name)
    )
    conn.commit()
    cat_id = cursor.lastrowid
    conn.close()
    return cat_id


def get_categories(user_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM categories WHERE user_id = ? ORDER BY name",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_category_by_name(user_id: int, name: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM categories WHERE user_id = ? AND name = ?",
        (user_id, name)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_category(cat_id: int, user_id: int) -> bool:
    conn = get_db()
    cursor = conn.execute(
        "DELETE FROM categories WHERE id = ? AND user_id = ?",
        (cat_id, user_id)
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


# --- Lesson operations ---

def add_lesson(user_id: int, title: str, category_id: int | None, level: str,
               objective: str, content: str, activities: str, evaluation: str,
               materials: str, notes: str, date: str, time: str) -> int:
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO lessons 
           (user_id, title, category_id, level, objective, content, activities,
            evaluation, materials, notes, date, time)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, title, category_id, level, objective, content, activities,
         evaluation, materials, notes, date, time)
    )
    conn.commit()
    lesson_id = cursor.lastrowid
    conn.close()
    return lesson_id


def get_lesson(lesson_id: int, user_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute(
        """SELECT l.*, c.name as category_name 
           FROM lessons l 
           LEFT JOIN categories c ON l.category_id = c.id 
           WHERE l.id = ? AND l.user_id = ?""",
        (lesson_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_lessons(user_id: int, category_id: int | None = None,
                level: str | None = None, limit: int = 50) -> list[dict]:
    conn = get_db()
    query = """SELECT l.*, c.name as category_name 
               FROM lessons l 
               LEFT JOIN categories c ON l.category_id = c.id 
               WHERE l.user_id = ?"""
    params: list = [user_id]

    if category_id:
        query += " AND l.category_id = ?"
        params.append(category_id)
    if level:
        query += " AND l.level = ?"
        params.append(level)

    query += " ORDER BY l.date DESC, l.time DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_lesson(lesson_id: int, user_id: int, **kwargs) -> bool:
    allowed = {'title', 'category_id', 'level', 'objective', 'content',
               'activities', 'evaluation', 'materials', 'notes', 'date', 'time'}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False

    fields['updated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [lesson_id, user_id]

    conn = get_db()
    cursor = conn.execute(
        f"UPDATE lessons SET {set_clause} WHERE id = ? AND user_id = ?",
        values
    )
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated


def delete_lesson(lesson_id: int, user_id: int) -> bool:
    conn = get_db()
    # Delete related schedules first
    conn.execute("DELETE FROM schedules WHERE lesson_id = ? AND user_id = ?",
                 (lesson_id, user_id))
    cursor = conn.execute(
        "DELETE FROM lessons WHERE id = ? AND user_id = ?",
        (lesson_id, user_id)
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def search_lessons(user_id: int, term: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT l.*, c.name as category_name 
           FROM lessons l 
           LEFT JOIN categories c ON l.category_id = c.id 
           WHERE l.user_id = ? AND (
               l.title LIKE ? OR l.objective LIKE ? OR l.content LIKE ?
           )
           ORDER BY l.date DESC""",
        (user_id, f"%{term}%", f"%{term}%", f"%{term}%")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Schedule operations ---

def add_schedule(user_id: int, lesson_id: int, date: str, time: str) -> int:
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO schedules (user_id, lesson_id, scheduled_date, scheduled_time)
           VALUES (?, ?, ?, ?)""",
        (user_id, lesson_id, date, time)
    )
    conn.commit()
    sched_id = cursor.lastrowid
    conn.close()
    return sched_id


def get_schedules(user_id: int, from_date: str | None = None,
                  to_date: str | None = None) -> list[dict]:
    conn = get_db()
    query = """SELECT s.*, l.title, l.level, c.name as category_name
               FROM schedules s
               JOIN lessons l ON s.lesson_id = l.id
               LEFT JOIN categories c ON l.category_id = c.id
               WHERE s.user_id = ?"""
    params: list = [user_id]

    if from_date:
        query += " AND s.scheduled_date >= ?"
        params.append(from_date)
    if to_date:
        query += " AND s.scheduled_date <= ?"
        params.append(to_date)

    query += " ORDER BY s.scheduled_date, s.scheduled_time"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_notifications() -> list[dict]:
    """Get schedules that need notifications (not yet notified)."""
    conn = get_db()
    rows = conn.execute(
        """SELECT s.*, l.title, l.level, c.name as category_name
           FROM schedules s
           JOIN lessons l ON s.lesson_id = l.id
           LEFT JOIN categories c ON l.category_id = c.id
           WHERE s.notified_1h = 0 OR s.notified_15min = 0
           ORDER BY s.scheduled_date, s.scheduled_time"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_notified(schedule_id: int, notification_type: str):
    """Mark a schedule as notified. type = '1h' or '15min'."""
    col = "notified_1h" if notification_type == "1h" else "notified_15min"
    conn = get_db()
    conn.execute(f"UPDATE schedules SET {col} = 1 WHERE id = ?", (schedule_id,))
    conn.commit()
    conn.close()


def delete_schedule(schedule_id: int, user_id: int) -> bool:
    conn = get_db()
    cursor = conn.execute(
        "DELETE FROM schedules WHERE id = ? AND user_id = ?",
        (schedule_id, user_id)
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted
