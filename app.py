from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import psycopg2.extras
import os
from werkzeug.security import generate_password_hash, check_password_hash
import base64

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cartas-secret-key-change-in-prod')

DATABASE_URL = os.environ.get('DATABASE_URL')


def get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    cur.execute('''
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
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sticky_notes (
            id SERIAL PRIMARY KEY,
            content TEXT,
            drawing_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER REFERENCES users(id)
        )
    ''')
    cur.execute("SELECT id FROM users WHERE username = %s", ('admin',))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)",
                     ('admin', generate_password_hash('admin')))
    cur.execute("SELECT id FROM users WHERE username = %s", ('luisa',))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)",
                     ('luisa', generate_password_hash('1234')))
    conn.commit()
    conn.close()


init_db()


@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('gallery'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = 'admin' if user['username'] == 'admin' else 'user'
            return redirect(url_for('gallery'))
        return render_template('login.html', error='Usuario o contraseña incorrectos')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/gallery')
def gallery():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM letters ORDER BY letter_number DESC")
    letters = cur.fetchall()
    cur.execute('''
        SELECT sn.*, u.username FROM sticky_notes sn
        JOIN users u ON sn.user_id = u.id
        ORDER BY sn.created_at DESC
    ''')
    notes = cur.fetchall()
    conn.close()
    return render_template('gallery.html', letters=letters, notes=notes)


@app.route('/new', methods=['GET', 'POST'])
def new_letter():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'admin':
        return redirect(url_for('gallery'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        if not title:
            return render_template('editor.html', error='El título es obligatorio')

        content = request.form.get('content', '').strip()
        pdf_data = None
        image_data = None

        if 'pdf' in request.files:
            pdf = request.files['pdf']
            if pdf and pdf.filename:
                b64 = base64.b64encode(pdf.read()).decode()
                pdf_data = f"data:application/pdf;base64,{b64}"

        if 'image' in request.files:
            img = request.files['image']
            if img and img.filename:
                ext = img.filename.rsplit('.', 1)[-1].lower()
                mime = f"image/{ext}" if ext in ('png', 'jpg', 'jpeg', 'gif', 'webp') else "image/png"
                b64 = base64.b64encode(img.read()).decode()
                image_data = f"data:{mime};base64,{b64}"

        if not content and not pdf_data and not image_data:
            return render_template('editor.html', error='Escribe algo o sube un archivo')

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT COALESCE(MAX(letter_number), 0) + 1 FROM letters")
        letter_number = cur.fetchone()['coalesce']
        cur.execute(
            "INSERT INTO letters (letter_number, title, content, pdf_data, image_data, user_id) VALUES (%s, %s, %s, %s, %s, %s)",
            (letter_number, title, content, pdf_data, image_data, session['user_id']))
        conn.commit()
        conn.close()
        flash('Carta guardada', 'success')
        return redirect(url_for('gallery'))

    return render_template('editor.html')


@app.route('/letter/<int:letter_id>')
def view_letter(letter_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM letters WHERE id = %s", (letter_id,))
    letter = cur.fetchone()
    conn.close()
    if not letter:
        return redirect(url_for('gallery'))
    return render_template('view.html', letter=letter)


@app.route('/help')
def help_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('help.html')


@app.route('/sticky-note', methods=['POST'])
def create_sticky_note():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    content = request.form.get('content', '').strip()
    drawing = request.form.get('drawing', '')
    drawing_data = drawing if drawing.startswith('data:') else None

    if content or drawing_data:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO sticky_notes (content, drawing_data, user_id) VALUES (%s, %s, %s)",
                     (content, drawing_data, session['user_id']))
        conn.commit()
        conn.close()
        flash('Notita guardada', 'success')
    return redirect(url_for('gallery'))


@app.route('/sticky-note/<int:note_id>/delete', methods=['POST'])
def delete_sticky_note(note_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM sticky_notes WHERE id = %s", (note_id,))
    note = cur.fetchone()
    if note and (session.get('role') == 'admin' or note['user_id'] == session['user_id']):
        cur.execute("DELETE FROM sticky_notes WHERE id = %s", (note_id,))
        conn.commit()
    conn.close()
    return redirect(url_for('gallery'))


@app.route('/delete/<int:letter_id>', methods=['POST'])
def delete_letter(letter_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'admin':
        return redirect(url_for('gallery'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM letters WHERE id = %s", (letter_id,))
    conn.commit()
    conn.close()
    flash('Carta eliminada', 'info')
    return redirect(url_for('gallery'))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
