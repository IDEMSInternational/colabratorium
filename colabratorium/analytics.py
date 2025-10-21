import sqlite3
from datetime import datetime
import os

DB = "analytics.db"

def analytics_connect():
    return sqlite3.connect(DB)

def init_db():
    """
    Create the database schema dynamically from the DBML file.
    Optionally seeds default data.
    """
    existed = os.path.exists(DB)
    
    conn = analytics_connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS analytics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        person_id INTEGER,
        requested_table TEXT,
        requested_id INTEGER
    );"""
    )

    conn.commit()
    print("Analysis db initialized.")
    conn.close()

def analytics_log(person_id, requested_table, requested_id):
    """
    Log an analytics event to the database.
    """
    conn = analytics_connect()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO analytics (person_id, requested_table, requested_id)
        VALUES (?, ?, ?);
    """, (person_id, requested_table, requested_id))

    conn.commit()
    conn.close()