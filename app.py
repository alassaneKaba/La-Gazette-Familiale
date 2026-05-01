from flask import Flask, render_template, request, redirect, session, jsonify, flash, url_for
import sqlite3, os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timezone
from flask_mail import Mail, Message
import time, random
from PIL import Image

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuration de Flask-Mail (Exemple pour Gmail)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'alassanekaba2008@gmail.com'
app.config['MAIL_PASSWORD'] = 'vecuhnaguawnofzc'  # Ce n'est pas ton mdp habituel
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


def process_image(file_path):
    """Compresse et redimensionne l'image pour optimiser le stockage et l'affichage."""
    with Image.open(file_path) as img:
        # Convertir en RGB (pour gérer les formats comme RGBA/PNG avec transparence vers JPEG si besoin)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Redimensionnement maximal (ex: 1200px de large) tout en gardant les proportions
        max_size = 1200
        if img.width > max_size:
            ratio = max_size / float(img.width)
            new_height = int(float(img.height) * float(ratio))
            img = img.resize((max_size, new_height), Image.Resampling.LANCZOS)
        # Sauvegarde avec compression (qualité 85 est le standard web)
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
    with get_db() as db:
        user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    return jsonify({"exists": True if user else False})


# --- NOUVELLES ROUTES AJAX POUR LE PROFIL ---
@app.route('/update_profile_ajax', methods=['POST'])
# On enlève @login_required ici pour gérer l'erreur 401 proprement en JSON
def update_profile_ajax():
    # Vérification manuelle de la session
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Session expirée, veuillez vous reconnecter.'}), 401

    firstname = request.form.get('firstname')
    lastname = request.form.get('lastname')
    bio = request.form.get('bio')
    avatar_file = request.files.get('avatar')
    username = session['user']
    new_avatar_name = None

    with get_db() as db:
        if avatar_file and avatar_file.filename != '':
            old_user = db.execute("SELECT avatar FROM users WHERE username = ?", (username,)).fetchone()
            if old_user and old_user['avatar'] and old_user['avatar'] != 'default.png':
                try:
                    os.remove(os.path.join(app.config['AVATAR_FOLDER'], old_user['avatar']))
                except:
                    pass

            new_avatar_name = f"{username}_avatar_{int(time.time())}.png"
            avatar_file.save(os.path.join(app.config['AVATAR_FOLDER'], new_avatar_name))
            db.execute("UPDATE users SET avatar=? WHERE username=?", (new_avatar_name, username))

        db.execute("UPDATE users SET firstname=?, lastname=?, bio=? WHERE username=?",
                   (firstname, lastname, bio, username))
        db.commit()

    return jsonify({'success': True, 'new_avatar': new_avatar_name})


@app.route('/delete_profile_ajax', methods=['POST'])
@login_required
def delete_profile_ajax():
    username = session['user']
    with get_db() as db:
        # 1. Récupérer l'avatar et la cover
        user_data = db.execute("SELECT avatar, cover FROM users WHERE username = ?", (username,)).fetchone()
        # 2. Récupérer tous les fichiers des publications (photos/vidéos)
        # On cherche tous les médias liés aux posts de cet utilisateur
        medias = db.execute("""
            SELECT m.filename FROM post_medias m 
            JOIN posts p ON m.post_id = p.id 
            WHERE p.username = ?
        """, (username,)).fetchall()
        # 3. SUPPRESSION PHYSIQUE DES FICHIERS
        # Suppression avatar/cover
        if user_data:
            for key in ['avatar', 'cover']:
                if user_data[key] and user_data[key] not in ['default.png', 'default_cover.png']:
                    try:
                        os.remove(os.path.join(app.config['AVATAR_FOLDER'], user_data[key]))
                    except:
                        pass
        # Suppression des médias de posts
        for m in medias:
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], m['filename']))
            except:
                pass
        # 4. SUPPRESSION EN BASE DE DONNÉES
        # Si tes clés étrangères sont en ON DELETE CASCADE,
        # supprimer l'user supprimera ses posts et commentaires automatiquement.
        db.execute("DELETE FROM users WHERE username = ?", (username,))
        db.commit()
    session.clear()  # Déconnexion immédiate
    return jsonify({'success': True})


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
    # if not session.get("is_admin"):
    # return redirect("/")
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
            flash(f"L'utilisateur {user['firstname']} a été approuvé et un mail lui a été envoyé.", "success")
        except Exception as e:
            print(f"Erreur envoi mail : {e}")
            flash("Utilisateur approuvé, mais le mail n'est pas parti.", "warning")
    return redirect("/admin/users")


@app.route("/admin/reject/<int:user_id>", methods=["POST"])
def reject_user(user_id):
    # La vérification admin est active ici, assure-toi que ton compte admin a bien is_admin=1 en base
    if not session.get("is_admin"):
        return redirect("/")
    with get_db() as db:
        # 1. On récupère les infos AVANT de supprimer
        user = db.execute("SELECT email, firstname, avatar FROM users WHERE id = ?", (user_id,)).fetchone()
        if user:
            # 2. Suppression de l'avatar physique
            if user['avatar'] and user['avatar'] != 'default.png':
                try:
                    path = os.path.join(app.config["AVATAR_FOLDER"], user['avatar'])
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as e:
                    print(f"Erreur fichier : {e}")
            # 3. SUPPRESSION DÉFINITIVE ET COMMIT IMMÉDIAT
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            db.commit()
            # 4. Envoi du mail (placé après le commit pour être sûr que l'user est supprimé)
            try:
                msg = Message("Demande d'inscription - La Gazette Familiale ❌", recipients=[user['email']])
                msg.html = f"""
                <div style="font-family: sans-serif; color: #2d3748; max-width: 600px; border: 1px solid #e2e8f0; padding: 20px; border-radius: 15px;">
                    <h1 style="color: #e53e3e;">🌳 La Gazette Familiale</h1>
                    <p>Bonjour <strong>{user['firstname']}</strong>,</p>
                    <p>Nous avons bien reçu ta demande d'inscription.</p>
                    <p>Malheureusement, l'administrateur n'a pas pu valider ton entrée pour le moment.</p>
                    <hr style="border: 0; border-top: 1px solid #edf2f7; margin: 20px 0;">
                    <p style="font-size: 0.9em; color: #718096;">À bientôt,<br>L'administration de la famille</p>
                </div>
                """
                mail.send(msg)
                flash(f"L'utilisateur {user['firstname']} a été refusé.", "info")
            except Exception as e:
                print(f"Erreur mail : {e}")
                flash("Utilisateur supprimé, mais le mail n'est pas parti.", "warning")
    return redirect("/admin/users")


@app.context_processor
def inject_global_stats():
    stats = {'total_users': 0, 'total_posts': 0}
    if session.get('user'):
        db = get_db()
        # Nombre total de membres approuvés
        u_count = db.execute("SELECT COUNT(*) FROM users WHERE is_approved = 1").fetchone()[0]
        # Nombre total de messages partagés
        p_count = db.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        stats = {'total_users': u_count, 'total_posts': p_count}
    return stats


@app.context_processor
def inject_pending_count():
    if session.get('is_admin'):
        db = get_db()
        count = db.execute("SELECT COUNT(*) as total FROM users WHERE is_approved = 0").fetchone()
        return {'pending_count': count['total']}
    return {'pending_count': 0}


@app.context_processor
def inject_notifications_count():
    if session.get('user'):
        db = get_db()
        count = db.execute("SELECT COUNT(*) FROM notifications WHERE username = ? AND is_read = 0",
                           (session['user'],)).fetchone()[0]
        return {'unread_count': count}
    return {'unread_count': 0}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email_saisi = request.form.get("email")
        password_saisi = request.form.get("password")
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email_saisi,)).fetchone()
            if user and check_password_hash(user["password"], password_saisi):
                # VÉRIFICATION DE L'APPROBATION
                if user["is_approved"] == 0:
                    flash("Votre compte est en attente de validation par l'administrateur.", "info")
                    return render_template("login.html")
                # CONNEXION RÉUSSIE
                session.clear()
                session["user"] = user["username"]
                session["user_id"] = user["id"]
                session["is_admin"] = user["is_admin"]
                # --- LA CORRECTION EST ICI ---
                # On stocke l'avatar en session pour le JavaScript (commentaires, etc.)
                session["user_avatar"] = user["avatar"] if user["avatar"] else "default.png"
                return redirect(url_for("home"))  # ou return redirect("/")
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
            # 1. ENREGISTREMENT EN BASE DE DONNÉES
            with get_db() as db:
                db.execute("""
                    INSERT INTO users (firstname, lastname, email, username, password, avatar, is_approved, is_admin) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (firstname, lastname, email, username, hashed_password, filename, 0, 0))
                db.commit()
            # 2. ENVOI DU MAIL À L'ADMIN
            try:
                base_url = request.host_url
                msg = Message(
                    subject="Nouvelle demande d'adhésion 🌳",
                    recipients=["alassanekaba2008@gmail.com"]
                )
                msg.html = f"""
                <div style="font-family: 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e2e8f0; border-radius: 15px; overflow: hidden;">
                    <div style="background-color: #3182ce; padding: 20px; text-align: center; color: white;">
                        <h1 style="margin: 0; font-size: 24px;">🌳 La Gazette Familiale</h1>
                    </div>
                    <div style="padding: 30px; background-color: white;">
                        <h2 style="color: #2d3748; margin-top: 0;">Nouvelle inscription !</h2>
                        <p style="color: #4a5568; line-height: 1.6;">Bonjour Admin, un nouveau membre attend ta validation pour rejoindre la tribu.</p>
                        <div style="background-color: #f7fafc; padding: 20px; border-radius: 10px; margin: 20px 0; border: 1px solid #edf2f7;">
                            <p style="margin: 5px 0;"><strong>👤 Nom :</strong> {firstname} {lastname}</p>
                            <p style="margin: 5px 0;"><strong>🆔 Pseudo :</strong> @{username}</p>
                            <p style="margin: 5px 0;"><strong>📧 Email :</strong> {email}</p>
                        </div>
                        <div style="text-align: center; margin-top: 30px;">
                            <a href="{base_url}admin/users" 
                               style="background-color: #3182ce; color: white; padding: 12px 25px; text-decoration: none; font-weight: bold; border-radius: 8px; display: inline-block;">
                               Accéder aux demandes
                            </a>
                        </div>
                    </div>
                </div>
                """
                msg.body = f"Nouvelle inscription : {firstname} {lastname}. Validez ici : {base_url}admin/users"
                mail.send(msg)
            except Exception as e:
                print(f"Erreur d'envoi mail : {e}")
            # 3. RÉPONSE À L'UTILISATEUR (Bien aligné en dehors du try/except mail)
            flash("Bienvenue dans la tribu ! Ta demande d'accès est en attente de validation.", "info")
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
                filename = secure_filename(f"{int(time.time())}_{file.filename}")
                file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(file_path)
                # DÉTERMINER LE TYPE
                ext = filename.rsplit('.', 1)[1].lower()
                if ext in ['jpg', 'jpeg', 'png', 'gif']:
                    process_image(file_path)  # <--- ON COMPRESSE ICI
                    file_type = 'image'
                else:
                    file_type = 'video'
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
                texte_react = "a aimé votre publication" if reaction_type == 'heart' else "a réagi à votre publication"
                db.execute("""
                                INSERT INTO notifications (username, sender, message, post_id) 
                                VALUES (?, ?, ?, ?)
                            """, (owner['username'], username, texte_react, post_id))
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
    parent_id = request.form.get("parent_id")  # On récupère l'ID du commentaire parent s'il existe
    if not content:
        return jsonify({"error": "Empty content"}), 400
    with get_db() as db:
        # On insère le commentaire avec son parent_id (peut être None)
        cursor = db.execute(
            "INSERT INTO comments (post_id, username, content, parent_id) VALUES (?, ?, ?, ?)",
            (post_id, session["user"], content, parent_id)
        )
        comment_id = cursor.lastrowid
        # Notification au propriétaire du post
        owner = db.execute("SELECT username FROM posts WHERE id=?", (post_id,)).fetchone()
        if owner and owner['username'] != session['user']:
            db.execute("""
                INSERT INTO notifications (username, sender, message, post_id, comment_id) 
                VALUES (?, ?, ?, ?, ?)
            """, (owner['username'], session['user'], "a commenté votre publication", post_id, comment_id))
        # SI c'est une réponse, on peut aussi notifier l'auteur du commentaire parent !
        if parent_id:
            parent_author = db.execute("SELECT username FROM comments WHERE id=?", (parent_id,)).fetchone()
            if parent_author and parent_author['username'] != session['user']:
                db.execute("""
                    INSERT INTO notifications (username, sender, message, post_id, comment_id) 
                    VALUES (?, ?, ?, ?, ?)
                """, (parent_author['username'], session['user'], "a répondu à votre commentaire", post_id, comment_id))
        db.commit()
        comment_data = db.execute("SELECT created_at FROM comments WHERE id = ?", (comment_id,)).fetchone()
    return jsonify({
        "username": session["user"],
        "content": content,
        "created_at": comment_data["created_at"],
        "comment_id": comment_id,
        "parent_id": parent_id
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


@app.route("/post/<int:post_id>")
@login_required
def view_post(post_id):
    with get_db() as db:
        # 1. On récupère le post spécifique avec les infos de l'auteur
        post_query = db.execute("""
            SELECT posts.*, users.avatar AS user_avatar,
                (SELECT COUNT(*) FROM reactions WHERE post_id=posts.id AND type='thumb') as thumbs,
                (SELECT COUNT(*) FROM reactions WHERE post_id=posts.id AND type='heart') as hearts
            FROM posts
            JOIN users ON posts.username = users.username
            WHERE posts.id = ?
        """, (post_id,)).fetchone()
        if not post_query:
            flash("Ce post n'existe plus.", "warning")
            return redirect(url_for('home'))
        # 2. On transforme en dictionnaire pour ajouter les médias
        post = dict(post_query)
        medias = db.execute("SELECT * FROM post_medias WHERE post_id = ?", (post_id,)).fetchall()
        post['medias'] = medias
        # 3. On récupère les commentaires liés à ce post
        comments = db.execute("""
            SELECT comments.*, users.avatar AS comm_avatar
            FROM comments 
            JOIN users ON comments.username = users.username
            WHERE post_id = ?
            ORDER BY created_at ASC
        """, (post_id,)).fetchall()
    # On réutilise le template home.html, mais en ne passant QUE ce post dans une liste
    return render_template("home.html", posts=[post], comments=comments)


@app.route("/notifications")
@login_required
def notifications():
    with get_db() as db:
        # On récupère toutes les colonnes pour les afficher dans notifications.html
        notifs = db.execute("""
                    SELECT id, sender, message, post_id, comment_id, is_read, created_at 
                    FROM notifications 
                    WHERE username = ? 
                    ORDER BY created_at DESC
                """, (session['user'],)).fetchall()
        # 2. Dernière activité (Les 3 derniers posts du site)
        recent_activity = db.execute("""
                    SELECT username, content, created_at 
                    FROM posts ORDER BY id DESC LIMIT 3
                """).fetchall()
        citations = [
            "La famille, c'est là où la vie commence et où l'amour ne finit jamais.",
            "Chaque souvenir partagé ici est un trésor pour demain.",
            "Une gazette remplie de rires est une gazette réussie !",
            "Petit à petit, la tribu grandit et l'histoire s'écrit.",
            "Le bonheur est fait de petites choses partagées."
        ]
        pensee_du_jour = random.choice(citations)
        # Optionnel : Marquer comme lu quand on visite la page
        db.execute("UPDATE notifications SET is_read = 1 WHERE username = ?", (session["user"],))
        db.commit()
    return render_template("notifications.html", notifs=notifs, recent_activity=recent_activity,
                           pensee_du_jour=pensee_du_jour)


@app.route("/notifications/mark-all-read")
@login_required
def mark_all_read():
    with get_db() as db:
        db.execute("UPDATE notifications SET is_read = 1 WHERE username = ?", (session["user"],))
        db.commit()
    return redirect(url_for('notifications'))


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
                cover TEXT,
                bio TEXT,
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
                FOREIGN KEY (post_id) REFERENCES posts (id),
                FOREIGN KEY (parent_id) REFERENCES comments (id) ON DELETE CASCADE
            )
        """)
        db.execute(
            "CREATE TABLE IF NOT EXISTS reactions (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, post_id INTEGER, type TEXT, UNIQUE(username, post_id))")
        db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,      -- Celui qui reçoit
                sender TEXT,        -- Celui qui a agi
                message TEXT,
                post_id INTEGER,    -- Pour cliquer et aller sur le post
                comment_id INTEGER, -- envoie vers un commentaire en particulier
                is_read INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)


init_db()

if __name__ == "__main__":
    app.run(debug=True)
