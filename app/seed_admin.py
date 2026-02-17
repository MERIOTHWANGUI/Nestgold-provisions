import os
from app import create_app, db
from app.models import User  # Make sure your User model has 'username' and 'set_password'

app = create_app()

with app.app_context():
    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")

    if not User.query.filter_by(username=username).first():
        admin = User(username=username, role="admin")
        admin.set_password(password)  # Assuming your User model has this method
        db.session.add(admin)
        db.session.commit()
        print(f"Admin user '{username}' created successfully.")
    else:
        print(f"Admin user '{username}' already exists.")
