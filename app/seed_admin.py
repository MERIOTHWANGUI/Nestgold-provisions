# app/seed_admin.py
import os
from werkzeug.security import generate_password_hash
from app.models import db, User
from app import create_app

# Load Flask app context
app = create_app()

with app.app_context():
    # Read admin credentials from environment variables
    username = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD")

    if not password:
        raise ValueError("ADMIN_PASSWORD environment variable is not set!")

    # Check if admin user already exists
    admin = User.query.filter_by(username=username).first()

    if not admin:
        # Create new admin with hashed password
        hashed_password = generate_password_hash(password)
        admin = User(username=username, role="admin", password=hashed_password)
        db.session.add(admin)
        db.session.commit()
        print(f"[✅] Admin user '{username}' created successfully.")
    else:
        print(f"[ℹ️] Admin user '{username}' already exists.")
