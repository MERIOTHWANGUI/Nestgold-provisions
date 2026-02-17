# app/routes/main.py
from flask import Blueprint, render_template
from app.models import SubscriptionPlan
main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    plans = SubscriptionPlan.query.all()
    return render_template('public/index.html', plans=plans)

@main_bp.route('/about')
def about():
    return render_template('public/about.html')


@main_bp.route('/contact')
def contact():
    return render_template('public/contact.html')





