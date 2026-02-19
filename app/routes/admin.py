# app/routes/admin.py
from datetime import datetime, timedelta

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from markupsafe import escape
from sqlalchemy import and_, case, func, or_
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
    ManualPaymentStatus,
    Payment,
    PaymentConfig,
    PaymentStatus,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    db,
)
from app.routes.forms import ConfirmManualPaymentForm, DeliveryUpdateForm, PaymentConfigForm


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


def _escape_pdf(text):
    return (text or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _simple_pdf(lines):
    text_ops = ["BT", "/F1 12 Tf", "50 790 Td", "14 TL"]
    for line in lines:
        text_ops.append(f"({_escape_pdf(line)}) Tj")
        text_ops.append("T*")
    text_ops.append("ET")
    stream = "\n".join(text_ops).encode("latin-1", "replace")

    objs = []
    objs.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objs.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
    objs.append(
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >> endobj\n"
    )
    objs.append(f"4 0 obj << /Length {len(stream)} >> stream\n".encode("ascii") + stream + b"\nendstream endobj\n")
    objs.append(b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")

    out = b"%PDF-1.4\n"
    offsets = [0]
    for obj in objs:
        offsets.append(len(out))
        out += obj
    xref_pos = len(out)
    out += f"xref\n0 {len(offsets)}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode("ascii")
    return out


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

    has_history = Payment.query.filter_by(subscription_id=subscription.id).first() or Delivery.query.filter_by(subscription_id=subscription.id).first()
    if has_history:
        subscription.status = SubscriptionStatus.CANCELLED.value
        subscription.current_period_end = datetime.utcnow()
        subscription.delivery_status = "Cancelled"
        db.session.commit()
        flash(
            f'Subscription #{sub_id} has payment/delivery history. It was cancelled instead of deleted.',
            'warning'
        )
        return redirect(url_for('admin.dashboard'))

    try:
        db.session.delete(subscription)
        db.session.commit()
        flash(f'Subscription #{sub_id} deleted successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('Unable to delete subscription right now.', 'warning')

    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/payments')
def payments():
    payment_status_filter = (request.args.get('payment_status') or '').strip()
    has_subscription_filter = (request.args.get('has_subscription') or '').strip().lower()
    query_text = (request.args.get('q') or '').strip()

    payments_query = Payment.query
    if payment_status_filter in {ManualPaymentStatus.PENDING.value, ManualPaymentStatus.CONFIRMED.value}:
        payments_query = payments_query.filter(Payment.payment_status == payment_status_filter)

    if has_subscription_filter == 'yes':
        payments_query = payments_query.filter(Payment.subscription_id.isnot(None))
    elif has_subscription_filter == 'no':
        payments_query = payments_query.filter(Payment.subscription_id.is_(None))

    if query_text:
        like = f"%{query_text}%"
        payments_query = payments_query.filter(or_(
            Payment.customer_name.ilike(like),
            Payment.customer_phone.ilike(like),
            Payment.reference_id.ilike(like),
            Payment.tracking_code.ilike(like),
            Payment.checkout_request_id.ilike(like),
            Payment.admin_transaction_reference.ilike(like),
        ))

    payments_list = payments_query.order_by(Payment.payment_date.desc(), Payment.id.desc()).all()
    confirm_form = ConfirmManualPaymentForm()
    delivery_form = DeliveryUpdateForm()
    config = PaymentConfig.query.order_by(PaymentConfig.id.desc()).first()
    if not config:
        config = PaymentConfig()
        db.session.add(config)
        db.session.commit()
    config_form = PaymentConfigForm(obj=config)
    delete_form = DeleteForm()

    total_pending = Payment.query.filter_by(payment_status=ManualPaymentStatus.PENDING.value).count()
    total_confirmed = Payment.query.filter_by(payment_status=ManualPaymentStatus.CONFIRMED.value).count()
    trays_delivered = db.session.query(func.count(Delivery.id)).filter(
        Delivery.status == DeliveryStatus.DELIVERED.value
    ).scalar() or 0
    trays_remaining_total = db.session.query(func.coalesce(func.sum(Subscription.trays_remaining), 0)).scalar() or 0

    return render_template(
        'admin/payments.html',
        payments=payments_list,
        confirm_form=confirm_form,
        delivery_form=delivery_form,
        config_form=config_form,
        payment_config=config,
        summary={
            'pending': total_pending,
            'confirmed': total_confirmed,
            'trays_delivered': trays_delivered,
            'trays_remaining': trays_remaining_total,
        },
        delete_form=delete_form,
        selected_filters={
            'payment_status': payment_status_filter,
            'has_subscription': has_subscription_filter,
            'q': query_text,
        },
    )


@admin_bp.route('/confirm/<int:payment_id>', methods=['POST'])
def confirm_payment(payment_id):
    form = ConfirmManualPaymentForm()
    if not form.validate_on_submit():
        flash("Bad request (CSRF validation failed).", "danger")
        return redirect(url_for('admin.payments'))

    payment = Payment.query.get_or_404(payment_id)
    now = datetime.utcnow()
    first_success = payment.status != PaymentStatus.COMPLETED.value

    payment.status = PaymentStatus.COMPLETED.value
    payment.payment_status = ManualPaymentStatus.CONFIRMED.value
    payment.manual_payment_status = ManualPaymentStatus.CONFIRMED.value
    payment.payment_method = 'Manual'
    payment.payment_date = now
    payment.instruction_channel = form.channel.data or None
    payment.admin_transaction_reference = (form.transaction_reference.data or '').strip() or None
    payment.admin_notes = (form.admin_notes.data or '').strip() or None

    sub = payment.subscription
    if sub and first_success:
        sub.apply_successful_payment(now=now)
        monthly_trays = sub.plan.trays_per_week * 4
        sub.trays_allocated_total = (sub.trays_allocated_total or 0) + monthly_trays
        sub.trays_remaining = (sub.trays_remaining or 0) + monthly_trays
        sub.delivery_status = "Pending"

    db.session.commit()
    flash(f'Payment #{payment.id} confirmed successfully.', 'success')
    return redirect(url_for('admin.payments'))


@admin_bp.route('/deliver/<int:subscription_id>', methods=['POST'])
def mark_delivery_done(subscription_id):
    form = DeliveryUpdateForm()
    if not form.validate_on_submit():
        flash("Bad request (CSRF validation failed).", "danger")
        return redirect(url_for('admin.payments'))

    sub = Subscription.query.get_or_404(subscription_id)
    if sub.trays_remaining <= 0 and form.status.data == DeliveryStatus.DELIVERED.value:
        sub.delivery_status = "Completed"
        db.session.commit()
        flash(f'Subscription #{sub.id} has no trays remaining.', 'warning')
        return redirect(url_for('admin.payments'))

    status = form.status.data
    delivered_before = sub.trays_allocated_total - sub.trays_remaining
    if status == DeliveryStatus.DELIVERED.value and sub.trays_remaining > 0:
        sub.trays_remaining -= 1

    delivery = Delivery(
        subscription_id=sub.id,
        scheduled_date=datetime.combine(form.delivery_date.data, datetime.utcnow().time()),
        status=status,
        notes=(form.notes.data or '').strip() or f"Delivery update saved (tray #{delivered_before + 1}).",
    )
    db.session.add(delivery)

    if sub.trays_remaining == 0:
        sub.delivery_status = "Completed"
    else:
        sub.delivery_status = "In Progress"

    db.session.commit()
    flash(f'Delivery recorded for subscription #{sub.id}.', 'success')
    return redirect(url_for('admin.payments'))


@admin_bp.route('/payments/config', methods=['POST'])
def save_payment_config():
    config = PaymentConfig.query.order_by(PaymentConfig.id.desc()).first()
    if not config:
        config = PaymentConfig()
        db.session.add(config)
    form = PaymentConfigForm()
    if not form.validate_on_submit():
        flash("Invalid payment details form.", "danger")
        return redirect(url_for('admin.payments'))

    config.mpesa_paybill = form.mpesa_paybill.data.strip()
    config.bank_name = form.bank_name.data.strip()
    config.bank_account_name = form.bank_account_name.data.strip()
    config.bank_account_number = form.bank_account_number.data.strip()
    config.instructions_footer = (form.instructions_footer.data or '').strip() or None
    db.session.commit()
    flash("Payment details updated.", "success")
    return redirect(url_for('admin.payments'))


@admin_bp.route('/payments/<int:payment_id>/receipt')
def download_payment_receipt(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if payment.payment_status != ManualPaymentStatus.CONFIRMED.value:
        flash("Receipt is available only for confirmed payments.", "warning")
        return redirect(url_for('admin.payments'))

    sub = payment.subscription
    ref = payment.admin_transaction_reference or payment.reference_id or payment.checkout_request_id or "-"
    paid_at = payment.payment_date.strftime("%Y-%m-%d %H:%M:%S") if payment.payment_date else "-"
    lines = [
        "NESTGOLD PROVISIONS - RECEIPT",
        "----------------------------------------",
        f"Payment ID: {payment.id}",
        f"Reference: {ref}",
        f"Customer: {payment.customer_name or (sub.name if sub else '-')}",
        f"Phone: {payment.customer_phone or (sub.phone if sub else '-')}",
        f"Amount (KES): {payment.amount:.2f}",
        f"Payment Status: {payment.payment_status}",
        f"Confirmed At: {paid_at}",
        f"Plan: {(sub.plan.name if sub and sub.plan else '-')}",
        f"Trays Remaining: {(sub.trays_remaining if sub else 0)}",
    ]
    response = Response(_simple_pdf(lines), mimetype="application/pdf")
    response.headers["Content-Disposition"] = f'attachment; filename="admin_receipt_{payment.id}.pdf"'
    return response


@admin_bp.route('/payments/delete/<int:payment_id>', methods=['POST'])
def delete_payment(payment_id):
    form = DeleteForm()
    if not form.validate_on_submit():
        flash("Bad request (CSRF validation failed).", "danger")
        return redirect(url_for('admin.payments'))

    payment = Payment.query.get_or_404(payment_id)
    sub = payment.subscription

    if sub and payment.payment_status == ManualPaymentStatus.CONFIRMED.value and sub.plan:
        monthly_trays = max(0, int(sub.plan.trays_per_week or 0) * 4)
        sub.trays_allocated_total = max(0, int(sub.trays_allocated_total or 0) - monthly_trays)
        sub.trays_remaining = max(0, int(sub.trays_remaining or 0) - monthly_trays)

    db.session.delete(payment)
    db.session.flush()

    if sub:
        remaining = Payment.query.filter_by(subscription_id=sub.id).count()
        delivery_rows = Delivery.query.filter_by(subscription_id=sub.id).count()
        confirmed_left = Payment.query.filter_by(
            subscription_id=sub.id,
            payment_status=ManualPaymentStatus.CONFIRMED.value
        ).count()

        if confirmed_left == 0:
            sub.status = SubscriptionStatus.PENDING.value
            sub.current_period_end = datetime.utcnow()
            sub.delivery_status = "Pending"

        if remaining == 0 and delivery_rows == 0 and sub.status == SubscriptionStatus.PENDING.value:
            db.session.delete(sub)

    db.session.commit()
    flash(f'Payment #{payment_id} deleted successfully.', 'success')
    return redirect(url_for('admin.payments'))
