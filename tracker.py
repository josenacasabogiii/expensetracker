import sqlite3
from datetime import datetime

# Connect to database (creates file if it doesn't exist)
conn = sqlite3.connect("expenses.db")
cursor = conn.cursor()

# Create table if it doesn't exist
cursor.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        amount REAL,
        category TEXT,
        description TEXT
    )
""")
conn.commit()

def add_expense():
    try:
        amount = float(input("Enter amount: "))
    except ValueError:
        print("Invalid amount.\n")
        return

    category = input("Enter category (e.g. food, transport): ")
    description = input("Enter description: ")
    date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO expenses (date, amount, category, description)
        VALUES (?, ?, ?, ?)
    """, (date, amount, category, description))
    conn.commit()
    print("✅ Expense added!\n")

def view_expenses():
    cursor.execute("SELECT date, amount, category, description FROM expenses ORDER BY date DESC")
    rows = cursor.fetchall()
    for row in rows:
        print(f"{row[0]} - ₱{row[1]:.2f} [{row[2]}] - {row[3]}")
    print()

def total_expenses():
    cursor.execute("SELECT SUM(amount) FROM expenses")
    total = cursor.fetchone()[0] or 0
    print(f"\n💸 Total spent: ₱{total:.2f}\n")

def menu():
    while True:
        print("=== Expense Tracker (SQLite) ===")
        print("1. Add Expense")
        print("2. View Expenses")
        print("3. Show Total Spent")
        print("4. Exit")

        choice = input("Choose an option: ")

        if choice == "1":
            add_expense()
        elif choice == "2":
            view_expenses()
        elif choice == "3":
            total_expenses()
        elif choice == "4":
            print("Goodbye!")
            break
        else:
            print("Invalid choice.\n")

# Run the app
menu()

# Close connection when done
conn.close()
