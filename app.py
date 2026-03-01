import os
import urllib.parse as urlparse
import pymysql
import pandas as pd
import pickle
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from twilio.rest import Client

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secret123")

# ================= DATABASE =================

def get_db_connection():
    DATABASE_URL = os.environ.get("MYSQL_URL")

    urlparse.uses_netloc.append("mysql")
    url = urlparse.urlparse(DATABASE_URL)

    return pymysql.connect(
        host=url.hostname,
        user=url.username,
        password=url.password,
        database=url.path[1:],
        port=url.port,
        ssl={"ssl": {}}
    )

serializer = URLSafeTimedSerializer(app.secret_key)

# ================= TWILIO =================

def send_sms(to_number):
    try:
        client = Client(
            os.environ.get("TWILIO_ACCOUNT_SID"),
            os.environ.get("TWILIO_AUTH_TOKEN")
        )

        client.messages.create(
            body="You have successfully logged into Enterprise AI.",
            from_=os.environ.get("TWILIO_PHONE_NUMBER"),
            to=to_number
        )

    except Exception as e:
        print("Twilio Error:", e)

# ================= MODEL LOAD =================

def load_model():
    if os.path.exists("model.pkl"):
        return pickle.load(open("model.pkl", "rb"))
    return None

# ================= ROUTES =================

@app.route("/")
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("dashboard"))

# ---------- REGISTER ----------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])
        role = "user"

        connection = get_db_connection()
        cur = connection.cursor()

        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            flash("Email already registered!", "danger")
            cur.close()
            connection.close()
            return redirect(url_for("register"))

        cur.execute(
            "INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s)",
            (email.split("@")[0], email, password, role)
        )
        connection.commit()
        cur.close()
        connection.close()

        flash("Registration successful!", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

# ---------- LOGIN ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        connection = get_db_connection()
        cur = connection.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        cur.close()
        connection.close()

        if user and check_password_hash(user[3], password):
            session["user"] = user[2]
            session["role"] = user[4]

            # 🔥 SEND SMS AFTER LOGIN
            send_sms("+917013474425")  # change to your verified number

            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password", "danger")

    return render_template("login.html")

# ---------- FORGOT PASSWORD ----------

@app.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"]

        connection = get_db_connection()
        cur = connection.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        cur.close()
        connection.close()

        if not user:
            flash("Email not found!", "danger")
            return redirect(url_for("forgot_password"))

        token = serializer.dumps(email, salt="reset-salt")
        reset_link = url_for("reset_password", token=token, _external=True)

        return f"""
        <h3>Copy this link and open it:</h3>
        <a href="{reset_link}">{reset_link}</a>
        """

    return render_template("forgot.html")

# ---------- RESET PASSWORD ----------

@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = serializer.loads(token, salt="reset-salt", max_age=600)
    except:
        flash("Reset link expired or invalid", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":
        new_password = generate_password_hash(request.form["password"])

        connection = get_db_connection()
        cur = connection.cursor()
        cur.execute("UPDATE users SET password=%s WHERE email=%s",
                    (new_password, email))
        connection.commit()
        cur.close()
        connection.close()

        flash("Password updated successfully!", "success")
        return redirect(url_for("login"))

    return render_template("reset.html")

# ---------- DASHBOARD ----------

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    return render_template("dashboard.html",
                           user=session["user"],
                           role=session["role"])

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- AI CSV PREDICTION ----------

@app.route("/ai_prediction", methods=["GET", "POST"])
def ai_prediction():
    if "user" not in session:
        return redirect(url_for("login"))

    model = load_model()

    if request.method == "POST":
        file = request.files.get("file")

        if not file:
            return render_template("predict.html", error="No file selected")

        if not model:
            return render_template("predict.html", error="Train model first")

        df = pd.read_csv(file)
        predictions = model.predict(df)
        df["Prediction"] = predictions

        return render_template("predict.html",
                               predictions=df.to_html(classes="table table-bordered", index=False))

    return render_template("predict.html")

# ---------- AI TRAIN + MANUAL PREDICT ----------

@app.route("/train_model", methods=["GET", "POST"])
def train_model():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        # TRAIN
        if "file" in request.files and request.files["file"].filename != "":
            file = request.files["file"]
            df = pd.read_csv(file)

            X = df[["marks", "hours"]]
            y = df["result"]

            from sklearn.model_selection import train_test_split
            from sklearn.linear_model import LogisticRegression

            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42
            )

            model = LogisticRegression()
            model.fit(X_train, y_train)
            accuracy = model.score(X_test, y_test)

            pickle.dump(model, open("model.pkl", "wb"))

            return render_template("ai.html", accuracy=accuracy)

        # MANUAL PREDICT
        if "marks" in request.form and "hours" in request.form:
            model = load_model()
            if not model:
                return render_template("ai.html", error="Train model first")

            marks = float(request.form["marks"])
            hours = float(request.form["hours"])

            prediction = model.predict([[marks, hours]])[0]
            result = "Pass ✅" if prediction == 1 else "Fail ❌"

            return render_template("ai.html", prediction=result)

    return render_template("ai.html")

# ================= RUN =================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))