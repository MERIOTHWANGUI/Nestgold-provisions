from app import create_app, db
from app.models import User
import os

app = create_app()

with app.app_context():
    existing_admin = User.query.filter_by(role="admin").first()

    if existing_admin:
        print("Admin already exists.")
    else:
        username = os.environ.get("ADMIN_USERNAME")
        email = os.environ.get("ADMIN_EMAIL")
        password = os.environ.get("ADMIN_PASSWORD")

        if not username or not email or not password:
            raise Exception("Missing ADMIN_* environment variables")

        admin = User(
            username=username,
            email=email,
            role="admin"
        )

        admin.set_password(password)

        db.session.add(admin)
        db.session.commit()

        print("Admin created successfully.")
