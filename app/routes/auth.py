# app/routes/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import db, User
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from .forms import LoginForm
import os

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# ------------------
# Rate limiter
# ------------------
limiter = Limiter(key_func=get_remote_address)

# ------------------
# Login
# ------------------
@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")  # prevent brute force
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():  # handles CSRF automatically
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user, remember=form.remember_me.data)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('admin.dashboard'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html', form=form)

# ------------------
# Logout
# ------------------
@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))

# ------------------
# Admin creation (from environment)
# ------------------
def create_admin():
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    admin_password = os.getenv('ADMIN_PASSWORD')
    if not admin_password:
        print("WARNING: ADMIN_PASSWORD not set in environment!")
        return

    if not User.query.filter_by(username=admin_username).first():
        admin = User(
            username=admin_username,
            password_hash=generate_password_hash(admin_password, method='pbkdf2:sha256'),
            role='admin'
        )
        db.session.add(admin)
        db.session.commit()
        print(f"Admin created: username='{admin_username}'")
