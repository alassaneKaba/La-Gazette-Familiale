from flask import Flask, render_template, request, redirect, session, jsonify, flash, url_for
import sqlite3, os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timezone
from flask_mail import Mail, Message

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuration de Flask-Mail (Exemple pour Gmail)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'alassanekaba2008@gmail.com'
app.config['MAIL_PASSWORD'] = 'vecuhnaguawnofzc' # Ce n'est pas ton mdp habituel
app.config['MAIL_DEFAULT_SENDER'] = ('La Gazette Familiale', 'alassanekaba2008@gmail.com')

mail = Mail(app)

# Configuration des dossiers
UPLOAD_FOLDER = "static/uploads"
AVATAR_FOLDER = "static/avatars"  # Le chemin vers tes avatars

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["AVATAR_FOLDER"] = AVATAR_FOLDER  # CETTE LIGNE MANQUAIT PROBABLEMENT

# On s'assure que les dossiers existent sur l'ordinateur
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AVATAR_FOLDER, exist_ok=True)

# Ajoutez 'mp4', 'mov' aux extensions autorisées si vous avez une fonction de vérification
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'webm'}


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
        # 1. On récupère les posts
        posts_query = db.execute("""
            SELECT posts.*, users.avatar AS user_avatar,
                (SELECT COUNT(*) FROM reactions WHERE post_id=posts.id AND type='thumb') as thumbs,
                (SELECT COUNT(*) FROM reactions WHERE post_id=posts.id AND type='heart') as hearts
            FROM posts
            JOIN users ON posts.username = users.username
            ORDER BY posts.id DESC
        """).fetchall()
        # Convertir en liste de dictionnaires pour pouvoir ajouter les médias
        posts = [dict(row) for row in posts_query]
        # 2. Pour chaque post, on va chercher ses médias
        for post in posts:
            medias = db.execute("SELECT * FROM post_medias WHERE post_id = ?", (post['id'],)).fetchall()
            post['medias'] = medias  # On ajoute la liste des médias au post
        comments = db.execute('''
            SELECT comments.*, users.avatar AS comm_avatar
            FROM comments 
            JOIN users ON comments.username = users.username
        ''').fetchall()
    return render_template("home.html", posts=posts, comments=comments)


@app.route("/admin/users")
def admin_users():
    # Si la session ne contient pas is_admin ou si c'est False, on renvoie à l'accueil
    #if not session.get("is_admin"):
        #return redirect("/")
    db = get_db()
    pending = db.execute("SELECT * FROM users WHERE is_approved = 0").fetchall()
    return render_template("admin.html", users=pending)


@app.route("/admin/approve/<int:user_id>", methods=["POST"])
def approve_user(user_id):
    if not session.get("is_admin"):
        return redirect("/")

    db = get_db()
    # 1. On récupère les infos
    user = db.execute("SELECT email, firstname FROM users WHERE id = ?", (user_id,)).fetchone()

    if user:
        # 2. On valide en base
        db.execute("UPDATE users SET is_approved = 1 WHERE id = ?", (user_id,))
        db.commit()
        # 3. ON INSÈRE TON NOUVEAU CODE ICI
        try:
            msg = Message("Bienvenue dans la tribu ! ✅", recipients=[user['email']])
            # On utilise .html au lieu de .body pour envoyer le joli design
            msg.html = f"""
            <div style="font-family: sans-serif; color: #2d3748; max-width: 600px; border: 1px solid #e2e8f0; padding: 20px; border-radius: 15px;">
                <h1 style="color: #3182ce;">🌳 La Gazette Familiale</h1>
                <p>Bonjour <strong>{user['firstname']}</strong>,</p>
                <p>Bonne nouvelle ! Ta demande d'inscription a été <strong>acceptée</strong>.</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="http://127.0.0.1:5000/login" 
                       style="background-color: #38a169; color: white; padding: 12px 25px; text-decoration: none; border-radius: 8px; font-weight: bold;">
                       Se connecter à la maison
                    </a>
                </div>
                <p style="font-size: 0.9em; color: #718096;">À très vite,<br>L'administration de la famille</p>
            </div>
            """
            mail.send(msg)
            flash(f"L'utilisateur {user['firstname']} a été approuvé et le mail HTML a été envoyé.", "success")
        except Exception as e:
            print(f"Erreur envoi mail : {e}")
            flash("Utilisateur approuvé, mais le mail n'est pas parti.", "warning")
    return redirect("/admin/users")

@app.context_processor
def inject_pending_count():
    if session.get('is_admin'):
        db = get_db()
        count = db.execute("SELECT COUNT(*) as total FROM users WHERE is_approved = 0").fetchone()
        return {'pending_count': count['total']}
    return {'pending_count': 0}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # On récupère "email" car c'est le "name" dans ton HTML
        email_saisi = request.form.get("email")
        password_saisi = request.form.get("password")
        db = get_db()
        # On cherche par EMAIL et non par username
        user = db.execute("SELECT * FROM users WHERE email = ?", (email_saisi,)).fetchone()
        if user and check_password_hash(user["password"], password_saisi):
            # VERIFICATION DE L'APPROBATION
            if user["is_approved"] == 0:
                flash("Bienvenue ! Votre compte est en attente de validation.", "info")
                return render_template("login.html")
            # Si c'est bon, on ouvre la session
            session.clear()
            session["user"] = user["username"]  # On stocke le pseudo pour l'affichage
            session["is_admin"] = user["is_admin"]
            return redirect("/")
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
                # On force is_approved à 0 et is_admin à 0 pour les nouveaux inscrits
                db.execute("""
                    INSERT INTO users (firstname, lastname, email, username, password, avatar, is_approved, is_admin) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (firstname, lastname, email, username, hashed_password, filename, 0, 0))
                db.commit()
            # Nouveau message personnalisé pour la tribu
            flash("Bienvenue dans la tribu ! Ta demande d'accès est en attente de validation par l'administrateur.",
                  "info")
            return redirect("/login")
        except sqlite3.IntegrityError:
            flash("Ce nom d'utilisateur ou cet e-mail est déjà utilisé.", "danger")
            return redirect("/register")
    return render_template("register.html")


@app.route("/post", methods=["POST"])
@login_required
def post():
    content = request.form.get("content")
    files = request.files.getlist("images")  # On récupère une liste de fichiers
    with get_db() as db:
        # Création du post
        cursor = db.execute("INSERT INTO posts (username, content) VALUES (?, ?)",
                            (session["user"], content))
        post_id = cursor.lastrowid
        # Gestion des médias multiples
        for file in files:
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                # Déterminer si c'est une vidéo ou une image
                file_type = 'video' if filename.rsplit('.', 1)[1].lower() in ['mp4', 'mov', 'webm'] else 'image'
                db.execute("INSERT INTO post_medias (post_id, filename, file_type) VALUES (?, ?, ?)",
                           (post_id, filename, file_type))
    return redirect("/")


@app.template_filter('relative_time')
def relative_time(date_str):
    if not date_str:
        return "Date inconnue"
    # SQLite donne la date en UTC. On la lit sans fuseau (naïve)
    past = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
    # On récupère le "Maintenant" en UTC également
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    diff = now - past
    if diff.days == 0:
        if diff.seconds < 60:
            return "À l'instant"
        if diff.seconds < 3600:
            return f"Il y a {diff.seconds // 60} min"
        return f"Il y a {diff.seconds // 3600} h"
    if diff.days == 1:
        return "Hier"
    if diff.days < 7:
        return f"Il y a {diff.days} jours"
    return past.strftime('%d/%m/%Y')

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
def add_comment(post_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    content = request.form.get("content")
    if not content:
        return jsonify({"error": "Empty content"}), 400
    db = get_db()
    # On insère le commentaire (created_at se remplira tout seul via CURRENT_TIMESTAMP)
    cursor = db.execute(
        "INSERT INTO comments (post_id, username, content) VALUES (?, ?, ?)",
        (post_id, session["user"], content)
    )
    db.commit()
    # On récupère la date qui vient d'être générée par SQLite
    comment_id = cursor.lastrowid
    comment_data = db.execute(
        "SELECT created_at FROM comments WHERE id = ?", (comment_id,)
    ).fetchone()
    # On renvoie le username, le contenu ET la date au format texte
    return jsonify({
        "username": session["user"],
        "content": content,
        "created_at": comment_data["created_at"]
    })


@app.route("/user/<username>")
@login_required
def profile(username):
    with get_db() as db:
        user_info = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not user_info:
            flash("Utilisateur introuvable", "danger")
            return redirect(url_for('home'))
        posts_query = db.execute("""
            SELECT posts.*, users.avatar AS user_avatar,
                (SELECT COUNT(*) FROM reactions WHERE post_id=posts.id AND type='thumb') as thumbs,
                (SELECT COUNT(*) FROM reactions WHERE post_id=posts.id AND type='heart') as hearts
            FROM posts
            JOIN users ON posts.username = users.username
            WHERE posts.username=?
            ORDER BY posts.id DESC
        """, (username,)).fetchall()
        posts = [dict(row) for row in posts_query]
        for post in posts:
            # 1. Récupérer les médias
            medias = db.execute("SELECT filename, file_type FROM post_medias WHERE post_id = ?",
                                (post['id'],)).fetchall()
            post['medias'] = [dict(m) for m in medias]
            # 2. RÉCUPÉRER LES COMMENTAIRES (Ce qui manquait !)
            comments = db.execute("""
                SELECT comments.*, users.avatar AS user_avatar 
                FROM comments 
                JOIN users ON comments.username = users.username 
                WHERE post_id = ? 
                ORDER BY created_at ASC
            """, (post['id'],)).fetchall()
            post['comments'] = [dict(c) for c in comments]
        posts_count = len(posts)
        total_reactions = sum((p['thumbs'] or 0) + (p['hearts'] or 0) for p in posts)
    return render_template(
        "profile.html",
        posts=posts,
        user=user_info,
        posts_count=posts_count,
        likes_received=total_reactions
    )


@app.route("/upload_cover", methods=["POST"])
@login_required
def upload_cover():
    if 'cover' not in request.files:
        return jsonify({"error": "Aucun fichier"}), 400
    file = request.files['cover']
    if file.filename == '':
        return jsonify({"error": "Nom de fichier vide"}), 400
    if file:
        filename = secure_filename(f"cover_{session['user']}_{file.filename}")
        file.save(os.path.join(app.config['AVATAR_FOLDER'], filename))
        with get_db() as db:
            db.execute("UPDATE users SET cover = ? WHERE username = ?", (filename, session['user']))
        return jsonify({"success": True, "filename": filename})


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
                avatar TEXT,
                cover TEXT
                is_approved INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                username TEXT, 
                content TEXT, 
                likes INTEGER DEFAULT 0, 
                image TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
                    CREATE TABLE IF NOT EXISTS post_medias (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        post_id INTEGER,
                        filename TEXT,
                        file_type TEXT, -- 'image' ou 'video'
                        FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE
                    )
                """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER,
                username TEXT,
                content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP, -- Ajout de cette ligne
                FOREIGN KEY (post_id) REFERENCES posts (id)
            )
        """)
        db.execute(
            "CREATE TABLE IF NOT EXISTS reactions (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, post_id INTEGER, type TEXT, UNIQUE(username, post_id))")
        db.execute(
            "CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, message TEXT)")


init_db()

if __name__ == "__main__":
    app.run(debug=True)