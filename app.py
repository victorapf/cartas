from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import uuid

app = Flask(__name__)
app.secret_key = 'cartas-secret-key-change-in-prod'
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

DB_PATH = 'database.db'


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS letters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            letter_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            pdf_filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS sticky_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER REFERENCES users(id)
        );
    ''');
    if not conn.execute('SELECT id FROM users WHERE username = ?', ('admin',)).fetchone():
        conn.execute('INSERT INTO users (username, password) VALUES (?, ?)',
                     ('admin', generate_password_hash('admin')))
    if not conn.execute('SELECT id FROM users WHERE username = ?', ('luisa',)).fetchone():
        conn.execute('INSERT INTO users (username, password) VALUES (?, ?)',
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
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
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
    letters = conn.execute('SELECT * FROM letters ORDER BY letter_number DESC').fetchall()
    notes = conn.execute('''
        SELECT sn.*, u.username FROM sticky_notes sn
        JOIN users u ON sn.user_id = u.id
        ORDER BY sn.created_at DESC
    ''').fetchall()
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
        pdf_filename = None

        if 'pdf' in request.files:
            pdf = request.files['pdf']
            if pdf and pdf.filename:
                ext = secure_filename(pdf.filename).rsplit('.', 1)[-1]
                pdf_filename = f"{uuid.uuid4()}.{ext}"
                pdf.save(os.path.join(app.config['UPLOAD_FOLDER'], pdf_filename))

        if not content and not pdf_filename:
            return render_template('editor.html', error='Escribe algo o sube un PDF')

        conn = get_db()
        max_num = conn.execute('SELECT MAX(letter_number) FROM letters').fetchone()[0]
        letter_number = (max_num or 0) + 1
        conn.execute(
            'INSERT INTO letters (letter_number, title, content, pdf_filename, user_id) VALUES (?, ?, ?, ?, ?)',
            (letter_number, title, content, pdf_filename, session['user_id']))
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
    letter = conn.execute('SELECT * FROM letters WHERE id = ?', (letter_id,)).fetchone()
    conn.close()
    if not letter:
        return redirect(url_for('gallery'))
    return render_template('view.html', letter=letter)


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/sticky-note', methods=['POST'])
def create_sticky_note():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    content = request.form.get('content', '').strip()
    if content:
        conn = get_db()
        conn.execute('INSERT INTO sticky_notes (content, user_id) VALUES (?, ?)',
                     (content, session['user_id']))
        conn.commit()
        conn.close()
        flash('💌 Notita guardada', 'success')
    return redirect(url_for('gallery'))


@app.route('/sticky-note/<int:note_id>/delete', methods=['POST'])
def delete_sticky_note(note_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    note = conn.execute('SELECT * FROM sticky_notes WHERE id = ?', (note_id,)).fetchone()
    if note and (session.get('role') == 'admin' or note['user_id'] == session['user_id']):
        conn.execute('DELETE FROM sticky_notes WHERE id = ?', (note_id,))
        conn.commit()
        flash('Notita eliminada', 'info')
    conn.close()
    return redirect(url_for('gallery'))


@app.route('/delete/<int:letter_id>', methods=['POST'])
def delete_letter(letter_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'admin':
        return redirect(url_for('gallery'))
    conn = get_db()
    letter = conn.execute('SELECT * FROM letters WHERE id = ?', (letter_id,)).fetchone()
    if letter:
        if letter['pdf_filename']:
            path = os.path.join(app.config['UPLOAD_FOLDER'], letter['pdf_filename'])
            if os.path.exists(path):
                os.remove(path)
        conn.execute('DELETE FROM letters WHERE id = ?', (letter_id,))
    conn.commit()
    conn.close()
    flash('Carta eliminada', 'info')
    return redirect(url_for('gallery'))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
