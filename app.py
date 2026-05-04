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
import threading

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuration de Flask-Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'alassanekaba2008@gmail.com'
app.config['MAIL_PASSWORD'] = 'vecuhnaguawnofzc'
app.config['MAIL_DEFAULT_SENDER'] = ('La Gazette Familiale', 'alassanekaba2008@gmail.com')

mail = Mail(app)

# Fonction d'envoi simplifiée et sécurisée
def send_async_email(flask_app, msg):
    with flask_app.app_context():
        try:
            print("--- TENTATIVE D'ENVOI MAIL EN COURS ---")
            mail.send(msg)
            print("--- MAIL ENVOYÉ AVEC SUCCÈS ---")
        except Exception as e:
            print(f"--- ERREUR DANS LE THREAD MAIL : {e} ---")

# Configuration des dossiers
UPLOAD_FOLDER = "static/uploads"
AVATAR_FOLDER = "static/avatars"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["AVATAR_FOLDER"] = AVATAR_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AVATAR_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'webm'}

# --- LOGIQUE DE BASE DE DONNÉES (SUPABASE / SQLITE) ---
DATABASE_URL = os.environ.get('DATABASE_URL')


def get_db():
    if DATABASE_URL:
        # Connexion PostgreSQL pour Render/Supabase
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        # Connexion SQLite pour le local
        conn = sqlite3.connect("database.db")
        conn.row_factory = sqlite3.Row
        return conn


def query_db(query, args=(), one=False):
    """Exécute une requête et gère la différence entre SQLite (?) et Postgres (%s)"""
    db = get_db()
    is_pg = DATABASE_URL is not None
    if is_pg:
        query = query.replace('?', '%s')
        cur = db.cursor(cursor_factory=RealDictCursor)
    else:
        cur = db.cursor()

    try:
        cur.execute(query, args)
        if query.strip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            db.commit()
            if is_pg:
                return None
            return cur.lastrowid

        rv = cur.fetchall()
        return (rv[0] if rv else None) if one else rv
    finally:
        cur.close()
        db.close()


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
            flash("Veuillez vous connecter pour accéder à cette page.", "info")
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


# --- ROUTES API ---

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
    posts = [dict(row) for row in (posts_query or [])]
    for post in posts:
        post['medias'] = query_db("SELECT * FROM post_medias WHERE post_id = ?", (post['id'],))

    comments_query = query_db('''
        SELECT comments.*, users.avatar AS comm_avatar,
            (SELECT COUNT(*) FROM comment_reactions WHERE comment_id = comments.id) as like_count
        FROM comments 
        JOIN users ON comments.username = users.username
        ORDER BY comments.created_at ASC
    ''')
    comments = [dict(row) for row in (comments_query or [])]
    return render_template("home.html", posts=posts, comments=comments)


@app.route("/admin/users")
def admin_users():
    pending = query_db("SELECT * FROM users WHERE is_approved = 0")
    return render_template("admin.html", users=pending)


@app.route("/admin/approve/<int:user_id>", methods=["POST"])
def approve_user(user_id):
    if not session.get("is_admin"):
        return redirect("/")
    user = query_db("SELECT email, firstname FROM users WHERE id = ?", (user_id,), one=True)
    if user:
        try:
            # 1. On valide d'abord dans la base de données
            query_db("UPDATE users SET is_approved = 1 WHERE id = ?", (user_id,))
            # 2. Préparation du lien et du message
            login_url = request.host_url + "login"
            # 3. Création du message
            msg = Message("Bienvenue dans la tribu ! ✅", recipients=[user['email']])
            msg.html = f"""
            <h1>🌳 La Gazette Familiale</h1>
            <p>Bonjour {user['firstname']},</p>
            <p>Bonne nouvelle ! Ton compte a été validé par l'administrateur.</p>
            <p>Tu peux maintenant te connecter pour partager tes souvenirs avec la famille ici :</p>
            <p><a href="{login_url}" style="padding: 10px 20px; background-color: #28a745; color: white; text-decoration: none; border-radius: 5px;">Se connecter à La Gazette</a></p>
            <p>À très vite !</p>
            """
            # 3. Lancement du Thread de manière simple
            # On passe directement 'app' qui est ton objet Flask global
            thr = threading.Thread(target=send_async_email, args=(app, msg))
            thr.daemon = True  # Optionnel: assure que le thread ne bloque pas l'arrêt du serveur
            thr.start()
            flash(f"Utilisateur {user['firstname']} approuvé !", "success")
        except Exception as e:
            print(f"ERREUR DANS LA ROUTE: {str(e)}")
            flash(f"Erreur lors de l'approbation : {str(e)}", "danger")
    return redirect("/admin/users")


@app.route("/admin/reject/<int:user_id>", methods=["POST"])
def reject_user(user_id):
    if not session.get("is_admin"):
        return redirect("/")
    # On récupère les infos avant de supprimer l'utilisateur
    user = query_db("SELECT email, firstname, avatar FROM users WHERE id = ?", (user_id,), one=True)
    if user:
        # 1. Suppression physique de l'avatar s'il existe
        if user['avatar'] and user['avatar'] != 'default.png':
            try:
                os.remove(os.path.join(app.config["AVATAR_FOLDER"], user['avatar']))
            except Exception as e:
                print(f"Erreur suppression fichier : {e}")
        # 2. Suppression dans la base de données (très rapide)
        query_db("DELETE FROM users WHERE id = ?", (user_id,))
        # 3. Préparation et envoi du mail de refus en arrière-plan
        msg = Message("Demande d'accès refusée ❌", recipients=[user['email']])
        msg.body = f"Bonjour {user['firstname']},\n\nNous avons bien reçu votre demande d'inscription à La Gazette Familiale, mais nous ne pouvons pas l'accepter pour le moment.\n\nCordialement,\nL'équipe de La Gazette."
        thread = threading.Thread(target=send_async_email, args=(app, msg))
        thread.start()
        flash(f"La demande de {user['firstname']} a été refusée et le compte supprimé.", "info")
    return redirect("/admin/users")


@app.context_processor
def inject_global_stats():
    if session.get('user'):
        u = query_db("SELECT COUNT(*) as c FROM users WHERE is_approved = 1", one=True)
        p = query_db("SELECT COUNT(*) as c FROM posts", one=True)
        return {'total_users': u['c'], 'total_posts': p['c']}
    return {'total_users': 0, 'total_posts': 0}


@app.context_processor
def inject_pending_count():
    if session.get('is_admin'):
        count = query_db("SELECT COUNT(*) as total FROM users WHERE is_approved = 0", one=True)
        return {'pending_count': count['total']}
    return {'pending_count': 0}


@app.context_processor
def inject_notifications_count():
    if session.get('user'):
        count = query_db("SELECT COUNT(*) as c FROM notifications WHERE username = ? AND is_read = 0",
                         (session['user'],), one=True)
        return {'unread_count': count['c']}
    return {'unread_count': 0}


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
            session["user"], session["user_id"], session["is_admin"] = user["username"], user["id"], user["is_admin"]
            session["user_avatar"] = user["avatar"] if user["avatar"] else "default.png"
            return redirect(url_for("home"))
        flash("Email ou mot de passe incorrect", "danger")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        firstname, lastname, email = request.form.get("firstname"), request.form.get("lastname"), request.form.get(
            "email")
        username, password = request.form.get("username"), request.form.get("password")
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
            flash("Demande envoyée !", "info")
            return redirect("/login")
        except:
            flash("Erreur d'inscription.", "danger")
    return render_template("register.html")


@app.route("/post", methods=["POST"])
@login_required
def post():
    content = request.form.get("content")
    files = request.files.getlist("images")

    # Pour obtenir l'ID sur Postgres vs SQLite
    db = get_db()
    cur = db.cursor()
    if DATABASE_URL:
        cur.execute("INSERT INTO posts (username, content) VALUES (%s, %s) RETURNING id", (session["user"], content))
        post_id = cur.fetchone()[0]
    else:
        cur.execute("INSERT INTO posts (username, content) VALUES (?, ?)", (session["user"], content))
        post_id = cur.lastrowid
    db.commit()
    cur.close()
    db.close()

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
        now = datetime.now()
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
            query_db("INSERT INTO notifications (username, sender, message, post_id) VALUES (?, ?, ?, ?)",
                     (owner['username'], username, "a réagi à votre post", post_id))
    counts = query_db("SELECT type, COUNT(*) as c FROM reactions WHERE post_id=? GROUP BY type", (post_id,))
    res = {"thumb": 0, "heart": 0}
    for r in counts: res[r['type']] = r['c']
    return jsonify(res)


@app.route("/comment/<int:post_id>", methods=["POST"])
def add_comment(post_id):
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    content, parent_id = request.form.get("content"), request.form.get("parent_id")

    db = get_db()
    cur = db.cursor()
    if DATABASE_URL:
        cur.execute(
            "INSERT INTO comments (post_id, username, content, parent_id) VALUES (%s, %s, %s, %s) RETURNING id, created_at",
            (post_id, session["user"], content, parent_id))
        r = cur.fetchone()
        cid, cat = r[0], r[1]
    else:
        cur.execute("INSERT INTO comments (post_id, username, content, parent_id) VALUES (?, ?, ?, ?)",
                    (post_id, session["user"], content, parent_id))
        cid = cur.lastrowid
        db.commit()
        cat = query_db("SELECT created_at FROM comments WHERE id=?", (cid,), one=True)['created_at']
    if DATABASE_URL: db.commit()
    cur.close()
    db.close()

    owner = query_db("SELECT username FROM posts WHERE id=?", (post_id,), one=True)
    if owner and owner['username'] != session['user']:
        query_db("INSERT INTO notifications (username, sender, message, post_id, comment_id) VALUES (?, ?, ?, ?, ?)",
                 (owner['username'], session['user'], "a commenté", post_id, cid))
    return jsonify({"username": session["user"], "content": content, "created_at": str(cat), "comment_id": cid,
                    "parent_id": parent_id})


@app.route('/react_comment/<int:comment_id>', methods=['POST'])
def react_comment(comment_id):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    uid, username = session.get('user_id'), session.get('user')
    res = query_db("SELECT username, post_id, content FROM comments WHERE id = ?", (comment_id,), one=True)
    if not res: return jsonify({"error": "notFound"}), 404

    exists = query_db("SELECT 1 FROM comment_reactions WHERE user_id = ? AND comment_id = ?", (uid, comment_id),
                      one=True)
    if exists:
        query_db("DELETE FROM comment_reactions WHERE user_id = ? AND comment_id = ?", (uid, comment_id))
    else:
        query_db("INSERT INTO comment_reactions (user_id, comment_id) VALUES (?, ?)", (uid, comment_id))
        if res['username'] != username:
            query_db(
                "INSERT INTO notifications (username, sender, message, post_id, comment_id) VALUES (?, ?, ?, ?, ?)",
                (res['username'], username, "a aimé votre commentaire", res['post_id'], comment_id))

    count = query_db("SELECT COUNT(*) as c FROM comment_reactions WHERE comment_id = ?", (comment_id,), one=True)
    return jsonify({"total": count['c']})


@app.route("/user/<username>")
@login_required
def profile(username):
    u = query_db("SELECT * FROM users WHERE username = ?", (username,), one=True)
    if not u: return redirect(url_for('home'))
    posts = [dict(row) for row in query_db(
        "SELECT posts.*, users.avatar AS user_avatar FROM posts JOIN users ON posts.username = users.username WHERE posts.username=? ORDER BY posts.id DESC",
        (username,))]
    for post in posts:
        post['medias'] = query_db("SELECT filename, file_type FROM post_medias WHERE post_id = ?", (post['id'],))
        post['comments'] = query_db(
            "SELECT comments.*, users.avatar AS user_avatar FROM comments JOIN users ON comments.username = users.username WHERE post_id = ?",
            (post['id'],))
    return render_template("profile.html", posts=posts, user=u, posts_count=len(posts))


@app.route("/upload_cover", methods=["POST"])
@login_required
def upload_cover():
    file = request.files.get('cover')
    if file:
        filename = secure_filename(f"cover_{session['user']}_{file.filename}")
        file.save(os.path.join(app.config['AVATAR_FOLDER'], filename))
        query_db("UPDATE users SET cover = ? WHERE username = ?", (filename, session['user']))
        return jsonify({"success": True, "filename": filename})
    return jsonify({"error": "Non"}), 400


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        new_pw, file = request.form.get("password"), request.files.get("avatar")
        if file and file.filename != "":
            filename = secure_filename(file.filename)
            file.save(os.path.join(AVATAR_FOLDER, filename))
            query_db("UPDATE users SET avatar=? WHERE username=?", (filename, session["user"]))
        if new_pw:
            query_db("UPDATE users SET password=? WHERE username=?", (generate_password_hash(new_pw), session["user"]))
        return redirect("/settings")
    return render_template("settings.html")


@app.route("/delete_account", methods=["POST"])
@login_required
def delete_account():
    query_db("DELETE FROM users WHERE username=?", (session["user"],))
    session.clear()
    return redirect("/")


@app.route("/delete/<int:post_id>", methods=["POST"])
def delete_post(post_id):
    query_db("DELETE FROM posts WHERE id = ? AND username = ?", (post_id, session["user"]))
    return redirect(url_for("home"))


@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
@login_required
def delete_comment(comment_id):
    query_db("DELETE FROM comments WHERE id = ? AND username = ?", (comment_id, session['user']))
    return jsonify({"success": True})


@app.route('/delete_notification/<int:notif_id>', methods=['POST'])
@login_required
def delete_notification(notif_id):
    query_db("DELETE FROM notifications WHERE id = ? AND username = ?", (notif_id, session['user']))
    return jsonify({'success': True})


@app.route('/edit_comment/<int:comment_id>', methods=['POST'])
@login_required
def edit_comment(comment_id):
    new_c = request.form.get('content')
    query_db("UPDATE comments SET content = ? WHERE id = ? AND username = ?", (new_c, comment_id, session['user']))
    return jsonify({"success": True, "content": new_c})


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/post/<int:post_id>")
@login_required
def view_post(post_id):
    post = query_db(
        "SELECT posts.*, users.avatar AS user_avatar FROM posts JOIN users ON posts.username = users.username WHERE posts.id = ?",
        (post_id,), one=True)
    if not post: return redirect(url_for('home'))
    post = dict(post)
    post['medias'] = query_db("SELECT * FROM post_medias WHERE post_id = ?", (post_id,))
    comments = query_db(
        "SELECT comments.*, users.avatar AS comm_avatar, (SELECT COUNT(*) FROM comment_reactions WHERE comment_id = comments.id) as like_count FROM comments JOIN users ON comments.username = users.username WHERE post_id = ?",
        (post_id,))
    return render_template("home.html", posts=[post], comments=comments)


@app.route("/notifications")
@login_required
def notifications():
    notifs = query_db("SELECT * FROM notifications WHERE username = ? ORDER BY created_at DESC", (session['user'],))
    recent = query_db("SELECT username, content, created_at FROM posts ORDER BY id DESC LIMIT 3")
    query_db("UPDATE notifications SET is_read = 1 WHERE username = ?", (session["user"],))
    return render_template("notifications.html", notifs=notifs, recent_activity=recent,
                           pensee_du_jour="La famille est un trésor.")


@app.route("/notifications/mark-all-read")
@login_required
def mark_all_read():
    query_db("UPDATE notifications SET is_read = 1 WHERE username = ?", (session["user"],))
    return redirect(url_for('notifications'))


# --- INITIALISATION BASE ---

def init_db():
    db = get_db()
    cur = db.cursor()
    id_t = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    dt_t = "TIMESTAMP" if DATABASE_URL else "DATETIME"
    try:
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS users (id {id_t}, email TEXT UNIQUE, firstname TEXT, lastname TEXT, username TEXT UNIQUE, password TEXT, avatar TEXT, cover TEXT, bio TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)")
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS posts (id {id_t}, username TEXT, content TEXT, created_at {dt_t} DEFAULT CURRENT_TIMESTAMP)")
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS post_medias (id {id_t}, post_id INTEGER, filename TEXT, file_type TEXT, FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE)")
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS comments (id {id_t}, post_id INTEGER, username TEXT, content TEXT, parent_id INTEGER, created_at {dt_t} DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE)")
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS comment_reactions (user_id INTEGER, comment_id INTEGER, PRIMARY KEY (user_id, comment_id))")
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS reactions (id {id_t}, username TEXT, post_id INTEGER, type TEXT, UNIQUE(username, post_id))")
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS notifications (id {id_t}, username TEXT, sender TEXT, message TEXT, post_id INTEGER, comment_id INTEGER, is_read INTEGER DEFAULT 0, created_at {dt_t} DEFAULT CURRENT_TIMESTAMP)")
        db.commit()
    except Exception as e:
        print(f"Erreur init: {e}")
    finally:
        cur.close()
        db.close()

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)