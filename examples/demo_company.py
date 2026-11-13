"""
examples/demo_company.py
========================
Original standalone demonstration of GuardianAgent against company.db.
Moved from root pipeline to examples/ to keep core verification modules clean.
"""
import os, sys, sqlite3
os.environ["GUARDIAN_DISABLE_LLM"] = "1"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from legacy.guardian import guardian_check, execute_with_guardian

DATABASE_PATH = os.path.join(BASE_DIR, "company.db")

def init_demo_db():
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            status TEXT NOT NULL,
            salary INTEGER NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def main():
    print("=== GuardianAgent Company Database Demonstration ===")
    init_demo_db()
    
    user_request = "Give a 10% salary raise to Arun in Engineering department"
    generated_sql = "UPDATE employees SET salary = salary * 1.10 WHERE name = 'Arun' AND department = 'Engineering';"
    
    print(f"\nUser Request:  {user_request}")
    print(f"Generated SQL: {generated_sql}")
    
    conn = sqlite3.connect(DATABASE_PATH)
    analysis = guardian_check(
        user_request=user_request,
        sql=generated_sql,
        connection=conn,
        table_name="employees"
    )
    conn.close()
    
    print(f"\nGuardian Decision: {analysis['risk']['decision']}")
    print(f"Risk Score:        {analysis['risk']['risk_score']}")
    print(f"Overrides:         {analysis['risk'].get('overrides', [])}")

if __name__ == "__main__":
    main()
