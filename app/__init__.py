# app/__init__.py
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from dotenv import load_dotenv
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

    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = (
            database_url
            or 'sqlite:///' + os.path.join(app.instance_path, 'nestgold.db')
    )

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # ------------------
    # Initialize extensions
    # ------------------
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

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
