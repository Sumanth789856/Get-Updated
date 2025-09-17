from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, jsonify, current_app
import os
import sqlite3
from datetime import datetime
from sqlalchemy import or_
from dotenv import load_dotenv  # <-- NEW

# ---------- LOAD ENV ----------
load_dotenv()  

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ---------- CONFIG ----------
UPLOAD_FOLDER = "uploads"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
DB_NAME = "database.db"

# ---------- DATABASE SETUP ----------
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # canonical tables with improved schema and safe migrations
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            email TEXT UNIQUE,
            password TEXT,
            role TEXT DEFAULT 'student',
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            last_login TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            title TEXT,
            content TEXT,
            uploaded_by TEXT,
            created_at TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT,
            author TEXT,
            date TEXT DEFAULT (datetime('now'))
        )
    ''')

    # helper to safely add a missing column (SQLite supports ADD COLUMN)
    def ensure_column(table, col_def):
        colname = col_def.split()[0]
        c.execute(f"PRAGMA table_info({table})")
        existing = [r[1] for r in c.fetchall()]
        if colname not in existing:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
            except Exception:
                # ignore migration error; keep silent in prod
                pass

    # ensure missing columns are added for older DBs
    ensure_column('users', 'email TEXT')
    ensure_column('users', 'is_active INTEGER DEFAULT 1')
    ensure_column('users', 'created_at TEXT')
    ensure_column('users', 'last_login TEXT')

    ensure_column('notes', 'title TEXT')
    ensure_column('notes', 'content TEXT')
    ensure_column('notes', 'created_at TEXT')

    # indexes for performance
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_notes_filename ON notes(filename)")

    # seed default accounts (safe)
    try:
        c.execute(
            "INSERT OR IGNORE INTO users (username, email, password, role, created_at) VALUES (?,?,?,?,datetime('now'))",
            ("teacher", "teacher@example.com", "pass", "teacher")
        )
        c.execute(
            "INSERT OR IGNORE INTO users (username, email, password, role, created_at) VALUES (?,?,?,?,datetime('now'))",
            ("student", "student@example.com", "pass", "student")
        )
    except Exception:
        pass

    conn.commit()
    conn.close()

init_db()

# ---------- ROUTES ----------

@app.route("/")
def index():
    return render_template("index.html", title="Home")

# ---------- LOGIN ----------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not username or not email or not password:
            return "Email, username and password are required!"

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # require username + email + password to match
        c.execute(
            "SELECT id, username, email, password, role FROM users WHERE username=? AND email=? COLLATE NOCASE AND password=?",
            (username, email, password),
        )
        user = c.fetchone()

        if user:
            # update last_login timestamp
            try:
                c.execute("UPDATE users SET last_login=? WHERE id=?",
                          (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user[0]))
                conn.commit()
            except Exception:
                pass
            conn.close()

            session["username"] = user[1]
            session["role"] = user[4]
            return redirect(url_for("dashboard"))
        else:
            conn.close()
            return "Invalid credentials!"
    return render_template("login.html", title="Login")

# ---------- REGISTER ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "student")

        if not username or not password or not email:
            return "⚠️ Username, email and password are required!"

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=? OR email=?", (username, email))
        if c.fetchone():
            conn.close()
            return "⚠️ Username or email already taken!"

        c.execute("INSERT INTO users (username, email, password, role) VALUES (?,?,?,?)",
                  (username, email, password, role))
        conn.commit()
        conn.close()

        return redirect(url_for("login"))

    return render_template("register.html", title="Register")

# ---------- LOGOUT ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# ---------- DASHBOARD ----------
@app.route("/dashboard")
def dashboard():
    if "username" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html", title="Dashboard", role=session["role"])

# ---------- NOTES ----------
@app.route("/notes", methods=["GET","POST"])
def notes():
    if "username" not in session:
        return redirect(url_for("login"))

    # Upload note
    if request.method == "POST":
        file = request.files["file"]
        if file:
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
            file.save(filepath)

            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("INSERT INTO notes (filename,uploaded_by) VALUES (?,?)",
                      (file.filename, session["username"]))
            conn.commit()
            conn.close()

    # Fetch all notes
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM notes")
    files = c.fetchall()
    conn.close()

    return render_template("notes.html", title="Notes", files=files, role=session["role"])

# Download file
@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# Delete note
@app.route("/delete_note/<int:note_id>", methods=["POST"])
def delete_note(note_id):
    if "username" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT filename, uploaded_by FROM notes WHERE id=?", (note_id,))
    note = c.fetchone()

    if note:
        filename, uploader = note
        if session["role"] == "teacher" or session["username"] == uploader:
            c.execute("DELETE FROM notes WHERE id=?", (note_id,))
            conn.commit()

            # Delete file from uploads
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            if os.path.exists(file_path):
                os.remove(file_path)

    conn.close()
    return redirect(url_for("notes"))

# ---------- ANNOUNCEMENTS ----------
@app.route("/announcements", methods=["GET","POST"])
def announcements():
    if "username" not in session:
        return redirect(url_for("login"))

    if request.method == "POST" and session["role"] == "teacher":
        content = request.form.get("announcement")
        if content and content.strip():
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("INSERT INTO announcements (content,author,date) VALUES (?,?,?)",
                      (content.strip(), session["username"], datetime.now().strftime("%Y-%m-%d %H:%M")))
            conn.commit()
            conn.close()
            return redirect(url_for("announcements"))

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM announcements ORDER BY id DESC")
    announcements = c.fetchall()
    conn.close()

    return render_template("announcements.html", title="Announcements",
                           announcements=announcements, role=session["role"])

# Delete announcement
@app.route("/delete_announcement/<int:ann_id>", methods=["POST"])
def delete_announcement(ann_id):
    if "username" in session and session["role"] == "teacher":
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
        conn.commit()
        conn.close()
    return redirect(url_for("announcements"))

# ---------- SEARCH ----------
@app.route('/search')
def search_notes():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])

    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # search filename (case-insensitive)
        pattern = f"%{q}%"
        c.execute("SELECT id, filename FROM notes WHERE filename LIKE ? COLLATE NOCASE LIMIT 12", (pattern,))
        rows = c.fetchall()
        conn.close()

        results = [
            {
                'id': r[0],
                'title': r[1] or '',
                'excerpt': r[1] or ''
            }
            for r in rows
        ]
        return jsonify(results)
    except Exception:
        current_app.logger.exception("Search error")
        return jsonify({'error': 'server error'}), 500

# ---------- RUN ----------
if __name__ == "__main__":
    app.run(debug=True)
