import os
import urllib.parse as urlparse
import MySQLdb
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer

# ==============================
# Flask Setup
# ==============================

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secret123")

# ==============================
# Database Connection (Railway)
# ==============================

DATABASE_URL = os.environ.get("MYSQL_URL")

urlparse.uses_netloc.append("mysql")
url = urlparse.urlparse(DATABASE_URL)

conn = MySQLdb.connect(
    host=url.hostname,
    user=url.username,
    passwd=url.password,
    db=url.path[1:],
    port=url.port
)

# ==============================
# Mail Configuration (SECURE)
# ==============================

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")

mail = Mail(app)
serializer = URLSafeTimedSerializer(app.secret_key)

# ==============================
# Home Route
# ==============================

@app.route("/")
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("dashboard"))

# ==============================
# Register
# ==============================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])
        role = "user"

        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        existing_user = cur.fetchone()

        if existing_user:
            flash("Email already registered!", "danger")
            cur.close()
            return redirect(url_for("register"))

        cur.execute(
            "INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s)",
            (email.split("@")[0], email, password, role)
        )

        conn.commit()
        cur.close()

        flash("Registration successful!", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

# ==============================
# Login
# ==============================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user[3], password):
            session["user"] = user[2]
            session["role"] = user[4]
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password", "danger")

    return render_template("login.html")

# ==============================
# Forgot Password
# ==============================

@app.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"]

        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        cur.close()

        if user:
            token = serializer.dumps(email, salt="password-reset-salt")
            reset_link = url_for("reset_password", token=token, _external=True)

            msg = Message(
                subject="Password Reset",
                recipients=[email]
            )

            msg.body = f"""
Click the link below to reset your password:

{reset_link}

This link will expire in 10 minutes.
"""
            mail.send(msg)
            flash("Reset link sent to your email!", "success")
        else:
            flash("Email not found!", "danger")

    return render_template("forgot.html")

# ==============================
# Reset Password
# ==============================

@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = serializer.loads(token, salt="password-reset-salt", max_age=600)
    except:
        flash("Reset link expired or invalid.", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":
        new_password = generate_password_hash(request.form["password"])

        cur = conn.cursor()
        cur.execute("UPDATE users SET password=%s WHERE email=%s",
                    (new_password, email))
        conn.commit()
        cur.close()

        flash("Password updated successfully!", "success")
        return redirect(url_for("login"))

    return render_template("reset.html")

# ==============================
# Dashboard
# ==============================

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    if session["role"] == "admin":
        cur = conn.cursor()
        cur.execute("SELECT id, username, role FROM users")
        users = cur.fetchall()
        cur.close()

        return render_template("dashboard.html",
                               user=session["user"],
                               role=session["role"],
                               users=users)

    return render_template("dashboard.html",
                           user=session["user"],
                           role=session["role"])

# ==============================
# Logout
# ==============================

@app.route("/logout")
def logout():
    session.pop("user", None)
    session.pop("role", None)
    return redirect(url_for("login"))

# ==============================
# Run App (Railway Ready)
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))