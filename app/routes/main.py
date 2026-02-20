# app/routes/main.py
from flask import Blueprint, flash, redirect, render_template, url_for

from app import db
from app.models import Feedback, SubscriptionPlan
from app.routes.forms import FeedbackForm

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


@main_bp.route('/feedback', methods=['GET', 'POST'])
def feedback():
    form = FeedbackForm()

    if form.validate_on_submit():
        entry = Feedback(
            name=form.name.data.strip(),
            rating=form.rating.data,
            comment=form.comment.data.strip(),
        )
        db.session.add(entry)
        db.session.commit()
        flash('Thanks for your feedback.', 'success')
        return redirect(url_for('main.feedback'))

    feedback_items = Feedback.query.order_by(Feedback.created_at.desc()).limit(12).all()
    return render_template('public/feedback.html', form=form, feedback_items=feedback_items)
