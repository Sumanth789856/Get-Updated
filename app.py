from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, jsonify, current_app, flash
import os
from datetime import datetime
from dotenv import load_dotenv  # <-- NEW
import psycopg2
from psycopg2 import Error




# ---------- LOAD ENV ----------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")

# ---------- CONFIG ----------
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ---------- DATABASE CONFIG ----------
app.config["DB_NAME"] = os.getenv("DBNAME", "neondb")
app.config["DB_USER"] = os.getenv("DBUSER", "neondb_owner")
app.config["DB_PASSWORD"] = os.getenv("DBPASSWORD", "npg_amlCENp4dF7Q")
app.config["DB_HOST"] = os.getenv("DBHOST", "ep-round-resonance-adiv96hj-pooler.c-2.us-east-1.aws.neon.tech")
app.config["DB_PORT"] = os.getenv("DBPORT", "5432")

# ---------- DATABASE CONNECTION ----------
def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname=app.config["DB_NAME"],
            user=app.config["DB_USER"],
            password=app.config["DB_PASSWORD"],
            host=app.config["DB_HOST"],
            port=app.config["DB_PORT"],
            sslmode="require"
        )
        return conn
    except Exception as e:
        current_app.logger.error(f"DB connection failed: {e}")
        return None

# ---------- DATABASE SETUP ----------
def init_db():
    conn = get_db_connection()
    if not conn:
        print("Database connection failed.")
        return

    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id SERIAL PRIMARY KEY,
                    filename TEXT NOT NULL,
                    uploaded_by TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(255) UNIQUE NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role VARCHAR(50) DEFAULT 'student',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            """)
            # Seed default users
            default_users = [
                ("teacher", "teacher@example.com", "pass", "teacher"),
                ("student", "student@example.com", "pass", "student"),
                ("admin", "admin@example.com", "adminpass", "admin")
            ]
            for u in default_users:
                cur.execute("SELECT 1 FROM users WHERE username=%s OR email=%s", (u[0], u[1]))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO users (username, email, password, role, created_at) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)",
                        u
                    )
            conn.commit()
    except Exception as e:
        print(f"Error initializing DB: {e}")
    finally:
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
            return "⚠️ Email, username and password are required!"

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # require username + email + password to match
            cur.execute(
                "SELECT id, username, email, password, role FROM users "
                "WHERE username ILIKE %s AND email ILIKE %s AND password=%s",
                (username, email, password),
            )
            user = cur.fetchone()

            if user:
                # update last_login timestamp
                try:
                    cur.execute("UPDATE users SET last_login=%s WHERE id=%s",
                                (datetime.now(), user[0]))
                    conn.commit()
                except Exception:
                    pass

                session["username"] = user[1]
                session["role"] = user[4]
                return redirect(url_for("dashboard"))
            else:
                return "⚠️ Invalid credentials!"
        except Error as e:
            return f"⚠️ Database error: {str(e)}"
        finally:
            conn.close()
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

        # Restrict teacher registration to admins only
        if role == "teacher" and session.get("role") != "admin":
            return "⚠️ Only admins can add teachers!"

        try:
            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("SELECT 1 FROM users WHERE username=%s OR email=%s", (username, email))
            if cur.fetchone():
                return "⚠️ Username or email already taken!"

            cur.execute(
                "INSERT INTO users (username, email, password, role, created_at) "
                "VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)",
                (username, email, password, role)
            )
            conn.commit()
            return redirect(url_for("login"))
        except Error as e:
            return f"⚠️ Database error: {str(e)}"
        finally:
            conn.close()

    return render_template("register.html", title="Register")



# ---------- LOGOUT ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# ---------- DASHBOARD ----------
@app.route("/dashboard", methods=["GET"])
def dashboard():
    if "username" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html", title="Dashboard", role=session["role"])

# ---------- NOTES
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

            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO notes (filename, uploaded_by) VALUES (%s, %s)",
                      (file.filename, session["username"]))
            conn.commit()
            conn.close()

    # Fetch all notes
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, filename, uploaded_by, created_at FROM notes")
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

    conn = get_db_connection()
    c = conn.cursor()  # Fixed cursor call
    c.execute("SELECT filename, uploaded_by FROM notes WHERE id=%s", (note_id,))  # Fixed placeholder
    note = c.fetchone()

    if note:
        filename, uploader = note
        current_app.logger.info(f"Note found: {filename}, uploaded by: {uploader}")
        if session["role"] in ["teacher", "admin"] or session["username"] == uploader:
            c.execute("DELETE FROM notes WHERE id=%s", (note_id,))
            conn.commit()
            current_app.logger.info(f"Note deleted: {filename}")

            # Delete file from uploads
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                current_app.logger.info(f"File removed: {file_path}")
        else:
            current_app.logger.warning("Unauthorized delete attempt")
    else:
        current_app.logger.warning("Note not found")
    conn.close()
    return redirect(url_for("notes"))

# ---------- ANNOUNCEMENTS ----------
from psycopg2.extras import RealDictCursor

@app.route("/announcements", methods=["GET", "POST"])
def announcements():
    if "username" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        content = request.form.get("announcement")
        if content and content.strip():
            if session["role"] in ["student", "teacher", "admin"]:
                try:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO announcements (content, author, date) "
                        "VALUES (%s, %s, CURRENT_TIMESTAMP)",
                        (content.strip(), session["username"])
                    )
                    conn.commit()
                    conn.close()
                    flash("✅ Announcement posted successfully!", "success")
                    # 🔑 Redirect to avoid re-post on refresh
                    return redirect(url_for("announcements"))
                except Exception as e:
                    flash(f"⚠️ Database error: {str(e)}", "error")
            else:
                flash("⚠️ You are not authorized to post announcements!", "error")

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, content, author, date FROM announcements ORDER BY id DESC")
        announcements = cur.fetchall()
        conn.close()
    except Exception as e:
        announcements = []
        flash(f"⚠️ Database error: {str(e)}", "error")

    return render_template(
        "announcements.html",
        title="Announcements",
        announcements=announcements,
        role=session["role"],
        username=session["username"]
    )
@app.route("/delete_announcement/<int:ann_id>", methods=["POST"])
def delete_announcement(ann_id):
    if "username" not in session:
        return redirect(url_for("login"))

    # Only teachers/admins allowed to delete
    if session["role"] not in ["teacher", "admin"]:
        flash("⚠️ You are not authorized to delete announcements!", "error")
        return redirect(url_for("announcements"))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM announcements WHERE id = %s", (ann_id,))
        conn.commit()
        conn.close()
        flash("🗑️ Announcement deleted successfully!", "success")
    except Exception as e:
        flash(f"⚠️ Database error: {str(e)}", "error")

    return redirect(url_for("announcements"))


# ---------- SEARCH ----------
@app.route('/search')
def search_notes():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])

    try:
        conn = get_db_connection()
        c = conn.cursor()
        # search filename (case-insensitive)
        pattern = f"%{q}%"
        c.execute("SELECT id, filename, uploaded_by FROM notes WHERE filename ILIKE %s LIMIT 12", (pattern,))
        rows = c.fetchall()
        conn.close()

        results = [
            {
                'id': r[0],
                'title': r[1],
                'excerpt': f"Uploaded by: {r[2]}"
            }
            for r in rows
        ]
        return jsonify(results)
    except Exception as e:
        current_app.logger.exception("Search error")
        return jsonify({'error': 'server error', 'details': str(e)}), 500

# ---------- EDIT NOTE ----------
@app.route("/edit_note/<int:note_id>", methods=["GET", "POST"])
def edit_note(note_id):
    if "username" not in session or session["role"] != "admin":
        return redirect(url_for("login"))

    conn = get_db_connection()
    c = conn.cursor()

    if request.method == "POST":
        new_title = request.form.get("title", "").strip()
        new_content = request.form.get("content", "").strip()
        if new_title and new_content:
            c.execute("UPDATE notes SET title=%s, content=%s WHERE id=%s", (new_title, new_content, note_id))
            conn.commit()
            conn.close()
            return redirect(url_for("notes"))

    c.execute("SELECT * FROM notes WHERE id=%s", (note_id,))
    note = c.fetchone()
    conn.close()

    return render_template("edit_note.html", title="Edit Note", note=note)

@app.route("/admin/users", methods=["GET"])
def admin_users():
    if "username" not in session or session["role"] != "admin":
        return redirect(url_for("login"))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE role = 'admin'")
    admins = c.fetchall()
    conn.close()

    return render_template("admin_users.html", title="Admin Users", admins=admins)

# ---------- ADD TEACHER ----------
@app.route("/admin/add_teacher", methods=["GET", "POST"])
def add_teacher():
    if "username" not in session or session["role"] != "admin":
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not email or not password:
            flash("⚠️ All fields are required!", "error")
            return redirect(url_for("add_teacher"))

        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE username=%s OR email=%s", (username, email))
            if c.fetchone():
                flash("⚠️ Username or email already exists!", "error")
                conn.close()
                return redirect(url_for("add_teacher"))

            c.execute("INSERT INTO users (username, email, password, role, created_at) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)",
                      (username, email, password, "teacher"))
            conn.commit()
            conn.close()

            flash("✅ Teacher added successfully!", "success")
            return redirect(url_for("dashboard"))
        except Exception as e:
            flash(f"⚠️ Database error: {str(e)}", "error")
            return redirect(url_for("add_teacher"))

    return render_template("add_teacher.html", title="Add Teacher")

# ---------- ADD STUDENT ----------
@app.route("/admin/add_student", methods=["GET", "POST"])
def add_student():
    if "username" not in session or session["role"] != "admin":
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not email or not password:
            flash("⚠️ All fields are required!", "error")
            return redirect(url_for("add_student"))

        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE username=%s OR email=%s", (username, email))
            if c.fetchone():
                flash("⚠️ Username or email already exists!", "error")
                conn.close()
                return redirect(url_for("add_student"))

            c.execute("INSERT INTO users (username, email, password, role, created_at) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)",
                      (username, email, password, "student"))
            conn.commit()
            conn.close()

            flash("✅ Student added successfully!", "success")
            return redirect(url_for("dashboard"))
        except Exception as e:
            flash(f"⚠️ Database error: {str(e)}", "error")
            return redirect(url_for("add_student"))

    return render_template("add_teacher.html", title="Add Student")

# ---------- VIEW USERS ----------
@app.route("/admin/view_users", methods=["GET"])
def view_users():
    if "username" not in session or session["role"] != "admin":
        return redirect(url_for("login"))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, username, email, role FROM users ORDER BY id ASC")
    users = c.fetchall()
    conn.close()

    return render_template("view_users.html", title="View Users", users=users)

# ---------- DELETE USER ----------
@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
def delete_user(user_id):
    if "username" not in session or session["role"] != "admin":
        return redirect(url_for("login"))

    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id=%s", (user_id,))
        conn.commit()
        conn.close()

        flash("✅ User deleted successfully!", "success")
    except Exception as e:
        flash(f"⚠️ Database error: {str(e)}", "error")

    return redirect(url_for("view_users"))

# ---------- RUN ----------
if __name__ == "__main__":
    app.run(debug=True)
