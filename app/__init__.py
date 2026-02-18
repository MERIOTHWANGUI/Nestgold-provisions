# app/__init__.py
from flask import Flask, flash, redirect, request, url_for
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
import os

# Load environment variables
load_dotenv()

# Extensions
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)

    # ------------------
    # Config
    # ------------------
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret')
    app.config['WTF_CSRF_TIME_LIMIT'] = 60 * 60 * 4  # 4 hours; helps mobile users resuming tabs

    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = (
            database_url
            or 'sqlite:///' + os.path.join(app.instance_path, 'nestgold.db')
    )

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Respect reverse-proxy headers on Railway so Flask treats requests as HTTPS.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    # Harden session/remember cookies for HTTPS production environments.
    is_production = os.getenv('FLASK_ENV') == 'production' or os.getenv('RAILWAY_ENVIRONMENT') is not None
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = is_production
    app.config['REMEMBER_COOKIE_SECURE'] = is_production
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True

    # ------------------
    # Initialize extensions
    # ------------------
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        # Avoid raw 400 pages in production; redirect back with a clear message.
        flash('Session expired or invalid form token. Please try logging in again.', 'warning')
        return redirect(request.referrer or url_for('auth.login'))

    # ------------------
    # User loader
    # ------------------
    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))

    # ------------------
    # Register blueprints
    # ------------------
    from .routes.main import main_bp
    from .routes.subscription import sub_bp
    from .routes.payments import payments_bp
    from .routes.auth import auth_bp
    from .routes.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(sub_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    return app
