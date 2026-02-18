# app/routes/admin.py
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from markupsafe import escape
from sqlalchemy import and_, case, func
from sqlalchemy.exc import IntegrityError
from wtforms import (
    BooleanField,
    FloatField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange

from app.models import (
    Delivery,
    DeliveryStatus,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    db,
)
from app.services.mpesa import initiate_stk_push


admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.before_request
@login_required
def require_admin():
    """Only allow users with role 'admin'."""
    if current_user.role != 'admin':
        flash('Access denied. Admin only.', 'danger')
        return redirect(url_for('main.index'))


class DeleteForm(FlaskForm):
    submit = SubmitField('Delete')


class ActionForm(FlaskForm):
    submit = SubmitField('Submit')


class SubscriptionEditForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    phone = StringField('Phone', validators=[DataRequired(), Length(max=20)])
    location = StringField('Location', validators=[DataRequired(), Length(max=200)])
    preferred_delivery_day = SelectField('Preferred Delivery Day', choices=[
        ('Monday', 'Monday'),
        ('Tuesday', 'Tuesday'),
        ('Wednesday', 'Wednesday'),
        ('Thursday', 'Thursday'),
        ('Friday', 'Friday'),
    ])
    submit = SubmitField('Save')


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


def _dashboard_base_query(now):
    display_status_expr = case(
        (Subscription.current_period_end > now, 'active'),
        (Subscription.status == SubscriptionStatus.PENDING.value, 'pending'),
        (Subscription.status.in_([SubscriptionStatus.FAILED.value, SubscriptionStatus.CANCELLED.value]), 'failed'),
        else_='expired'
    )

    amount_paid_subq = db.session.query(
        Payment.subscription_id.label('sub_id'),
        func.coalesce(
            func.sum(case((Payment.status == PaymentStatus.COMPLETED.value, Payment.amount), else_=0.0)),
            0.0
        ).label('amount_paid_total')
    ).group_by(Payment.subscription_id).subquery()

    latest_payment_time_subq = db.session.query(
        Payment.subscription_id.label('sub_id'),
        func.max(Payment.payment_date).label('last_payment_date')
    ).group_by(Payment.subscription_id).subquery()

    latest_payment_subq = db.session.query(
        Payment.subscription_id.label('sub_id'),
        Payment.payment_date.label('last_payment_date'),
        Payment.payment_method.label('payment_method'),
        Payment.checkout_request_id.label('checkout_request_id'),
        Payment.mpesa_receipt.label('mpesa_receipt'),
        Payment.status.label('payment_status'),
    ).join(
        latest_payment_time_subq,
        and_(
            Payment.subscription_id == latest_payment_time_subq.c.sub_id,
            Payment.payment_date == latest_payment_time_subq.c.last_payment_date
        )
    ).subquery()

    delivery_count_subq = db.session.query(
        Delivery.subscription_id.label('sub_id'),
        func.coalesce(
            func.sum(case((Delivery.status == DeliveryStatus.DELIVERED.value, 1), else_=0)),
            0
        ).label('delivery_count')
    ).group_by(Delivery.subscription_id).subquery()

    duplicate_active_phone_subq = db.session.query(
        Subscription.phone_normalized.label('phone_normalized')
    ).filter(
        Subscription.current_period_end > now
    ).group_by(
        Subscription.phone_normalized
    ).having(
        func.count(Subscription.id) > 1
    ).subquery()

    base_query = db.session.query(
        Subscription,
        SubscriptionPlan.name.label('plan_name'),
        display_status_expr.label('display_status'),
        func.coalesce(amount_paid_subq.c.amount_paid_total, 0.0).label('amount_paid_total'),
        latest_payment_subq.c.payment_method.label('payment_method'),
        latest_payment_subq.c.checkout_request_id.label('checkout_request_id'),
        latest_payment_subq.c.mpesa_receipt.label('mpesa_receipt'),
        latest_payment_subq.c.last_payment_date.label('last_payment_date'),
        latest_payment_subq.c.payment_status.label('last_payment_status'),
        func.coalesce(delivery_count_subq.c.delivery_count, 0).label('delivery_count'),
        case((duplicate_active_phone_subq.c.phone_normalized.isnot(None), True), else_=False).label('is_duplicate_active_phone')
    ).join(
        SubscriptionPlan, Subscription.plan_id == SubscriptionPlan.id
    ).outerjoin(
        amount_paid_subq, amount_paid_subq.c.sub_id == Subscription.id
    ).outerjoin(
        latest_payment_subq, latest_payment_subq.c.sub_id == Subscription.id
    ).outerjoin(
        delivery_count_subq, delivery_count_subq.c.sub_id == Subscription.id
    ).outerjoin(
        duplicate_active_phone_subq, duplicate_active_phone_subq.c.phone_normalized == Subscription.phone_normalized
    )
    return base_query, display_status_expr, amount_paid_subq


@admin_bp.route('/dashboard')
def dashboard():
    now = datetime.utcnow()

    status_filter = (request.args.get('status') or '').strip().lower()
    plan_id_filter = request.args.get('plan_id', type=int)
    phone_filter = (request.args.get('phone') or '').strip()
    expiry_filter = (request.args.get('expiry') or '').strip().lower()
    sort_by = (request.args.get('sort_by') or 'created').strip().lower()
    sort_dir = (request.args.get('sort_dir') or 'desc').strip().lower()
    page = max(1, request.args.get('page', default=1, type=int))
    per_page = min(100, max(10, request.args.get('per_page', default=25, type=int)))

    base_query, display_status_expr, amount_paid_subq = _dashboard_base_query(now)

    if status_filter in {'active', 'pending', 'failed', 'expired'}:
        base_query = base_query.filter(display_status_expr == status_filter)

    if plan_id_filter:
        base_query = base_query.filter(Subscription.plan_id == plan_id_filter)

    if phone_filter:
        normalized = Subscription.normalize_phone(phone_filter)
        base_query = base_query.filter(
            (Subscription.phone.ilike(f'%{phone_filter}%')) |
            (Subscription.phone_normalized == normalized)
        )

    if expiry_filter == 'overdue':
        base_query = base_query.filter(Subscription.current_period_end < now)
    elif expiry_filter == '0_7':
        base_query = base_query.filter(
            Subscription.current_period_end >= now,
            Subscription.current_period_end <= now + timedelta(days=7)
        )
    elif expiry_filter == '8_30':
        base_query = base_query.filter(
            Subscription.current_period_end > now + timedelta(days=7),
            Subscription.current_period_end <= now + timedelta(days=30)
        )
    elif expiry_filter == 'gt_30':
        base_query = base_query.filter(Subscription.current_period_end > now + timedelta(days=30))

    sort_col = Subscription.start_date
    if sort_by == 'next_delivery':
        sort_col = Subscription.next_delivery_date
    elif sort_by == 'amount_paid':
        sort_col = func.coalesce(amount_paid_subq.c.amount_paid_total, 0.0)

    if sort_dir == 'asc':
        base_query = base_query.order_by(sort_col.asc(), Subscription.id.asc())
    else:
        base_query = base_query.order_by(sort_col.desc(), Subscription.id.desc())

    total_count = base_query.count()
    rows = base_query.offset((page - 1) * per_page).limit(per_page).all()

    subscriptions = []
    for row in rows:
        sub = row.Subscription
        days_until_expiry = (sub.current_period_end.date() - now.date()).days if sub.current_period_end else None
        payment_reference = row.mpesa_receipt or row.checkout_request_id or '-'

        subscriptions.append({
            'id': sub.id,
            'name': sub.name,
            'phone': sub.phone,
            'location': sub.location,
            'plan_name': row.plan_name,
            'display_status': row.display_status,
            'next_delivery_date': sub.next_delivery_date,
            'current_period_end': sub.current_period_end,
            'days_until_expiry': days_until_expiry,
            'amount_paid_total': float(row.amount_paid_total or 0.0),
            'payment_method': row.payment_method or '-',
            'payment_reference': payment_reference,
            'checkout_request_id': row.checkout_request_id,
            'last_payment_date': row.last_payment_date,
            'delivery_count': int(row.delivery_count or 0),
            'trays_remaining': int(sub.trays_remaining or 0),
            'is_duplicate_active_phone': bool(row.is_duplicate_active_phone),
        })

    active = Subscription.query.filter(Subscription.current_period_end > now).count()
    pending = Subscription.query.filter_by(status=SubscriptionStatus.PENDING.value).count()
    delete_form = DeleteForm()
    action_form = ActionForm()
    plan_options = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.name.asc()).all()
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return render_template(
        'admin/dashboard.html',
        subscriptions=subscriptions,
        active=active,
        pending=pending,
        delete_form=delete_form,
        action_form=action_form,
        plans=plan_options,
        selected_filters={
            'status': status_filter,
            'plan_id': plan_id_filter,
            'phone': phone_filter,
            'expiry': expiry_filter,
        },
        sort_state={'sort_by': sort_by, 'sort_dir': sort_dir},
        pagination={
            'page': page,
            'per_page': per_page,
            'total': total_count,
            'total_pages': total_pages,
            'has_prev': page > 1,
            'has_next': page < total_pages,
        }
    )


@admin_bp.route('/subscriptions/edit/<int:sub_id>', methods=['GET', 'POST'])
def edit_subscription(sub_id):
    sub = Subscription.query.get_or_404(sub_id)
    form = SubscriptionEditForm(obj=sub)

    if form.validate_on_submit():
        sub.name = form.name.data.strip()
        sub.phone = form.phone.data.strip()
        sub.phone_normalized = Subscription.normalize_phone(sub.phone)
        sub.location = form.location.data.strip()
        sub.preferred_delivery_day = form.preferred_delivery_day.data
        db.session.commit()
        flash(f'Subscription #{sub.id} updated successfully.', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/edit_subscription.html', form=form, subscription=sub)


@admin_bp.route('/subscriptions/cancel/<int:sub_id>', methods=['POST'])
def cancel_subscription(sub_id):
    form = ActionForm()
    if not form.validate_on_submit():
        flash("Bad request (CSRF validation failed).", "danger")
        return redirect(url_for('admin.dashboard'))

    sub = Subscription.query.get_or_404(sub_id)
    sub.status = SubscriptionStatus.CANCELLED.value
    sub.current_period_end = datetime.utcnow()
    db.session.commit()
    flash(f'Subscription #{sub.id} cancelled.', 'warning')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/subscriptions/retry-payment/<int:sub_id>', methods=['POST'])
def retry_payment(sub_id):
    form = ActionForm()
    if not form.validate_on_submit():
        flash("Bad request (CSRF validation failed).", "danger")
        return redirect(url_for('admin.dashboard'))

    sub = Subscription.query.get_or_404(sub_id)
    reference_id = f"NESTGOLD-RETRY-{sub.id}-{int(datetime.utcnow().timestamp())}"
    phone_mpesa = Subscription.normalize_phone(sub.phone)

    checkout_id, error = initiate_stk_push(
        phone_mpesa=phone_mpesa,
        amount_kes=sub.plan.price_per_month,
        reference_id=reference_id,
        customer_name=sub.name,
        description=f"{sub.plan.name} subscription renewal - {sub.name}",
    )

    if checkout_id:
        sub.mark_pending(checkout_request_id=checkout_id)
        db.session.commit()
        flash(f"Retry STK push sent to {sub.phone}.", "info")
    else:
        sub.mark_payment_failed(result_desc=error)
        db.session.commit()
        flash(f"Retry payment failed to start: {error}", "danger")

    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/plans')
def plans():
    plans_list = SubscriptionPlan.query.filter_by(is_active=True).all()
    delete_form = DeleteForm()
    return render_template('admin/plans.html', plans=plans_list, delete_form=delete_form)


@admin_bp.route('/plans/add', methods=['GET', 'POST'])
def add_plan():
    form = PlanForm()
    if form.validate_on_submit():
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
            is_active=True
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
