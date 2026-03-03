import os
import urllib.parse as urlparse
import pymysql
import pandas as pd
import pickle
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer

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

    connection = get_db_connection()
    cur = connection.cursor()

    # Get all users
    cur.execute("SELECT id, email, role FROM users")
    users = cur.fetchall()

    # Total predictions count
    cur.execute("SELECT COUNT(*) FROM predictions")
    total_predictions = cur.fetchone()[0]

    # User prediction history (UTC → IST)
    cur.execute(
        """
        SELECT prediction,
               CONVERT_TZ(created_at, '+00:00', '+05:30')
        FROM predictions
        WHERE user_email=%s
        ORDER BY created_at DESC
        """,
        (session["user"],)
    )
    user_predictions = cur.fetchall()

    # Chart data (grouped by IST date)
    cur.execute(
        """
        SELECT DATE(CONVERT_TZ(created_at, '+00:00', '+05:30')),
               COUNT(*)
        FROM predictions
        WHERE user_email=%s
        GROUP BY DATE(CONVERT_TZ(created_at, '+00:00', '+05:30'))
        ORDER BY DATE(CONVERT_TZ(created_at, '+00:00', '+05:30'))
        """,
        (session["user"],)
    )
    prediction_chart_data = cur.fetchall()

    # Prevent crash if empty
    dates = []
    counts = []

    if prediction_chart_data:
        dates = [str(row[0]) for row in prediction_chart_data]
        counts = [row[1] for row in prediction_chart_data]

    cur.close()
    connection.close()

    model_exists = os.path.exists("model.pkl")

    return render_template(
        "dashboard.html",
        user=session["user"],
        role=session["role"],
        users=users,
        model_status=model_exists,
        total_predictions=total_predictions,
        user_predictions=user_predictions,
        dates=dates,
        counts=counts
    )
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

        try:
            df = pd.read_csv(file)

            expected_features = list(model.feature_names_in_)

            # Check missing required columns
            missing_cols = [col for col in expected_features if col not in df.columns]
            if missing_cols:
                return render_template(
                    "predict.html",
                    error=f"Missing required columns: {missing_cols}"
                )

            # Keep only required columns and reorder properly
            df_features = df[expected_features]

            predictions = model.predict(df_features)

            df["Prediction"] = predictions

            return render_template(
                "predict.html",
                predictions=df.to_html(classes="table table-bordered", index=False)
            )

        except Exception as e:
            return render_template("predict.html", error=f"Invalid file format: {str(e)}")

    return render_template("predict.html")
# ---------- AI TRAIN + MANUAL PREDICT ----------

@app.route("/train_model", methods=["GET", "POST"])
def train_model():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        file = request.files.get("file")

        if not file:
            return render_template("train.html", error="No file selected")

        try:
            df = pd.read_csv(file)

            # REQUIRED TARGET COLUMN
            target_column = "result"

            if target_column not in df.columns:
                return render_template(
                    "train.html",
                    error=f"Training file must contain target column '{target_column}'"
                )

            # Separate features and target
            X = df.drop(columns=[target_column])
            y = df[target_column]

            if X.shape[1] == 0:
                return render_template(
                    "train.html",
                    error="No feature columns found"
                )

            # Train model
            from sklearn.linear_model import LogisticRegression
            model = LogisticRegression()

            model.fit(X, y)

            save_model(model)

            return render_template(
                "train.html",
                success="Model trained successfully!",
                columns=list(X.columns)
            )

        except Exception as e:
            return render_template(
                "train.html",
                error=f"Invalid file format: {str(e)}"
            )

    return render_template("train.html")
# ================= RUN =================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))