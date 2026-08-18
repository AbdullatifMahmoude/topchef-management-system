
from passlib.context import CryptContext
import sqlite3
import os
from datetime import datetime

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def add_user(): 
    db_paths = [
        "build/dist/TopChef/data/topchef_local.db"
    ]
    
    db_path = None
    for path in db_paths:
        if os.path.exists(path):
            db_path = path
            break
            
    if not db_path:
        print("Error: topchef_local.db not found in either desktop/data/ or build/dist/TopChef/data/")
        return

    username = "Abdullatif"
    password = "Abdullatif@1234"
    full_name = "Abdullatif"
    role = "ADMIN"
    phone = "01000000000"
    hashed_password = get_password_hash(password)
    now = datetime.now().isoformat()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if user already exists
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        existing = cursor.fetchone()

        if existing:
            print(f"User {username} already exists. Updating password.")
            cursor.execute("""
                UPDATE users 
                SET hashed_password = ?, updated_at = ?
                WHERE username = ?
            """, (hashed_password, now, username))
        else:
            print(f"Adding user {username}...")
            cursor.execute("""
                INSERT INTO users (username, full_name, role, phone, hashed_password, is_active, is_deleted, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?)
            """, (username, full_name, role, phone, hashed_password, now, now))
        
        conn.commit()
        print("Success!")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    add_user()
