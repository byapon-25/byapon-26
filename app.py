from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from functools import wraps
from datetime import date

app = Flask(__name__)
app.secret_key = "BYAPON_CMS_SECRET_2026"
DB = "byapon.db"

def db():
    import os
    from pathlib import Path
    import psycopg
    from psycopg.rows import dict_row

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip()
                    os.environ["DATABASE_URL"] = url
                    break

    if not url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("DATABASE_URL is missing or invalid")

    class PGConnection:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, params=()):
            sql = sql.replace("?", "%s")
            return self._conn.execute(sql, params)

        def commit(self):
            return self._conn.commit()

        def rollback(self):
            return self._conn.rollback()

        def close(self):
            return self._conn.close()

    return PGConnection(
        psycopg.connect(url, row_factory=dict_row)
    )

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper

def init_db():
    con = db()

    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        student_id INTEGER,
        teacher_id INTEGER
    );

    CREATE TABLE IF NOT EXISTS students(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        phone TEXT,
        guardian TEXT,
        class_name TEXT,
        batch TEXT,
        monthly_fee REAL DEFAULT 0,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS teachers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        subject TEXT,
        salary REAL DEFAULT 0,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS attendance(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        attendance_date TEXT NOT NULL,
        status TEXT NOT NULL,
        UNIQUE(student_id, attendance_date)
    );

    CREATE TABLE IF NOT EXISTS exams(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        subject TEXT,
        exam_date TEXT,
        full_marks REAL DEFAULT 100,
        pass_marks REAL DEFAULT 33
    );

    CREATE TABLE IF NOT EXISTS marks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        marks REAL DEFAULT 0,
        UNIQUE(exam_id, student_id)
    );

    CREATE TABLE IF NOT EXISTS fees(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        fee_month TEXT NOT NULL,
        amount REAL NOT NULL,
        paid_amount REAL DEFAULT 0,
        payment_date TEXT,
        status TEXT,
        note TEXT
    );

    CREATE TABLE IF NOT EXISTS transactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tx_date TEXT NOT NULL,
        tx_type TEXT NOT NULL,
        category TEXT,
        amount REAL NOT NULL,
        note TEXT
    );

    CREATE TABLE IF NOT EXISTS routines(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day_name TEXT NOT NULL,
        batch TEXT,
        subject TEXT,
        teacher TEXT,
        start_time TEXT,
        end_time TEXT
    );

    CREATE TABLE IF NOT EXISTS assignments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id INTEGER NOT NULL,
        batch TEXT NOT NULL,
        subject TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS notices(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    admin = con.execute(
        "SELECT id FROM users WHERE username='admin'"
    ).fetchone()

    if not admin:
        con.execute(
            "INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
            ("admin", generate_password_hash("admin123"), "admin")
        )

    con.commit()
    con.close()

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        con = db()
        user = con.execute(
            "SELECT * FROM users WHERE username=?",
            (username,)
        ).fetchone()
        con.close()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["student_id"] = user["student_id"]
            session["teacher_id"] = user["teacher_id"]

            if user["role"] == "student":
                return redirect(url_for("student_dashboard"))

            if user["role"] == "teacher":
                return redirect(url_for("teacher_dashboard"))

            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/dashboard")
@login_required
@admin_required
def dashboard():
    con = db()

    students = con.execute(
        "SELECT COUNT(*) n FROM students WHERE active=1"
    ).fetchone()["n"]

    teachers = con.execute(
        "SELECT COUNT(*) n FROM teachers WHERE active=1"
    ).fetchone()["n"]

    exams = con.execute(
        "SELECT COUNT(*) n FROM exams"
    ).fetchone()["n"]

    paid = con.execute(
        "SELECT COALESCE(SUM(paid_amount),0) n FROM fees"
    ).fetchone()["n"]

    income = con.execute(
        "SELECT COALESCE(SUM(amount),0) n FROM transactions WHERE tx_type='Income'"
    ).fetchone()["n"]

    expense = con.execute(
        "SELECT COALESCE(SUM(amount),0) n FROM transactions WHERE tx_type='Expense'"
    ).fetchone()["n"]

    pending = con.execute(
        "SELECT COALESCE(SUM(amount-paid_amount),0) n FROM fees"
    ).fetchone()["n"]

    con.close()

    return render_template(
        "dashboard.html",
        students=students,
        teachers=teachers,
        exams=exams,
        paid=paid,
        income=income,
        expense=expense,
        pending=pending
    )

# ---------------- STUDENTS ----------------

@app.route("/students", methods=["GET", "POST"])
@login_required
@admin_required
def students():
    con = db()

    if request.method == "POST":
        student_id = request.form["student_id"].strip()
        name = request.form["name"].strip()
        password = request.form.get("password", "").strip() or student_id

        try:
            cur = con.execute("""
                INSERT INTO students
                (student_id,name,phone,guardian,class_name,batch,monthly_fee)
                VALUES(?,?,?,?,?,?,?)
            """, (
                student_id,
                name,
                request.form.get("phone"),
                request.form.get("guardian"),
                request.form.get("class_name"),
                request.form.get("batch"),
                float(request.form.get("monthly_fee") or 0)
            ))

            sid = cur.lastrowid

            con.execute("""
                INSERT INTO users
                (username,password_hash,role,student_id)
                VALUES(?,?,?,?)
            """, (
                student_id,
                generate_password_hash(password),
                "student",
                sid
            ))

            con.commit()
            flash("Student added successfully.", "success")

        except sqlite3.IntegrityError:
            con.rollback()
            flash("Student ID already exists.", "danger")

        return redirect(url_for("students"))

    q = request.args.get("q", "").strip()

    if q:
        rows = con.execute("""
            SELECT * FROM students
            WHERE student_id LIKE ?
               OR name LIKE ?
               OR phone LIKE ?
               OR batch LIKE ?
               OR class_name LIKE ?
            ORDER BY id DESC
        """, tuple("%" + q + "%" for _ in range(5))).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM students ORDER BY id DESC"
        ).fetchall()

    con.close()
    return render_template("students.html", students=rows, q=q)

@app.route("/students/<int:sid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_student(sid):
    con = db()

    student = con.execute(
        "SELECT * FROM students WHERE id=?",
        (sid,)
    ).fetchone()

    if not student:
        con.close()
        return "Student not found", 404

    if request.method == "POST":
        con.execute("""
            UPDATE students
            SET student_id=?, name=?, phone=?, guardian=?,
                class_name=?, batch=?, monthly_fee=?
            WHERE id=?
        """, (
            request.form["student_id"],
            request.form["name"],
            request.form.get("phone"),
            request.form.get("guardian"),
            request.form.get("class_name"),
            request.form.get("batch"),
            float(request.form.get("monthly_fee") or 0),
            sid
        ))

        con.execute(
            "UPDATE users SET username=? WHERE student_id=?",
            (request.form["student_id"], sid)
        )

        new_password = request.form.get("password", "").strip()

        if new_password:
            con.execute(
                "UPDATE users SET password_hash=? WHERE student_id=?",
                (generate_password_hash(new_password), sid)
            )

        con.commit()
        con.close()

        flash("Student updated.", "success")
        return redirect(url_for("students"))

    con.close()
    return render_template("student_edit.html", student=student)

@app.route("/students/<int:sid>/delete", methods=["POST"])
@login_required
@admin_required
def delete_student(sid):
    con = db()
    con.execute("DELETE FROM users WHERE student_id=?", (sid,))
    con.execute("DELETE FROM attendance WHERE student_id=?", (sid,))
    con.execute("DELETE FROM marks WHERE student_id=?", (sid,))
    con.execute("DELETE FROM fees WHERE student_id=?", (sid,))
    con.execute("DELETE FROM students WHERE id=?", (sid,))
    con.commit()
    con.close()

    flash("Student deleted.", "success")
    return redirect(url_for("students"))

# ---------------- TEACHERS ----------------

@app.route("/teachers", methods=["GET", "POST"])
@login_required
@admin_required
def teachers():
    con = db()

    if request.method == "POST":
        name = request.form["name"].strip()
        password = request.form.get("password", "").strip() or "teacher123"

        try:
            cur = con.execute("""
                INSERT INTO teachers(name,phone,subject,salary)
                VALUES(?,?,?,?)
            """, (
                name,
                request.form.get("phone"),
                request.form.get("subject"),
                float(request.form.get("salary") or 0)
            ))

            tid = cur.lastrowid

            username = request.form.get("username", "").strip() or (
                "teacher" + str(tid)
            )

            con.execute("""
                INSERT INTO users
                (username,password_hash,role,teacher_id)
                VALUES(?,?,?,?)
            """, (
                username,
                generate_password_hash(password),
                "teacher",
                tid
            ))

            con.commit()
            flash("Teacher added successfully.", "success")

        except sqlite3.IntegrityError:
            con.rollback()
            flash("Teacher username already exists.", "danger")

        return redirect(url_for("teachers"))

    q = request.args.get("q", "").strip()

    if q:
        rows = con.execute("""
            SELECT * FROM teachers
            WHERE name LIKE ?
               OR phone LIKE ?
               OR subject LIKE ?
            ORDER BY id DESC
        """, (
            "%" + q + "%",
            "%" + q + "%",
            "%" + q + "%"
        )).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM teachers ORDER BY id DESC"
        ).fetchall()

    con.close()

    return render_template(
        "teachers.html",
        teachers=rows,
        q=q
    )

@app.route("/teachers/<int:tid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_teacher(tid):
    con = db()

    teacher = con.execute(
        "SELECT * FROM teachers WHERE id=?",
        (tid,)
    ).fetchone()

    if not teacher:
        con.close()
        return "Teacher not found", 404

    if request.method == "POST":
        con.execute("""
            UPDATE teachers
            SET name=?, phone=?, subject=?, salary=?
            WHERE id=?
        """, (
            request.form["name"],
            request.form.get("phone"),
            request.form.get("subject"),
            float(request.form.get("salary") or 0),
            tid
        ))

        new_password = request.form.get("password", "").strip()
        new_username = request.form.get("username", "").strip()

        if new_username:
            con.execute(
                "UPDATE users SET username=? WHERE teacher_id=?",
                (new_username, tid)
            )

        if new_password:
            con.execute(
                "UPDATE users SET password_hash=? WHERE teacher_id=?",
                (generate_password_hash(new_password), tid)
            )

        con.commit()
        con.close()

        flash("Teacher updated.", "success")
        return redirect(url_for("teachers"))

    con.close()
    return render_template("teacher_edit.html", teacher=teacher)

@app.route("/teachers/<int:tid>/delete", methods=["POST"])
@login_required
@admin_required
def delete_teacher(tid):
    con = db()
    con.execute("DELETE FROM users WHERE teacher_id=?", (tid,))
    con.execute("DELETE FROM assignments WHERE teacher_id=?", (tid,))
    con.execute("DELETE FROM teachers WHERE id=?", (tid,))
    con.commit()
    con.close()

    flash("Teacher deleted.", "success")
    return redirect(url_for("teachers"))


# ---------------- ATTENDANCE ----------------

@app.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    if session.get("role") not in ("admin", "teacher"):
        return redirect(url_for("student_dashboard"))

    selected_date = request.values.get(
        "date",
        date.today().isoformat()
    )

    con = db()

    if request.method == "POST":

        # Admin-only attendance delete from the same form
        delete_id = request.form.get("delete_id")
        if delete_id:
            if session.get("role") == "admin":
                con.execute(
                    "DELETE FROM attendance WHERE id=?",
                    (int(delete_id),)
                )
                con.commit()
                con.close()
                flash("Attendance deleted.", "success")
                return redirect(
                    url_for("attendance", date=selected_date)
                )
            con.close()
            return redirect(
                url_for("attendance", date=selected_date)
            )

        for key, value in request.form.items():
            if key.startswith("status_"):
                sid = int(key.split("_")[1])

                con.execute("""
                    INSERT INTO attendance
                    (student_id,attendance_date,status)
                    VALUES(?,?,?)
                    ON CONFLICT(student_id,attendance_date)
                    DO UPDATE SET status=excluded.status
                """, (
                    sid,
                    selected_date,
                    value
                ))

        con.commit()
        flash("Attendance saved.", "success")

    rows = con.execute("""
        SELECT s.id,s.student_id,s.name,s.class_name,s.batch,
               a.id attendance_id,
               COALESCE(a.status,'Absent') status
        FROM students s
        LEFT JOIN attendance a
        ON a.student_id=s.id
        AND a.attendance_date=?
        WHERE s.active=1
        ORDER BY s.class_name,s.batch,s.name
    """, (selected_date,)).fetchall()

    con.close()

    return render_template(
        "attendance.html",
        students=rows,
        selected_date=selected_date
    )

# ---------------- EXAMS ----------------

@app.route("/exams", methods=["GET", "POST"])
@login_required
def exams():
    if session.get("role") not in ("admin", "teacher"):
        return redirect(url_for("dashboard"))
    con = db()

    if request.method == "POST":
        if session.get("role") != "admin":
            con.close()
            return redirect(url_for("exams"))

        con.execute("""
            INSERT INTO exams
            (title,subject,exam_date,full_marks,pass_marks)
            VALUES(?,?,?,?,?)
        """, (
            request.form["title"],
            request.form.get("subject"),
            request.form.get("exam_date"),
            float(request.form.get("full_marks") or 100),
            float(request.form.get("pass_marks") or 33)
        ))

        con.commit()
        flash("Exam created.", "success")
        return redirect(url_for("exams"))

    rows = con.execute(
        "SELECT * FROM exams ORDER BY id DESC"
    ).fetchall()

    con.close()
    return render_template("exams.html", exams=rows)

@app.route("/exams/<int:eid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_exam(eid):
    con = db()

    exam = con.execute(
        "SELECT * FROM exams WHERE id=?",
        (eid,)
    ).fetchone()

    if not exam:
        con.close()
        return "Exam not found", 404

    if request.method == "POST":
        con.execute("""
            UPDATE exams
            SET title=?, subject=?, exam_date=?,
                full_marks=?, pass_marks=?
            WHERE id=?
        """, (
            request.form["title"],
            request.form.get("subject"),
            request.form.get("exam_date"),
            float(request.form.get("full_marks") or 100),
            float(request.form.get("pass_marks") or 33),
            eid
        ))

        con.commit()
        con.close()

        flash("Exam updated.", "success")
        return redirect(url_for("exams"))

    con.close()
    return render_template("exam_edit.html", exam=exam)

@app.route("/exams/<int:eid>/delete", methods=["POST"])
@login_required
@admin_required
def delete_exam(eid):
    con = db()
    con.execute("DELETE FROM marks WHERE exam_id=?", (eid,))
    con.execute("DELETE FROM exams WHERE id=?", (eid,))
    con.commit()
    con.close()

    flash("Exam deleted.", "success")
    return redirect(url_for("exams"))

@app.route("/exams/<int:eid>/marks", methods=["GET", "POST"])
@login_required
def marks(eid):
    if session.get("role") not in ("admin", "teacher"):
        return redirect(url_for("student_dashboard"))

    con = db()

    exam = con.execute(
        "SELECT * FROM exams WHERE id=?",
        (eid,)
    ).fetchone()

    if not exam:
        con.close()
        return "Exam not found", 404

    if request.method == "POST":
        for key, value in request.form.items():
            if key.startswith("mark_"):
                sid = int(key.split("_")[1])

                con.execute("""
                    INSERT INTO marks(exam_id,student_id,marks)
                    VALUES(?,?,?)
                    ON CONFLICT(exam_id,student_id)
                    DO UPDATE SET marks=excluded.marks
                """, (
                    eid,
                    sid,
                    float(value or 0)
                ))

        con.commit()
        flash("Marks saved.", "success")

    rows = con.execute("""
        SELECT s.id,s.student_id,s.name,
               COALESCE(m.marks,0) marks
        FROM students s
        LEFT JOIN marks m
        ON m.student_id=s.id
        AND m.exam_id=?
        WHERE s.active=1
        ORDER BY s.name
    """, (eid,)).fetchall()

    con.close()

    return render_template(
        "marks.html",
        exam=exam,
        students=rows
    )

# ---------------- MARKSHEET ----------------

@app.route("/marksheet/<int:sid>")
@login_required
def marksheet(sid):
    if session.get("role") == "student":
        if session.get("student_id") != sid:
            return redirect(url_for("student_dashboard"))

    con = db()

    student = con.execute(
        "SELECT * FROM students WHERE id=?",
        (sid,)
    ).fetchone()

    if not student:
        con.close()
        return "Student not found", 404

    results = con.execute("""
        SELECT e.title,e.subject,e.exam_date,
               e.full_marks,e.pass_marks,
               COALESCE(m.marks,0) marks
        FROM exams e
        LEFT JOIN marks m
        ON m.exam_id=e.id
        AND m.student_id=?
        ORDER BY e.exam_date DESC,e.id DESC
    """, (sid,)).fetchall()

    con.close()

    return render_template(
        "marksheet.html",
        student=student,
        results=results
    )

# ---------------- FEES ----------------

@app.route("/fees", methods=["GET", "POST"])
@login_required
@admin_required
def fees():
    con = db()

    if request.method == "POST":
        amount = float(request.form.get("amount") or 0)
        paid = float(request.form.get("paid_amount") or 0)

        if paid >= amount:
            status = "Paid"
        elif paid > 0:
            status = "Partial"
        else:
            status = "Unpaid"

        con.execute("""
            INSERT INTO fees
            (student_id,fee_month,amount,paid_amount,
             payment_date,status,note)
            VALUES(?,?,?,?,?,?,?)
        """, (
            int(request.form["student_id"]),
            request.form["fee_month"],
            amount,
            paid,
            request.form.get("payment_date"),
            status,
            request.form.get("note")
        ))

        con.commit()
        flash("Fee saved.", "success")
        return redirect(url_for("fees"))

    students = con.execute("""
        SELECT id,student_id,name
        FROM students
        WHERE active=1
        ORDER BY name
    """).fetchall()

    rows = con.execute("""
        SELECT f.*,s.student_id,s.name
        FROM fees f
        JOIN students s ON s.id=f.student_id
        ORDER BY f.id DESC
    """).fetchall()

    con.close()

    return render_template(
        "fees.html",
        students=students,
        fees=rows
    )

@app.route("/fees/<int:fid>/delete", methods=["POST"])
@login_required
@admin_required
def delete_fee(fid):
    con = db()
    con.execute("DELETE FROM fees WHERE id=?", (fid,))
    con.commit()
    con.close()

    flash("Fee record deleted.", "success")
    return redirect(url_for("fees"))

# ---------------- FINANCE ----------------

@app.route("/finance", methods=["GET", "POST"])
@login_required
@admin_required
def finance():
    con = db()

    if request.method == "POST":
        con.execute("""
            INSERT INTO transactions
            (tx_date,tx_type,category,amount,note)
            VALUES(?,?,?,?,?)
        """, (
            request.form["tx_date"],
            request.form["tx_type"],
            request.form.get("category"),
            float(request.form["amount"]),
            request.form.get("note")
        ))

        con.commit()
        flash("Transaction saved.", "success")
        return redirect(url_for("finance"))

    rows = con.execute("""
        SELECT * FROM transactions
        ORDER BY tx_date DESC,id DESC
    """).fetchall()

    income = con.execute("""
        SELECT COALESCE(SUM(amount),0) n
        FROM transactions WHERE tx_type='Income'
    """).fetchone()["n"]

    expense = con.execute("""
        SELECT COALESCE(SUM(amount),0) n
        FROM transactions WHERE tx_type='Expense'
    """).fetchone()["n"]

    con.close()

    return render_template(
        "finance.html",
        transactions=rows,
        income=income,
        expense=expense
    )

@app.route("/finance/<int:tid>/delete", methods=["POST"])
@login_required
@admin_required
def delete_transaction(tid):
    con = db()
    con.execute(
        "DELETE FROM transactions WHERE id=?",
        (tid,)
    )
    con.commit()
    con.close()

    flash("Transaction deleted.", "success")
    return redirect(url_for("finance"))

# ---------------- ROUTINE ----------------

@app.route("/routine", methods=["GET", "POST"])
@login_required
def routine():
    if session.get("role") not in ("admin", "teacher", "student"):
        return redirect(url_for("login"))

    con = db()

    if request.method == "POST":
        if session.get("role") != "admin":
            con.close()
            return redirect(url_for("routine"))

        con.execute("""
            INSERT INTO routines
            (day_name,batch,subject,teacher,start_time,end_time)
            VALUES(?,?,?,?,?,?)
        """, (
            request.form["day_name"],
            request.form.get("batch"),
            request.form.get("subject"),
            request.form.get("teacher"),
            request.form.get("start_time"),
            request.form.get("end_time")
        ))

        con.commit()
        flash("Routine added.", "success")

    rows = con.execute("""
        SELECT * FROM routines
        ORDER BY id DESC
    """).fetchall()

    con.close()

    return render_template(
        "routine.html",
        routines=rows
    )

@app.route("/routine/<int:rid>/delete", methods=["POST"])
@login_required
@admin_required
def delete_routine(rid):
    con = db()
    con.execute(
        "DELETE FROM routines WHERE id=?",
        (rid,)
    )
    con.commit()
    con.close()

    flash("Routine deleted.", "success")
    return redirect(url_for("routine"))

# ---------------- ASSIGNMENTS ----------------

@app.route("/assignments", methods=["GET", "POST"])
@login_required
@admin_required
def assignments():
    con = db()

    if request.method == "POST":
        con.execute("""
            INSERT INTO assignments(teacher_id,batch,subject)
            VALUES(?,?,?)
        """, (
            int(request.form["teacher_id"]),
            request.form["batch"],
            request.form["subject"]
        ))

        con.commit()
        flash("Teacher assigned.", "success")
        return redirect(url_for("assignments"))

    teachers = con.execute(
        "SELECT * FROM teachers WHERE active=1 ORDER BY name"
    ).fetchall()

    rows = con.execute("""
        SELECT a.*,t.name teacher_name
        FROM assignments a
        JOIN teachers t ON t.id=a.teacher_id
        ORDER BY a.id DESC
    """).fetchall()

    con.close()

    return render_template(
        "assignments.html",
        teachers=teachers,
        assignments=rows
    )

@app.route("/assignments/<int:aid>/delete", methods=["POST"])
@login_required
@admin_required
def delete_assignment(aid):
    con = db()
    con.execute(
        "DELETE FROM assignments WHERE id=?",
        (aid,)
    )
    con.commit()
    con.close()

    flash("Assignment deleted.", "success")
    return redirect(url_for("assignments"))

# ---------------- NOTICES ----------------

@app.route("/notices", methods=["GET", "POST"])
@login_required
def notices():
    con = db()

    if request.method == "POST":
        if session.get("role") != "admin":
            con.close()
            return redirect(url_for("notices"))

        con.execute("""
            INSERT INTO notices(title,message)
            VALUES(?,?)
        """, (
            request.form["title"],
            request.form["message"]
        ))

        con.commit()
        flash("Notice published.", "success")
        return redirect(url_for("notices"))

    rows = con.execute("""
        SELECT * FROM notices
        ORDER BY id DESC
    """).fetchall()

    con.close()

    return render_template(
        "notices.html",
        notices=rows
    )

@app.route("/notices/<int:nid>/delete", methods=["POST"])
@login_required
@admin_required
def delete_notice(nid):
    con = db()
    con.execute(
        "DELETE FROM notices WHERE id=?",
        (nid,)
    )
    con.commit()
    con.close()

    flash("Notice deleted.", "success")
    return redirect(url_for("notices"))

# ---------------- STUDENT / TEACHER PORTALS ----------------



# ---------------- MASTER ADMIN EDIT ROUTES ----------------

@app.route("/attendance/<int:aid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_attendance(aid):
    con = db()
    row = con.execute("""
        SELECT a.*, s.student_id AS sid_code, s.name AS student_name
        FROM attendance a
        JOIN students s ON s.id=a.student_id
        WHERE a.id=?
    """, (aid,)).fetchone()
    if not row:
        con.close()
        return "Attendance record not found", 404

    students = con.execute(
        "SELECT id,student_id,name FROM students ORDER BY name"
    ).fetchall()

    if request.method == "POST":
        con.execute("""
            UPDATE attendance
            SET student_id=?, attendance_date=?, status=?
            WHERE id=?
        """, (
            int(request.form["student_id"]),
            request.form["attendance_date"],
            request.form["status"],
            aid
        ))
        con.commit()
        con.close()
        flash("Attendance updated.", "success")
        return redirect(url_for("attendance"))

    con.close()
    return render_template(
        "attendance_edit.html",
        attendance=row,
        students=students
    )


@app.route("/attendance/<int:aid>/delete", methods=["POST"])
@login_required
@admin_required
def delete_attendance(aid):
    con = db()
    con.execute("DELETE FROM attendance WHERE id=?", (aid,))
    con.commit()
    con.close()
    flash("Attendance deleted.", "success")
    return redirect(url_for("attendance"))


@app.route("/fees/<int:fid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_fee(fid):
    con = db()
    fee = con.execute(
        "SELECT * FROM fees WHERE id=?", (fid,)
    ).fetchone()

    if not fee:
        con.close()
        return "Fee record not found", 404

    students = con.execute(
        "SELECT id,student_id,name FROM students ORDER BY name"
    ).fetchall()

    if request.method == "POST":
        amount = float(request.form.get("amount") or 0)
        paid = float(request.form.get("paid_amount") or 0)

        if paid >= amount:
            status = "Paid"
        elif paid > 0:
            status = "Partial"
        else:
            status = "Unpaid"

        con.execute("""
            UPDATE fees
            SET student_id=?, fee_month=?, amount=?, paid_amount=?,
                payment_date=?, status=?, note=?
            WHERE id=?
        """, (
            int(request.form["student_id"]),
            request.form["fee_month"],
            amount,
            paid,
            request.form.get("payment_date"),
            status,
            request.form.get("note"),
            fid
        ))
        con.commit()
        con.close()
        flash("Fee record updated.", "success")
        return redirect(url_for("fees"))

    con.close()
    return render_template(
        "fee_edit.html",
        fee=fee,
        students=students
    )


@app.route("/finance/<int:tid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_transaction(tid):
    con = db()
    tx = con.execute(
        "SELECT * FROM transactions WHERE id=?", (tid,)
    ).fetchone()

    if not tx:
        con.close()
        return "Transaction not found", 404

    if request.method == "POST":
        con.execute("""
            UPDATE transactions
            SET tx_date=?, tx_type=?, category=?, amount=?, note=?
            WHERE id=?
        """, (
            request.form["tx_date"],
            request.form["tx_type"],
            request.form.get("category"),
            float(request.form.get("amount") or 0),
            request.form.get("note"),
            tid
        ))
        con.commit()
        con.close()
        flash("Transaction updated.", "success")
        return redirect(url_for("finance"))

    con.close()
    return render_template("finance_edit.html", transaction=tx)


@app.route("/routine/<int:rid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_routine(rid):
    con = db()
    row = con.execute(
        "SELECT * FROM routines WHERE id=?", (rid,)
    ).fetchone()

    if not row:
        con.close()
        return "Routine not found", 404

    if request.method == "POST":
        con.execute("""
            UPDATE routines
            SET day_name=?, batch=?, subject=?, teacher=?,
                start_time=?, end_time=?
            WHERE id=?
        """, (
            request.form["day_name"],
            request.form.get("batch"),
            request.form.get("subject"),
            request.form.get("teacher"),
            request.form.get("start_time"),
            request.form.get("end_time"),
            rid
        ))
        con.commit()
        con.close()
        flash("Routine updated.", "success")
        return redirect(url_for("routine"))

    con.close()
    return render_template("routine_edit.html", routine=row)


@app.route("/assignments/<int:aid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_assignment(aid):
    con = db()
    row = con.execute(
        "SELECT * FROM assignments WHERE id=?", (aid,)
    ).fetchone()

    if not row:
        con.close()
        return "Assignment not found", 404

    teachers = con.execute(
        "SELECT * FROM teachers WHERE active=1 ORDER BY name"
    ).fetchall()

    if request.method == "POST":
        con.execute("""
            UPDATE assignments
            SET teacher_id=?, batch=?, subject=?
            WHERE id=?
        """, (
            int(request.form["teacher_id"]),
            request.form["batch"],
            request.form["subject"],
            aid
        ))
        con.commit()
        con.close()
        flash("Teacher assignment updated.", "success")
        return redirect(url_for("assignments"))

    con.close()
    return render_template(
        "assignment_edit.html",
        assignment=row,
        teachers=teachers
    )


@app.route("/notices/<int:nid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_notice(nid):
    con = db()
    notice = con.execute(
        "SELECT * FROM notices WHERE id=?", (nid,)
    ).fetchone()

    if not notice:
        con.close()
        return "Notice not found", 404

    if request.method == "POST":
        con.execute("""
            UPDATE notices
            SET title=?, message=?
            WHERE id=?
        """, (
            request.form["title"],
            request.form["message"],
            nid
        ))
        con.commit()
        con.close()
        flash("Notice updated.", "success")
        return redirect(url_for("notices"))

    con.close()
    return render_template("notice_edit.html", notice=notice)


# ---------------- ADMIN PASSWORD CONTROL ----------------

@app.route("/admin/password", methods=["GET", "POST"])
@login_required
@admin_required
def admin_password():
    con = db()
    user = con.execute(
        "SELECT * FROM users WHERE id=? AND role='admin'",
        (session.get("user_id"),)
    ).fetchone()

    if not user:
        con.close()
        return "Admin user not found", 404

    if request.method == "POST":
        current = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "").strip()
        confirm = request.form.get("confirm_password", "")

        if not check_password_hash(user["password_hash"], current):
            con.close()
            flash("Current password is incorrect.", "danger")
            return redirect(url_for("admin_password"))

        if len(new_password) < 6:
            con.close()
            flash("New password must be at least 6 characters.", "danger")
            return redirect(url_for("admin_password"))

        if new_password != confirm:
            con.close()
            flash("New passwords do not match.", "danger")
            return redirect(url_for("admin_password"))

        con.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (generate_password_hash(new_password), user["id"])
        )
        con.commit()
        con.close()

        flash("Admin password changed successfully.", "success")
        return redirect(url_for("admin_password"))

    con.close()
    return render_template("admin_password.html")


@app.route("/admin/users", methods=["GET", "POST"])
@login_required
@admin_required
def admin_users():
    con = db()

    if request.method == "POST":
        uid = int(request.form["user_id"])
        new_password = request.form.get("password", "").strip()

        if not new_password:
            flash("Enter a new password.", "danger")
            con.close()
            return redirect(url_for("admin_users"))

        if len(new_password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            con.close()
            return redirect(url_for("admin_users"))

        con.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (generate_password_hash(new_password), uid)
        )
        con.commit()
        flash("Password reset successfully.", "success")

    users = con.execute("""
        SELECT id, username, role, student_id, teacher_id
        FROM users
        ORDER BY role, username
    """).fetchall()

    con.close()
    return render_template("admin_users.html", users=users)


@app.route("/student-dashboard")
@login_required
def student_dashboard():
    if session.get("role") != "student":
        return redirect(url_for("dashboard"))

    con = db()

    student = con.execute(
        "SELECT * FROM students WHERE id=?",
        (session.get("student_id"),)
    ).fetchone()

    notices = con.execute(
        "SELECT * FROM notices ORDER BY id DESC LIMIT 5"
    ).fetchall()

    con.close()

    return render_template(
        "student_dashboard.html",
        student=student,
        notices=notices
    )

@app.route("/teacher-dashboard")
@login_required
def teacher_dashboard():
    if session.get("role") != "teacher":
        return redirect(url_for("dashboard"))

    con = db()

    teacher = con.execute(
        "SELECT * FROM teachers WHERE id=?",
        (session.get("teacher_id"),)
    ).fetchone()

    assignments = con.execute("""
        SELECT * FROM assignments
        WHERE teacher_id=?
        ORDER BY id DESC
    """, (session.get("teacher_id"),)).fetchall()

    con.close()

    return render_template(
        "teacher_dashboard.html",
        teacher=teacher,
        assignments=assignments
    )

@app.route("/student-attendance")
@login_required
def student_attendance_report():
    if session.get("role") != "student":
        flash("Student access only.", "error")
        return redirect(url_for("login"))

    sid = session.get("student_id")
    con = db()
    student = con.execute(
        "SELECT * FROM students WHERE id=? OR student_id=? LIMIT 1",
        (sid, sid)
    ).fetchone()

    if not student:
        con.close()
        flash("Student profile not found.", "error")
        return redirect(url_for("student_dashboard"))

    attendance = con.execute(
        "SELECT attendance_date,status FROM attendance WHERE student_id=? ORDER BY attendance_date DESC",
        (student["id"],)
    ).fetchall()
    con.close()

    return render_template(
        "student_attendance_report.html",
        student=student,
        attendance=attendance
    )


@app.route("/student-fees")
@login_required
def student_fees_report():
    if session.get("role") != "student":
        flash("Student access only.", "error")
        return redirect(url_for("login"))

    sid = session.get("student_id")
    con = db()
    student = con.execute(
        "SELECT * FROM students WHERE id=? OR student_id=? LIMIT 1",
        (sid, sid)
    ).fetchone()

    if not student:
        con.close()
        flash("Student profile not found.", "error")
        return redirect(url_for("student_dashboard"))

    fees = con.execute(
        "SELECT * FROM fees WHERE student_id=? ORDER BY id DESC",
        (student["id"],)
    ).fetchall()
    con.close()

    return render_template(
        "student_fees_report.html",
        student=student,
        fees=fees
    )

if __name__ == "__main__":
    init_db()
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
