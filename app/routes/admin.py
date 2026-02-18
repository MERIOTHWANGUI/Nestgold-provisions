# app/routes/admin.py
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required, current_user
from app.models import Subscription, SubscriptionPlan, SubscriptionStatus, db
from sqlalchemy.exc import IntegrityError
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, IntegerField, BooleanField, SelectField, TextAreaField
from wtforms.validators import DataRequired, NumberRange, Length
from markupsafe import escape
from wtforms import SubmitField


admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# -----------------------------
# Admin access control
# -----------------------------
@admin_bp.before_request
@login_required
def require_admin():
    """Only allow users with role 'admin'."""
    if current_user.role != 'admin':
        flash('Access denied. Admin only.', 'danger')
        return redirect(url_for('main.index'))

# -----------------------------
# Plan Form
# -----------------------------


class DeleteForm(FlaskForm):
    submit = SubmitField('Delete')

class PlanForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    trays_per_week = IntegerField('Trays per Week', validators=[DataRequired(), NumberRange(min=1)])
    price_per_month = FloatField('Price per Month', validators=[DataRequired(), NumberRange(min=1)])
    description = TextAreaField('Description')
    is_recommended = BooleanField('Most Popular')
    button_color = SelectField('Button Color', choices=[
        ('warning', 'Warning'),
        ('primary', 'Primary'),
        ('success', 'Success'),
        ('danger', 'Danger')
    ], default='warning')

# -----------------------------
# Routes
# -----------------------------
@admin_bp.route('/dashboard')
def dashboard():
    now = datetime.utcnow()
    subscriptions = Subscription.query.order_by(Subscription.start_date.desc()).all()
    active = Subscription.query.filter(Subscription.current_period_end > now).count()
    pending = Subscription.query.filter_by(status=SubscriptionStatus.PENDING.value).count()
    delete_form = DeleteForm()
    return render_template(
        'admin/dashboard.html',
        subscriptions=subscriptions,
        active=active,
        pending=pending,
        delete_form=delete_form
    )

@admin_bp.route('/plans')
def plans():
    plans = SubscriptionPlan.query.filter_by(is_active=True).all()
    delete_form = DeleteForm()
    return render_template('admin/plans.html', plans=plans, delete_form=delete_form)


@admin_bp.route('/plans/add', methods=['GET', 'POST'])
def add_plan():
    form = PlanForm()
    if form.validate_on_submit():
        # Check for duplicates
        if SubscriptionPlan.query.filter_by(name=form.name.data).first():
            flash(f'A plan with name "{escape(form.name.data)}" already exists.', 'danger')
            return redirect(url_for('admin.add_plan'))

        plan = SubscriptionPlan(
            name=escape(form.name.data),
            trays_per_week=form.trays_per_week.data,
            price_per_month=form.price_per_month.data,
            description=escape(form.description.data),
            is_recommended=form.is_recommended.data,
            button_color=form.button_color.data,
            is_active=True  # default active
        )
        db.session.add(plan)
        db.session.commit()
        flash(f'Plan "{plan.name}" added successfully!', 'success')
        return redirect(url_for('admin.plans'))

    return render_template('admin/add-plan.html', form=form)

@admin_bp.route('/plans/edit/<int:plan_id>', methods=['GET', 'POST'])
def edit_plan(plan_id):
    plan = SubscriptionPlan.query.get_or_404(plan_id)
    form = PlanForm(obj=plan)

    if form.validate_on_submit():
        existing = SubscriptionPlan.query.filter_by(name=form.name.data).first()
        if existing and existing.id != plan.id:
            flash(f'A plan with name "{escape(form.name.data)}" already exists.', 'danger')
            return redirect(url_for('admin.edit_plan', plan_id=plan.id))

        plan.name = escape(form.name.data)
        plan.trays_per_week = form.trays_per_week.data
        plan.price_per_month = form.price_per_month.data
        plan.description = escape(form.description.data)
        plan.is_recommended = form.is_recommended.data
        plan.button_color = form.button_color.data
        db.session.commit()
        flash(f'Plan "{plan.name}" updated successfully!', 'success')
        return redirect(url_for('admin.plans'))

    return render_template('admin/edit_plan.html', form=form, plan=plan)

@admin_bp.route('/plans/delete/<int:plan_id>', methods=['POST'])
def delete_plan(plan_id):
    form = DeleteForm()

    if not form.validate_on_submit():
        flash("Bad request (CSRF validation failed).", "danger")
        return redirect(url_for('admin.plans'))

    plan = SubscriptionPlan.query.get_or_404(plan_id)

    if plan.is_recommended:
        flash("You cannot delete a plan marked as Most Popular.", "warning")
        return redirect(url_for('admin.plans'))

    db.session.delete(plan)
    db.session.commit()

    flash(f'Plan "{plan.name}" has been deleted permanently.', 'success')
    return redirect(url_for('admin.plans'))


@admin_bp.route('/subscriptions/delete/<int:sub_id>', methods=['POST'])
def delete_subscription(sub_id):
    form = DeleteForm()

    if not form.validate_on_submit():
        flash("Bad request (CSRF validation failed).", "danger")
        return redirect(url_for('admin.dashboard'))

    subscription = Subscription.query.get_or_404(sub_id)

    try:
        db.session.delete(subscription)
        db.session.commit()
        flash(f'Subscription #{sub_id} deleted successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash(
            'Cannot delete this subscription because related records exist (payments/deliveries).',
            'warning'
        )

    return redirect(url_for('admin.dashboard'))


