import pandas as pd
import pickle

from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from flask import Flask, render_template, request, redirect, url_for, session,flash
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer

app = Flask(__name__)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'aggu0217@gmail.com'
app.config['MAIL_PASSWORD'] = 'wihlqfuspqhjgsnr'
app.config['MAIL_DEFAULT_SENDER'] = 'aggu0217@gmail.com'

mail = Mail(app)
app.secret_key = "secret123"
serializer = URLSafeTimedSerializer(app.secret_key)

# ==============================
# MySQL Configuration
# ==============================

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'abdul123'  # <-- CHANGE THIS
app.config['MYSQL_DB'] = 'enterprise_ai'

mysql = MySQL(app)

# ==============================
# Home Route (Protected)
# ==============================

@app.route("/")
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("dashboard"))

# ==============================
# register Route
# ==============================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])
        role = "user"

        cur = mysql.connection.cursor()

        # Check if email already exists
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

        mysql.connection.commit()
        cur.close()

        flash("Registration successful!", "success")
        return redirect(url_for("login"))

    return render_template("register.html")
# ==============================
# Login Route
# ==============================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user[2], password):

            session["user"] = user[4]
            session["role"] = user[3]

            # Send login notification email
            msg = Message(
                subject="Login Alert - Enterprise AI",
                recipients=[user[4]]
            )

            msg.body = f"""
Hello,

You have successfully logged into Enterprise AI Platform.

If this was not you, please reset your password immediately.

Regards,
Enterprise AI Team
"""

            mail.send(msg)

            return redirect(url_for("dashboard"))

        else:
            flash("Invalid email or password", "danger")

    return render_template("login.html")

# ==============================
# forget Route
# ==============================

@app.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"]

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        cur.close()

        if user:
            token = serializer.dumps(email, salt="password-reset-salt")
            reset_link = url_for("reset_password", token=token, _external=True)

            msg = Message(
                subject="Password Reset - Enterprise AI",
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
# reset Route
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

        cur = mysql.connection.cursor()
        cur.execute("UPDATE users SET password=%s WHERE email=%s",
                    (new_password, email))
        mysql.connection.commit()
        cur.close()

        flash("Password updated successfully!", "success")
        return redirect(url_for("login"))

    return render_template("reset.html")
# ==============================
# dashboard Route
# ==============================

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    if session["role"] == "admin":
        cur = mysql.connection.cursor()
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
# ai Route
# ==============================
@app.route("/ai", methods=["GET", "POST"])
def ai_module():
    if "user" not in session:
        return redirect(url_for("login"))

    accuracy = None
    prediction = None

    if request.method == "POST":

        # TRAIN MODEL
        if "file" in request.files and request.files["file"].filename != "":
            file = request.files["file"]
            data = pd.read_csv(file)

            X = data.iloc[:, :-1]
            y = data.iloc[:, -1]

            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42
            )

            model = LogisticRegression()
            model.fit(X_train, y_train)

            accuracy = model.score(X_test, y_test)

            # Save trained model
            with open("model.pkl", "wb") as f:
                pickle.dump(model, f)

        # PREDICT USING SAVED MODEL
        elif "hours" in request.form:

            hours = float(request.form["hours"])
            marks = float(request.form["marks"])

            # Load saved model
            with open("model.pkl", "rb") as f:
                model = pickle.load(f)

            input_data = [[hours, marks]]
            result = model.predict(input_data)[0]

            prediction = "PASS" if result == 1 else "FAIL"

    return render_template("ai.html", accuracy=accuracy, prediction=prediction)

# ==============================
# predict Route
# ==============================

@app.route("/predict", methods=["GET", "POST"])
def predict():
    if "user" not in session:
        return redirect(url_for("login"))

    predictions = None
    error = None

    if request.method == "POST":
        try:
            file = request.files["file"]
            data = pd.read_csv(file)

            with open("model.pkl", "rb") as f:
                model = pickle.load(f)

            results = model.predict(data)
            data["Prediction"] = results

            predictions = data.to_html(classes="table table-bordered")

        except FileNotFoundError:
            error = "Train model first!"
        except Exception:
            error = "Invalid file format."

    return render_template("predict.html",
                           predictions=predictions,
                           error=error)


# ==============================
# Logout Route
# ==============================

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# ==============================

if __name__ == "__main__":
    app.run(debug=True)
