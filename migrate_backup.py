"""
Migra el backup de cartas (JSON de /export) hacia la base de datos PostgreSQL.

Uso:
    DATABASE_URL="postgresql://..." python migrate_backup.py ruta/al/backup.json

Requisitos: pip install psycopg2-binary
"""

import json
import os
import sys

import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash


DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("ERROR: Define DATABASE_URL apuntando a Supabase.")
    sys.exit(1)


def connect():
    return psycopg2.connect(DATABASE_URL)


def init_tables(cur, conn):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS letters (
            id SERIAL PRIMARY KEY,
            letter_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            pdf_data TEXT,
            image_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER REFERENCES users(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sticky_notes (
            id SERIAL PRIMARY KEY,
            content TEXT,
            drawing_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER REFERENCES users(id)
        )
    """)
    # Asegurar que admin y luisa existan antes de insertar cartas que los referencian
    cur.execute("SELECT id FROM users WHERE username = %s", ('admin',))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)",
                    ('admin', generate_password_hash('admin')))
    cur.execute("SELECT id FROM users WHERE username = %s", ('luisa',))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)",
                    ('luisa', generate_password_hash('1234')))
    conn.commit()


ALLOWED_COLS = {
    'letters': ('id', 'letter_number', 'title', 'content',
                'pdf_data', 'image_data', 'created_at', 'user_id'),
    'sticky_notes': ('id', 'content', 'drawing_data', 'created_at', 'user_id'),
}


def insert_rows(cur, table, rows):
    if not rows:
        return 0
    allowed = ALLOWED_COLS.get(table, ())
    cols = [c for c in (list(rows[0].keys()) if rows else []) if c in allowed]
    if not cols:
        return 0
    placeholders = ', '.join(['%s'] * len(cols))
    colstr = ', '.join(cols)
    sql = f"INSERT INTO {table} ({colstr}) VALUES ({placeholders})"
    cur.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
    return len(rows)


def main():
    if len(sys.argv) < 2:
        print("ERROR: Indica el archivo JSON del backup.")
        print(f"  {sys.argv[0]} backup.json")
        sys.exit(1)
    path = sys.argv[1]
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    letters = data.get('letters', []) or []
    notes = data.get('sticky_notes', []) or []

    conn = connect()
    cur = conn.cursor()
    init_tables(cur, conn)
    conn.commit()

    try:
        n_letters = insert_rows(cur, 'letters', letters)
        conn.commit()
        n_notes = insert_rows(cur, 'sticky_notes', notes)
        conn.commit()
        # Ajustar secuencias para que los nuevos inserts no colisionen
        for table in ('letters', 'sticky_notes', 'users'):
            cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table}), 1))")
        conn.commit()
        print(f"OK: {n_letters} cartas insertadas, {n_notes} notas insertadas.")
    except psycopg2.IntegrityError as e:
        conn.rollback()
        print("ERROR (posible duplicado, prueba vaciar antes):", e)
        print("Para limpiar: ejecuta en Supabase -> SQL Editor ->")
        print("  TRUNCATE letters, sticky_notes, users RESTART IDENTITY CASCADE;")
        sys.exit(1)
    except Exception as e:
        conn.rollback()
        print("ERROR durante la migración:", e)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
