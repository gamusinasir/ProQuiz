# reset_db.py
from app import app, db
import os

if __name__ == "__main__":
    with app.app_context():
        db.session.close()  # close active sessions
        
        # Recreate tables
        db.create_all()
        print("New database created.")