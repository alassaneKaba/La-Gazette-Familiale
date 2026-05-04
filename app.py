from flask import Flask, render_template, request, redirect, session, jsonify, flash, url_for
import sqlite3, os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timezone
from flask_mail import Mail, Message
import time, random
from PIL import Image
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'une_cle_tres_secrete_de_developpement')

# Configuration Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'alassanekaba2008@gmail.com'
app.config['MAIL_PASSWORD'] = 'vecuhnaguawnofzc'
app.config['MAIL_DEFAULT_SENDER'] = ('La Gazette Familiale', 'alassanekaba2008@gmail.com')

mail = Mail(app)

# Configuration Dossiers
UPLOAD_FOLDER = "static/uploads"
AVATAR_FOLDER = "static/avatars"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["AVATAR_FOLDER"] = AVATAR_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AVATAR_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'webm'}

# --- GESTION BASE DE DONNÉES ---
DATABASE_URL = os.environ.get('DATABASE_URL')


def get_db():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    else:
        conn = sqlite3.connect("database.db")
        conn.row_factory = sqlite3.Row
        return conn


def query_db(query, args=(), one=False):
    db = get_db()
    if DATABASE_URL:
        query = query.replace('?', '%s')
        cur = db.cursor(cursor_factory=RealDictCursor)
    else:
        cur = db.cursor()

    cur.execute(query, args)

    if query.strip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
        res = None
        if DATABASE_URL and "RETURNING" in query.upper():
            res = cur.fetchone()
        db.commit()
        last_id = res[0] if res else (cur.lastrowid if not DATABASE_URL else None)
        cur.close()
        db.close()
        return last_id

    rv = cur.fetchall()
    res = (rv[0] if rv else None) if one else rv
    cur.close()
    db.close()
    return res


# --- UTILITAIRES ---
def process_image(file_path):
    with Image.open(file_path) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        max_size = 1200
        if img.width > max_size:
            ratio = max_size / float(img.width)
            new_height = int(float(img.height) * float(ratio))
            img = img.resize((max_size, new_height), Image.Resampling.LANCZOS)
        img.save(file_path, "JPEG", optimize=True, quality=85)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            flash("Veuillez vous connecter.", "info")
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


# --- ROUTES ---

@app.route("/")
def home():
    posts_query = query_db("""
        SELECT posts.*, users.avatar AS user_avatar,
            (SELECT COUNT(*) FROM reactions WHERE post_id=posts.id AND type='thumb') as thumbs,
            (SELECT COUNT(*) FROM reactions WHERE post_id=posts.id AND type='heart') as hearts
        FROM posts
        JOIN users ON posts.username = users.username
        ORDER BY posts.id DESC
    """)
    posts = [dict(row) for row in posts_query]
    for post in posts:
        post['medias'] = query_db("SELECT * FROM post_medias WHERE post_id = ?", (post['id'],))

    comments_query = query_db('''
        SELECT comments.*, users.avatar AS comm_avatar,
            (SELECT COUNT(*) FROM comment_reactions WHERE comment_id = comments.id) as like_count
        FROM comments 
        JOIN users ON comments.username = users.username
        ORDER BY comments.created_at ASC
    ''')
    comments = [dict(row) for row in comments_query]
    return render_template("home.html", posts=posts, comments=comments)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        user = query_db("SELECT * FROM users WHERE email = ?", (email,), one=True)
        if user and check_password_hash(user["password"], password):
            if user["is_approved"] == 0:
                flash("Compte en attente de validation.", "info")
                return render_template("login.html")
            session.clear()
            session["user"] = user["username"]
            session["user_id"] = user["id"]
            session["is_admin"] = user["is_admin"]
            session["user_avatar"] = user["avatar"] or "default.png"
            return redirect(url_for("home"))
        flash("Identifiants incorrects", "danger")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        firstname = request.form.get("firstname")
        lastname = request.form.get("lastname")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")
        avatar = request.files.get("avatar")
        filename = "default.png"
        if avatar:
            filename = secure_filename(f"{username}_{avatar.filename}")
            avatar.save(os.path.join(app.config["AVATAR_FOLDER"], filename))
        hashed_password = generate_password_hash(password)
        try:
            query_db(
                "INSERT INTO users (firstname, lastname, email, username, password, avatar, is_approved, is_admin) VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
                (firstname, lastname, email, username, hashed_password, filename))
            flash("Demande envoyée ! En attente de validation.", "info")
            return redirect("/login")
        except:
            flash("Pseudo ou Email déjà utilisé.", "danger")
    return render_template("register.html")


@app.route("/post", methods=["POST"])
@login_required
def post():
    content = request.form.get("content")
    files = request.files.getlist("images")

    # Pour PostgreSQL, on force le retour de l'ID
    query = "INSERT INTO posts (username, content) VALUES (?, ?) RETURNING id" if DATABASE_URL else "INSERT INTO posts (username, content) VALUES (?, ?)"
    post_id = query_db(query, (session["user"], content))

    for file in files:
        if file and file.filename != '':
            filename = secure_filename(f"{int(time.time())}_{file.filename}")
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(file_path)
            ext = filename.rsplit('.', 1)[1].lower()
            file_type = 'image' if ext in ['jpg', 'jpeg', 'png', 'gif'] else 'video'
            if file_type == 'image': process_image(file_path)
            query_db("INSERT INTO post_medias (post_id, filename, file_type) VALUES (?, ?, ?)",
                     (post_id, filename, file_type))
    return redirect("/")


@app.template_filter('relative_time')
def relative_time(date_str):
    if not date_str: return "Date inconnue"
    try:
        if isinstance(date_str, datetime):
            past = date_str
        else:
            past = datetime.strptime(str(date_str).split('.')[0], '%Y-%m-%d %H:%M:%S')
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        diff = now - past
        if diff.days == 0:
            if diff.seconds < 60: return "À l'instant"
            if diff.seconds < 3600: return f"Il y a {diff.seconds // 60} min"
            return f"Il y a {diff.seconds // 3600} h"
        if diff.days == 1: return "Hier"
        return past.strftime('%d/%m/%Y')
    except:
        return "Récemment"


# --- CONTEXT PROCESSORS ---
@app.context_processor
def inject_globals():
    if session.get('user'):
        u_count = query_db("SELECT COUNT(*) as count FROM users WHERE is_approved = 1", one=True)
        p_count = query_db("SELECT COUNT(*) as count FROM posts", one=True)
        unread = query_db("SELECT COUNT(*) as count FROM notifications WHERE username = ? AND is_read = 0",
                          (session['user'],), one=True)

        pending_c = 0
        if session.get('is_admin'):
            p_res = query_db("SELECT COUNT(*) as count FROM users WHERE is_approved = 0", one=True)
            pending_c = p_res['count'] if DATABASE_URL else p_res[0]

        return {
            'total_users': u_count['count'] if DATABASE_URL else u_count[0],
            'total_posts': p_count['count'] if DATABASE_URL else p_count[0],
            'unread_count': unread['count'] if DATABASE_URL else unread[0],
            'pending_count': pending_c
        }
    return {'total_users': 0, 'total_posts': 0, 'unread_count': 0, 'pending_count': 0}


@app.route("/admin/users")
def admin_users():
    pending = query_db("SELECT * FROM users WHERE is_approved = 0")
    return render_template("admin.html", users=pending)


@app.route("/admin/approve/<int:user_id>", methods=["POST"])
def approve_user(user_id):
    if not session.get("is_admin"): return redirect("/")
    query_db("UPDATE users SET is_approved = 1 WHERE id = ?", (user_id,))
    flash("Utilisateur approuvé.", "success")
    return redirect("/admin/users")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# --- INITIALISATION DE LA BASE ---
def init_db():
    db = get_db()
    cur = db.cursor()
    # PostgreSQL utilise SERIAL et TIMESTAMP
    id_type = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    date_type = "TIMESTAMP" if DATABASE_URL else "DATETIME"

    cur.execute(
        f"CREATE TABLE IF NOT EXISTS users (id {id_type}, email TEXT UNIQUE, firstname TEXT, lastname TEXT, username TEXT UNIQUE, password TEXT, avatar TEXT, cover TEXT, bio TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)")
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS posts (id {id_type}, username TEXT, content TEXT, likes INTEGER DEFAULT 0, image TEXT, created_at {date_type} DEFAULT CURRENT_TIMESTAMP)")
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS post_medias (id {id_type}, post_id INTEGER, filename TEXT, file_type TEXT, FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE)")
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS comments (id {id_type}, post_id INTEGER, username TEXT, content TEXT, parent_id INTEGER, created_at {date_type} DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE)")
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS reactions (id {id_type}, username TEXT, post_id INTEGER, type TEXT, UNIQUE(username, post_id))")
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS comment_reactions (user_id INTEGER, comment_id INTEGER, PRIMARY KEY (user_id, comment_id))")
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS notifications (id {id_type}, username TEXT, sender TEXT, message TEXT, post_id INTEGER, comment_id INTEGER, is_read INTEGER DEFAULT 0, created_at {date_type} DEFAULT CURRENT_TIMESTAMP)")
    db.commit()
    cur.close()
    db.close()


if __name__ == "__main__":
    init_db()  # Création des tables au lancement
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)