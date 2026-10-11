from db_setup import get_engine
from sqlalchemy import text
from passlib.context import CryptContext

def create_users():
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
    engine = get_engine()
    
    with engine.begin() as conn:
        print("Création de la table app_user...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS app_user (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                username VARCHAR(255) UNIQUE NOT NULL,
                hashed_password VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'technicien')),
                assigned_gouvernorat VARCHAR(100),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        
        print("Insertion des comptes de démonstration...")
        users = [
            ("admin@gpon.local", "admin", "Admin123!", "admin", None),
            ("tech@gpon.local", "technicien", "Tech123!", "technicien", "SFAX")
        ]
        
        for email, user, pwd, role, gouv in users:
            hp = pwd_context.hash(pwd)
            conn.execute(text("""
                INSERT INTO app_user (email, username, hashed_password, role, assigned_gouvernorat)
                VALUES (:e, :u, :hp, :r, :g)
                ON CONFLICT (email) DO NOTHING
            """), {"e": email, "u": user, "hp": hp, "r": role, "g": gouv})
            
    print("Succès : Comptes admin@gpon.local et tech@gpon.local créés.")

if __name__ == "__main__":
    create_users()
