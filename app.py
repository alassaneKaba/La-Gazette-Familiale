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

# Configuration de Flask-Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'alassanekaba2008@gmail.com'
app.config['MAIL_PASSWORD'] = 'vecuhnaguawnofzc'
app.config['MAIL_DEFAULT_SENDER'] = ('La Gazette Familiale', 'alassanekaba2008@gmail.com')

mail = Mail(app)

# Configuration des dossiers
UPLOAD_FOLDER = "static/uploads"
AVATAR_FOLDER = "static/avatars"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["AVATAR_FOLDER"] = AVATAR_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AVATAR_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'webm'}

# --- GESTION BASE DE DONNÉES (SUPABASE / SQLITE) ---
DATABASE_URL = os.environ.get('DATABASE_URL')


def get_db():
    if DATABASE_URL:
        # Connexion PostgreSQL pour Render/Supabase
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    else:
        # Connexion SQLite pour le local
        conn = sqlite3.connect("database.db")
        conn.row_factory = sqlite3.Row
        return conn


def query_db(query, args=(), one=False):
    """Utilitaire pour rendre les requêtes compatibles SQLite (?) et PostgreSQL (%s)"""
    db = get_db()
    if DATABASE_URL:
        # Adaptation auto des ? en %s pour PostgreSQL
        query = query.replace('?', '%s')
        cur = db.cursor(cursor_factory=RealDictCursor)
    else:
        cur = db.cursor()

    cur.execute(query, args)
    rv = cur.fetchall()

    # Gestion du commit automatique pour les modifs
    if query.strip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
        db.commit()
        last_id = cur.lastrowid if not DATABASE_URL else None  # lastrowid est complexe en PG
        cur.close()
        db.close()
        return last_id

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


# --- ROUTES API & AJAX ---

@app.route("/check_email/<email>")
def check_email(email):
    user = query_db("SELECT id FROM users WHERE email = ?", (email,), one=True)
    return jsonify({"exists": True if user else False})


@app.route('/update_profile_ajax', methods=['POST'])
def update_profile_ajax():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Session expirée'}), 401
    firstname = request.form.get('firstname')
    lastname = request.form.get('lastname')
    bio = request.form.get('bio')
    avatar_file = request.files.get('avatar')
    username = session['user']
    new_avatar_name = None

    if avatar_file and avatar_file.filename != '':
        old_user = query_db("SELECT avatar FROM users WHERE username = ?", (username,), one=True)
        if old_user and old_user['avatar'] and old_user['avatar'] != 'default.png':
            try:
                os.remove(os.path.join(app.config['AVATAR_FOLDER'], old_user['avatar']))
            except:
                pass
        new_avatar_name = f"{username}_avatar_{int(time.time())}.png"
        avatar_file.save(os.path.join(app.config['AVATAR_FOLDER'], new_avatar_name))
        query_db("UPDATE users SET avatar=? WHERE username=?", (new_avatar_name, username))

    query_db("UPDATE users SET firstname=?, lastname=?, bio=? WHERE username=?", (firstname, lastname, bio, username))
    return jsonify({'success': True, 'new_avatar': new_avatar_name})


@app.route('/delete_profile_ajax', methods=['POST'])
@login_required
def delete_profile_ajax():
    username = session['user']
    user_data = query_db("SELECT avatar, cover FROM users WHERE username = ?", (username,), one=True)
    medias = query_db("SELECT m.filename FROM post_medias m JOIN posts p ON m.post_id = p.id WHERE p.username = ?",
                      (username,))

    if user_data:
        for key in ['avatar', 'cover']:
            if user_data[key] and user_data[key] not in ['default.png', 'default_cover.png']:
                try:
                    os.remove(os.path.join(app.config['AVATAR_FOLDER'], user_data[key]))
                except:
                    pass
    for m in medias:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], m['filename']))
        except:
            pass

    query_db("DELETE FROM users WHERE username = ?", (username,))
    session.clear()
    return jsonify({'success': True})


# --- ROUTES PRINCIPALES ---

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


@app.route("/admin/users")
def admin_users():
    pending = query_db("SELECT * FROM users WHERE is_approved = 0")
    return render_template("admin.html", users=pending)


@app.route("/admin/approve/<int:user_id>", methods=["POST"])
def approve_user(user_id):
    if not session.get("is_admin"): return redirect("/")
    user = query_db("SELECT email, firstname FROM users WHERE id = ?", (user_id,), one=True)
    if user:
        query_db("UPDATE users SET is_approved = 1 WHERE id = ?", (user_id,))
        try:
            msg = Message("Bienvenue dans la tribu ! ✅", recipients=[user['email']])
            msg.html = f"<h1>🌳 La Gazette Familiale</h1><p>Bonjour {user['firstname']}, ton compte est validé !</p>"
            mail.send(msg)
            flash(f"Utilisateur {user['firstname']} approuvé.", "success")
        except Exception as e:
            flash("Approuvé, mais erreur d'envoi mail.", "warning")
    return redirect("/admin/users")


@app.route("/admin/reject/<int:user_id>", methods=["POST"])
def reject_user(user_id):
    if not session.get("is_admin"): return redirect("/")
    user = query_db("SELECT email, firstname, avatar FROM users WHERE id = ?", (user_id,), one=True)
    if user:
        if user['avatar'] and user['avatar'] != 'default.png':
            try:
                os.remove(os.path.join(app.config["AVATAR_FOLDER"], user['avatar']))
            except:
                pass
        query_db("DELETE FROM users WHERE id = ?", (user_id,))
        try:
            msg = Message("Demande refusée ❌", recipients=[user['email']])
            msg.body = f"Bonjour {user['firstname']}, votre demande n'a pas été acceptée."
            mail.send(msg)
        except:
            pass
    return redirect("/admin/users")


# --- CONTEXT PROCESSORS ---
@app.context_processor
def inject_globals():
    if session.get('user'):
        u_count = query_db("SELECT COUNT(*) FROM users WHERE is_approved = 1", one=True)
        p_count = query_db("SELECT COUNT(*) FROM posts", one=True)
        # Gestion de la différence de retour entre SQLite et PG
        total_u = u_count[0] if isinstance(u_count, tuple) else u_count['count'] if DATABASE_URL else u_count[0]
        total_p = p_count[0] if isinstance(p_count, tuple) else p_count['count'] if DATABASE_URL else p_count[0]

        unread = query_db("SELECT COUNT(*) FROM notifications WHERE username = ? AND is_read = 0", (session['user'],),
                          one=True)
        unread_c = unread[0] if isinstance(unread, tuple) else unread['count'] if DATABASE_URL else unread[0]

        pending_c = 0
        if session.get('is_admin'):
            p_res = query_db("SELECT COUNT(*) FROM users WHERE is_approved = 0", one=True)
            pending_c = p_res[0] if isinstance(p_res, tuple) else p_res['count'] if DATABASE_URL else p_res[0]

        return {'total_users': total_u, 'total_posts': total_p, 'unread_count': unread_c, 'pending_count': pending_c}
    return {'total_users': 0, 'total_posts': 0, 'unread_count': 0, 'pending_count': 0}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email_saisi = request.form.get("email")
        password_saisi = request.form.get("password")
        user = query_db("SELECT * FROM users WHERE email = ?", (email_saisi,), one=True)
        if user and check_password_hash(user["password"], password_saisi):
            if user["is_approved"] == 0:
                flash("Compte en attente de validation.", "info")
                return render_template("login.html")
            session.clear()
            session["user"] = user["username"]
            session["user_id"] = user["id"]
            session["is_admin"] = user["is_admin"]
            session["user_avatar"] = user["avatar"] if user["avatar"] else "default.png"
            return redirect(url_for("home"))
        flash("Email ou mot de passe incorrect", "danger")
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
            try:
                msg = Message("Nouvelle adhésion 🌳", recipients=["alassanekaba2008@gmail.com"])
                msg.body = f"Nouvel inscrit : {firstname} {lastname} (@{username})"
                mail.send(msg)
            except:
                pass
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
    # Pour récupérer l'ID avec PG, il faudrait un RETURNING, mais on simplifie ici
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "INSERT INTO posts (username, content) VALUES (%s, %s) RETURNING id" if DATABASE_URL else "INSERT INTO posts (username, content) VALUES (?, ?)",
        (session["user"], content))
    post_id = cur.fetchone()[0] if DATABASE_URL else cur.lastrowid
    db.commit()

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
            past = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
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


@app.route("/react/<int:post_id>/<reaction_type>", methods=["POST"])
def react(post_id, reaction_type):
    if not session.get("user"): return jsonify({"error": "Unauthorized"}), 403
    username = session["user"]
    owner = query_db("SELECT username FROM posts WHERE id=?", (post_id,), one=True)
    existing = query_db("SELECT type FROM reactions WHERE username=? AND post_id=?", (username, post_id), one=True)

    if existing:
        if existing['type'] == reaction_type:
            query_db("DELETE FROM reactions WHERE username=? AND post_id=?", (username, post_id))
        else:
            query_db("UPDATE reactions SET type=? WHERE username=? AND post_id=?", (reaction_type, username, post_id))
    else:
        query_db("INSERT INTO reactions (username, post_id, type) VALUES (?, ?, ?)", (username, post_id, reaction_type))
        if owner and owner['username'] != username:
            msg = "a aimé votre publication" if reaction_type == 'heart' else "a réagi à votre publication"
            query_db("INSERT INTO notifications (username, sender, message, post_id) VALUES (?, ?, ?, ?)",
                     (owner['username'], username, msg, post_id))

    counts = query_db("SELECT type, COUNT(*) as c FROM reactions WHERE post_id=? GROUP BY type", (post_id,))
    result = {"thumb": 0, "heart": 0}
    for row in counts: result[row['type']] = row['c']
    return jsonify(result)


@app.route("/comment/<int:post_id>", methods=["POST"])
def add_comment(post_id):
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    content, parent_id = request.form.get("content"), request.form.get("parent_id")

    db = get_db()
    cur = db.cursor()
    cur.execute(
        "INSERT INTO comments (post_id, username, content, parent_id) VALUES (%s, %s, %s, %s) RETURNING id, created_at" if DATABASE_URL else "INSERT INTO comments (post_id, username, content, parent_id) VALUES (?, ?, ?, ?)",
        (post_id, session["user"], content, parent_id))
    res = cur.fetchone()
    comment_id = res[0] if DATABASE_URL else cur.lastrowid
    created_at = res[1] if DATABASE_URL else \
    query_db("SELECT created_at FROM comments WHERE id=?", (comment_id,), one=True)['created_at']
    db.commit()

    owner = query_db("SELECT username FROM posts WHERE id=?", (post_id,), one=True)
    if owner and owner['username'] != session['user']:
        query_db("INSERT INTO notifications (username, sender, message, post_id, comment_id) VALUES (?, ?, ?, ?, ?)",
                 (owner['username'], session['user'], "a commenté votre publication", post_id, comment_id))

    return jsonify(
        {"username": session["user"], "content": content, "created_at": str(created_at), "comment_id": comment_id,
         "parent_id": parent_id})


# --- FIN DU FICHIER (LES AUTRES ROUTES RESTENT IDENTIQUES EN UTILISANT query_db) ---

@app.route("/user/<username>")
@login_required
def profile(username):
    user_info = query_db("SELECT * FROM users WHERE username = ?", (username,), one=True)
    if not user_info: return redirect(url_for('home'))
    posts = [dict(row) for row in query_db(
        "SELECT posts.*, users.avatar AS user_avatar FROM posts JOIN users ON posts.username = users.username WHERE posts.username=? ORDER BY posts.id DESC",
        (username,))]
    for post in posts:
        post['medias'] = query_db("SELECT filename, file_type FROM post_medias WHERE post_id = ?", (post['id'],))
        post['comments'] = query_db(
            "SELECT comments.*, users.avatar AS user_avatar FROM comments JOIN users ON comments.username = users.username WHERE post_id = ? ORDER BY created_at ASC",
            (post['id'],))
    return render_template("profile.html", posts=posts, user=user_info)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


def init_db():
    db = get_db()
    cur = db.cursor()
    id_type = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS users (id {id_type}, email TEXT UNIQUE, firstname TEXT, lastname TEXT, username TEXT UNIQUE, password TEXT, avatar TEXT, cover TEXT, bio TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)")
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS posts (id {id_type}, username TEXT, content TEXT, likes INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS post_medias (id {id_type}, post_id INTEGER, filename TEXT, file_type TEXT, FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE)")
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS comments (id {id_type}, post_id INTEGER, username TEXT, content TEXT, parent_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE)")
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS reactions (id {id_type}, username TEXT, post_id INTEGER, type TEXT, UNIQUE(username, post_id))")
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS comment_reactions (user_id INTEGER, comment_id INTEGER, PRIMARY KEY (user_id, comment_id))")
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS notifications (id {id_type}, username TEXT, sender TEXT, message TEXT, post_id INTEGER, comment_id INTEGER, is_read INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    db.commit()
    cur.close()
    db.close()


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)