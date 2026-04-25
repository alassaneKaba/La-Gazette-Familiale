from flask import Flask, render_template, request, redirect, session, jsonify, flash, url_for
import sqlite3, os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuration des dossiers
UPLOAD_FOLDER = "static/uploads"
AVATAR_FOLDER = "static/avatars"  # Le chemin vers tes avatars

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["AVATAR_FOLDER"] = AVATAR_FOLDER  # CETTE LIGNE MANQUAIT PROBABLEMENT

# On s'assure que les dossiers existent sur l'ordinateur
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AVATAR_FOLDER, exist_ok=True)


# --- UTILITAIRES ---

def get_db():
    db = sqlite3.connect("database.db")
    db.row_factory = sqlite3.Row
    return db


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
    with get_db() as db:
        user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    return jsonify({"exists": True if user else False})


# --- ROUTES PRINCIPALES ---

@app.route("/")
def home():
    with get_db() as db:
        posts = db.execute("""
            SELECT posts.*, users.avatar AS user_avatar,
                (SELECT COUNT(*) FROM reactions WHERE post_id=posts.id AND type='thumb') as thumbs,
                (SELECT COUNT(*) FROM reactions WHERE post_id=posts.id AND type='heart') as hearts
            FROM posts
            JOIN users ON posts.username = users.username
            ORDER BY posts.id DESC
        """).fetchall()

        # Modification ici : on nomme l'avatar explicitement 'comm_avatar'
        comments = db.execute('''
            SELECT comments.*, users.avatar AS comm_avatar
            FROM comments 
            JOIN users ON comments.username = users.username
        ''').fetchall()
    return render_template("home.html", posts=posts, comments=comments)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

            if user and check_password_hash(user["password"], password):
                session["user"] = user["username"]
                # AJOUT DE L'AVATAR EN SESSION
                session["user_avatar"] = user["avatar"] if user["avatar"] else "default.png"
                return redirect("/")
            else:
                flash("Email ou mot de passe incorrect.", "danger")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        firstname = request.form.get("firstname")
        lastname = request.form.get("lastname")
        email = request.form.get("email")
        username = request.form.get("username")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        avatar = request.files.get("avatar")

        if password != confirm_password:
            flash("Les mots de passe ne correspondent pas.", "danger")
            return redirect("/register")

        filename = "default.png"
        if avatar:
            filename = secure_filename(f"{username}_{avatar.filename}")
            avatar.save(os.path.join(app.config["AVATAR_FOLDER"], filename))

        hashed_password = generate_password_hash(password)

        try:
            with get_db() as db:
                db.execute("INSERT INTO users (firstname, lastname, email, username, password, avatar) VALUES (?, ?, ?, ?, ?, ?)",
                           (firstname, lastname, email, username, hashed_password, filename))
                db.commit()
            flash("Compte créé ! Connectez-vous.", "success")
            return redirect("/login")
        except sqlite3.IntegrityError:
            flash("Ce nom d'utilisateur ou cet e-mail est déjà utilisé.", "danger")
            return redirect("/register")

    return render_template("register.html")


@app.route("/post", methods=["POST"])
@login_required
def post():
    content = request.form["content"]
    file = request.files.get("image")
    filename = None
    if file and file.filename != "":
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    with get_db() as db:
        db.execute("INSERT INTO posts (username, content, likes, image) VALUES (?, ?, 0, ?)",
                   (session["user"], content, filename))
        db.commit()
    return redirect("/")


@app.route("/react/<int:post_id>/<reaction_type>", methods=["POST"])
def react(post_id, reaction_type):
    # 1. Vérification session (Indispensable pour le JS)
    if not session.get("user"):
        return jsonify({"error": "Unauthorized"}), 403

    username = session["user"]
    with get_db() as db:
        # Récupérer le propriétaire du post pour la notification
        owner = db.execute("SELECT username FROM posts WHERE id=?", (post_id,)).fetchone()

        # Vérifier si l'utilisateur a déjà réagi
        existing = db.execute("SELECT type FROM reactions WHERE username=? AND post_id=?",
                              (username, post_id)).fetchone()

        if existing:
            if existing['type'] == reaction_type:
                # Annuler la réaction (Toggle)
                db.execute("DELETE FROM reactions WHERE username=? AND post_id=?", (username, post_id))
            else:
                # Changer le type (ex: de pouce à cœur)
                db.execute("UPDATE reactions SET type=? WHERE username=? AND post_id=?",
                           (reaction_type, username, post_id))
        else:
            # Nouvelle réaction
            db.execute("INSERT INTO reactions (username, post_id, type) VALUES (?, ?, ?)",
                       (username, post_id, reaction_type))

            # Notifier seulement s'il s'agit d'une NOUVELLE réaction et que ce n'est pas son propre post
            if owner and owner['username'] != username:
                db.execute("INSERT INTO notifications (username, message) VALUES (?, ?)",
                           (owner['username'], f"{username} a réagi à ton post !"))

        db.commit()

        # Recalculer les compteurs
        counts = db.execute("SELECT type, COUNT(*) as c FROM reactions WHERE post_id=? GROUP BY type",
                            (post_id,)).fetchall()

    # Préparer la réponse
    result = {"thumb": 0, "heart": 0}
    for row in counts:
        result[row['type']] = row['c']

    return jsonify(result)


@app.route("/comment/<int:post_id>", methods=["POST"])
def comment(post_id):
    if not session.get("user"):
        flash("Veuillez vous connecter pour commenter !", "info")
        return jsonify({"redirect": "/login"}), 403

    content = request.form["content"]
    username = session["user"]
    with get_db() as db:
        db.execute("INSERT INTO comments (post_id, username, content) VALUES (?, ?, ?)", (post_id, username, content))
        db.commit()
    return jsonify({"username": username, "content": content})


@app.route("/user/<username>")
def profile(username):
    with get_db() as db:
        posts = db.execute("""
            SELECT posts.*, users.avatar AS user_avatar,
                (SELECT COUNT(*) FROM reactions WHERE post_id=posts.id AND type='thumb') as thumbs,
                (SELECT COUNT(*) FROM reactions WHERE post_id=posts.id AND type='heart') as hearts
            FROM posts
            JOIN users ON posts.username = users.username
            WHERE posts.username=?
            ORDER BY posts.id DESC
        """, (username,)).fetchall()
    return render_template("profile.html", posts=posts, username=username)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        username = session["user"]
        new_password = request.form.get("password")
        file = request.files.get("avatar")
        with get_db() as db:
            if file and file.filename != "":
                filename = secure_filename(file.filename)
                file.save(os.path.join(AVATAR_FOLDER, filename))
                db.execute("UPDATE users SET avatar=? WHERE username=?", (filename, username))
                flash("Avatar mis à jour ! 📸", "success")
            if new_password:
                hashed_pw = generate_password_hash(new_password)
                db.execute("UPDATE users SET password=? WHERE username=?", (hashed_pw, username))
                flash("Mot de passe modifié ! 🔐", "success")
            db.commit()
        return redirect("/settings")
    return render_template("settings.html")


@app.route("/delete_account", methods=["POST"])
@login_required
def delete_account():
    username = session["user"]
    with get_db() as db:
        db.execute("DELETE FROM reactions WHERE username=?", (username,))
        db.execute("DELETE FROM comments WHERE username=?", (username,))
        db.execute("DELETE FROM posts WHERE username=?", (username,))
        db.execute("DELETE FROM notifications WHERE username=?", (username,))
        db.execute("DELETE FROM users WHERE username=?", (username,))
        db.commit()
    session.clear()
    flash("Compte supprimé définitivement.", "info")
    return redirect("/")


@app.route("/delete/<int:post_id>", methods=["POST"])
def delete_post(post_id):
    if "user" not in session:
        return redirect(url_for("login"))

    with get_db() as db:
        # On vérifie que c'est bien l'auteur qui supprime
        db.execute("DELETE FROM posts WHERE id = ? AND username = ?", (post_id, session["user"]))
        db.commit()

    # C'est cette ligne qui évite le "Not Found"
    return redirect(url_for("home"))

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")


@app.route("/notifications")
@login_required
def notifications():
    with get_db() as db:
        notifs = db.execute("SELECT message FROM notifications WHERE username=? ORDER BY id DESC",
                            (session["user"],)).fetchall()
    return render_template("notifications.html", notifs=notifs)


# --- INITIALISATION ---

def init_db():
    with sqlite3.connect("database.db") as db:
        # Table Users mise à jour avec Email, Prénom et Nom
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                email TEXT UNIQUE, 
                firstname TEXT, 
                lastname TEXT, 
                username TEXT UNIQUE, 
                password TEXT, 
                avatar TEXT
            )
        """)
        db.execute(
            "CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, content TEXT, likes INTEGER DEFAULT 0, image TEXT)")
        db.execute(
            "CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER, username TEXT, content TEXT)")
        db.execute(
            "CREATE TABLE IF NOT EXISTS reactions (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, post_id INTEGER, type TEXT, UNIQUE(username, post_id))")
        db.execute(
            "CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, message TEXT)")


init_db()

if __name__ == "__main__":
    app.run(debug=True)