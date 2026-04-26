import sqlite3

def make_me_admin(username):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    # On te valide et on te passe admin
    cursor.execute("UPDATE users SET is_approved = 1, is_admin = 1 WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    print(f"Succès ! L'utilisateur {username} est maintenant Admin et Approuvé.")

if __name__ == "__main__":
    mon_pseudo = "alassane_kaba" # Remplace par ton vrai pseudo
    make_me_admin(mon_pseudo)