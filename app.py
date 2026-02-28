import os
import urllib.parse as urlparse
import pymysql
import pandas as pd
import pickle
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secret123")

# ================= DATABASE =================

DATABASE_URL = os.environ.get("MYSQL_URL")

urlparse.uses_netloc.append("mysql")
url = urlparse.urlparse(DATABASE_URL)

conn = pymysql.connect(
    host=url.hostname,
    user=url.username,
    password=url.password,
    database=url.path[1:],
    port=url.port,
    ssl={"ssl": {}}
)

# ================= MAIL =================

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")

mail = Mail(app)
serializer = URLSafeTimedSerializer(app.secret_key)

# ================= MODEL =================

model = pickle.load(open("model.pkl", "rb"))

# ================= ROUTES =================

@app.route("/")
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("dashboard"))

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

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    return render_template("dashboard.html",
                           user=session["user"],
                           role=session["role"])

@app.route("/logout")
def logout():
    session.pop("user", None)
    session.pop("role", None)
    return redirect(url_for("login"))

# ================= AI PREDICTION =================

@app.route("/ai_prediction", methods=["GET", "POST"])
def ai_prediction():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        file = request.files.get("file")

        if not file:
            return render_template("predict.html", error="No file selected")

        try:
            df = pd.read_csv(file)
            predictions = model.predict(df)
            df["Prediction"] = predictions
            result_table = df.to_html(classes="table table-bordered", index=False)

            return render_template("predict.html", predictions=result_table)

        except Exception as e:
            return render_template("predict.html", error=str(e))

    return render_template("predict.html")


@app.route("/train_model", methods=["GET", "POST"])
def train_model():
    if "user" not in session:
        return redirect(url_for("login"))

    import pandas as pd
    import pickle
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split

    if request.method == "POST":

        # TRAIN MODEL
        if "file" in request.files and request.files["file"].filename != "":
            file = request.files["file"]

            df = pd.read_csv(file)

            X = df[["marks", "hours"]]
            y = df["result"]

            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42
            )

            model = LogisticRegression()
            model.fit(X_train, y_train)

            accuracy = model.score(X_test, y_test)

            pickle.dump(model, open("model.pkl", "wb"))

            return render_template("ai.html", accuracy=accuracy)

        # PREDICT
        if "marks" in request.form and "hours" in request.form:

            marks = float(request.form["marks"])
            hours = float(request.form["hours"])

            model = pickle.load(open("model.pkl", "rb"))

            prediction = model.predict([[marks, hours]])[0]

            result = "Pass ✅" if prediction == 1 else "Fail ❌"

            return render_template("ai.html", prediction=result)

    return render_template("ai.html")

# ================= RUN =================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))