# seed_admin_r.py
import os
import sys

# Add the project root to sys.path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.models import db, User

app = create_app()

with app.app_context():
    username = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD")

    if not password:
        raise ValueError("ADMIN_PASSWORD environment variable is not set!")

    admin = User.query.filter_by(username=username).first()

    if admin:
        admin.set_password(password)
        db.session.commit()
        print(f"[✅] Admin user '{username}' already exists. Password updated successfully.")
    else:
        admin = User(username=username, role="admin")
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print(f"[✅] Admin user '{username}' created successfully.")
