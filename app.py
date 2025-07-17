from flask import Flask, render_template, request, redirect, url_for, Response, send_file, session, flash
import sqlite3
import csv
import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta


app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure key in production
DB_NAME = "expenses.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            amount REAL,
            category TEXT,
            description TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # Update if table doesn't have recurring columns
    c.execute("PRAGMA table_info(expenses)")
    columns = [row[1] for row in c.fetchall()]
    if 'is_recurring' not in columns:
        c.execute("ALTER TABLE expenses ADD COLUMN is_recurring INTEGER DEFAULT 0")
    if 'frequency' not in columns:
        c.execute("ALTER TABLE expenses ADD COLUMN frequency TEXT DEFAULT 'monthly'")
        
    conn.commit()
    conn.close()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def check_and_clone_recurring(user_id):
    today = datetime.now().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Find recurring expenses last added BEFORE today
    c.execute("""
        SELECT id, amount, category, description, frequency, MAX(date)
        FROM expenses
        WHERE user_id = ? AND is_recurring = 1
        GROUP BY category, frequency, description
    """, (user_id,))
    recurring = c.fetchall()

    for rec in recurring:
        last_date = datetime.strptime(rec[5][:10], "%Y-%m-%d")
        freq = rec[4]
        due = False

        if freq == "daily":
            due = (datetime.now() - last_date).days >= 1
        elif freq == "weekly":
            due = (datetime.now() - last_date).days >= 7
        elif freq == "monthly":
            due = (datetime.now().month != last_date.month or
                   datetime.now().year != last_date.year)

        if due:
            new_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("""
                INSERT INTO expenses (user_id, date, amount, category, description, is_recurring, frequency)
                VALUES (?, ?, ?, ?, ?, 1, ?)
            """, (user_id, new_date, rec[1], rec[2], rec[3], freq))

    conn.commit()
    conn.close()


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            conn.commit()
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Username already exists.", "danger")
        conn.close()

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT id, password FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['username'] = username
            return redirect(url_for('index'))
        else:
            flash("Invalid credentials.", "danger")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    check_and_clone_recurring(session['user_id'])
    category = request.args.get("category", "")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")

    query = "SELECT id, date, amount, category, description FROM expenses WHERE user_id = ?"
    params = [session['user_id']]

    if category:
        query += " AND category = ?"
        params.append(category)

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)

    if end_date:
        query += " AND date <= ?"
        params.append(end_date + " 23:59:59")

    query += " ORDER BY date DESC"

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(query, params)
    expenses = c.fetchall()

    c.execute("SELECT SUM(amount) FROM expenses WHERE user_id = ?", (session['user_id'],))
    total = c.fetchone()[0] or 0

    c.execute("SELECT category, SUM(amount) FROM expenses WHERE user_id = ? GROUP BY category", (session['user_id'],))
    chart_data = c.fetchall()

    c.execute("""
        SELECT strftime('%Y-%m', date) AS month, SUM(amount)
        FROM expenses
        WHERE user_id = ?
        GROUP BY month
        ORDER BY month
    """, (session['user_id'],))
    monthly_summary = c.fetchall()

    # Spending by category per month
    c.execute("""
        SELECT strftime('%Y-%m', date) AS month, category, SUM(amount)
        FROM expenses
        WHERE user_id = ?
        GROUP BY month, category
        ORDER BY month
    """, (session['user_id'],))
    rows = c.fetchall()

    # Transform to {month: {category: amount}}
    from collections import defaultdict
    import json

    category_months = defaultdict(lambda: defaultdict(float))
    all_categories = set()

    for month, cat, amount in rows:
        category_months[month][cat] += amount
        all_categories.add(cat)

    months_sorted = sorted(category_months.keys())
    category_series = []

    for cat in sorted(all_categories):
        category_series.append({
            'label': cat,
            'data': [category_months[m].get(cat, 0) for m in months_sorted]
        })

    conn.close()

    labels = [row[0] for row in chart_data]
    amounts = [row[1] for row in chart_data]

    months = [row[0] for row in monthly_summary]
    monthly_totals = [row[1] for row in monthly_summary] 


    return render_template("index.html", expenses=expenses, total=total,
                           category=category, start_date=start_date, end_date=end_date,
                           labels=labels, amounts=amounts,
                           months=months, monthly_totals=monthly_totals,
                           months_sorted=months_sorted, category_series=category_series)

@app.route('/add', methods=["GET", "POST"])
@login_required
def add():
    if request.method == "POST":
        amount = float(request.form['amount'])
        category = request.form['category']
        description = request.form['description']
        is_recurring = 1 if request.form.get('is_recurring') else 0
        frequency = request.form['frequency'] if is_recurring else 'none'
        date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""
            INSERT INTO expenses (user_id, date, amount, category, description, is_recurring, frequency)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session['user_id'], date, amount, category, description, is_recurring, frequency))
        conn.commit()
        conn.close()
        return redirect(url_for("index"))
    return render_template("add.html")

@app.route('/edit/<int:id>', methods=["GET", "POST"])
@login_required
def edit(id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if request.method == "POST":
        amount = float(request.form['amount'])
        category = request.form['category']
        description = request.form['description']
        c.execute("UPDATE expenses SET amount=?, category=?, description=? WHERE id=? AND user_id=?",
                  (amount, category, description, id, session['user_id']))
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    c.execute("SELECT id, amount, category, description FROM expenses WHERE id=? AND user_id=?", (id, session['user_id']))
    expense = c.fetchone()
    conn.close()
    return render_template("edit.html", expense=expense)

@app.route('/delete/<int:id>')
@login_required
def delete(id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM expenses WHERE id=? AND user_id=?", (id, session['user_id']))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))



@app.route('/export/csv')
@login_required
def export_csv():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT date, amount, category, description FROM expenses WHERE user_id = ? ORDER BY date DESC", (session['user_id'],))
    expenses = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Amount", "Category", "Description"])
    for e in expenses:
        writer.writerow(e)

    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers["Content-Disposition"] = "attachment; filename=expenses.csv"
    return response

@app.route('/export/pdf')
@login_required
def export_pdf():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT date, amount, category, description FROM expenses WHERE user_id = ? ORDER BY date DESC", (session['user_id'],))
    expenses = c.fetchall()
    conn.close()

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    p.setFont("Helvetica", 12)
    p.drawString(50, height - 40, "Expense Report")

    y = height - 70
    p.setFont("Helvetica", 10)
    p.drawString(50, y, "Date")
    p.drawString(180, y, "Amount")
    p.drawString(260, y, "Category")
    p.drawString(380, y, "Description")
    y -= 20

    for e in expenses:
        if y < 50:
            p.showPage()
            y = height - 50
        p.drawString(50, y, e[0][:19])
        p.drawString(180, y, f"\u20b1{e[1]:.2f}")
        p.drawString(260, y, e[2])
        p.drawString(380, y, e[3])
        y -= 15

    p.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="expenses.pdf", mimetype='application/pdf')

@app.route('/profile')
@login_required
def profile():
    user_id = session['user_id']

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # 1. Top categories (by total spending)
    c.execute("""
        SELECT category, SUM(amount) as total
        FROM expenses
        WHERE user_id = ?
        GROUP BY category
        ORDER BY total DESC
        LIMIT 3
    """, (user_id,))
    top_categories = c.fetchall()

    # 2. Date range
    c.execute("SELECT MIN(date), MAX(date) FROM expenses WHERE user_id = ?", (user_id,))
    min_date, max_date = c.fetchone()
    date_range_days = (datetime.strptime(max_date, "%Y-%m-%d %H:%M:%S") - datetime.strptime(min_date, "%Y-%m-%d %H:%M:%S")).days + 1 if min_date and max_date else 1

    # 3. Total spending
    c.execute("SELECT SUM(amount) FROM expenses WHERE user_id = ?", (user_id,))
    total_spent = c.fetchone()[0] or 0

    # 4. Monthly spending (grouped)
    c.execute("""
        SELECT COUNT(DISTINCT strftime('%Y-%m', date)) FROM expenses WHERE user_id = ?
    """, (user_id,))
    month_count = c.fetchone()[0] or 1

    conn.close()

    avg_daily = total_spent / date_range_days if date_range_days else 0
    avg_monthly = total_spent / month_count if month_count else 0

    return render_template("profile.html",
                           username=session['username'],
                           top_categories=top_categories,
                           avg_daily=round(avg_daily, 2),
                           avg_monthly=round(avg_monthly, 2),
                           total_spent=round(total_spent, 2))


@app.route('/manifest.json')
def manifest():
    return send_file('static/manifest.json', mimetype='application/manifest+json')


if __name__ == '__main__':
    init_db()
