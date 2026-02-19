from datetime import datetime, timedelta
import secrets

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, url_for

from app.services.mpesa import get_manual_payment_instructions
from app.models import (
    ManualPaymentStatus,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    db,
)
from .forms import SubscriptionForm

sub_bp = Blueprint('subscription', __name__, url_prefix='/subscribe')


WEEKDAY_MAP = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


def _next_delivery_datetime(preferred_day, now=None):
    """Calculate nearest upcoming delivery date for logistics scheduling only."""
    now = now or datetime.utcnow()
    target = WEEKDAY_MAP.get(preferred_day, now.weekday())
    days_ahead = (target - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return now + timedelta(days=days_ahead)


def _new_tracking_code():
    return secrets.token_urlsafe(8).replace("-", "").replace("_", "").upper()


@sub_bp.route('/<int:plan_id>', methods=['GET', 'POST'])
def new(plan_id):
    plan = SubscriptionPlan.query.get_or_404(plan_id)
    form = SubscriptionForm()

    if form.validate_on_submit():
        name = form.name.data.strip()
        phone = form.phone.data.strip()
        location = form.location.data.strip()
        delivery_day = form.delivery_day.data.strip()

        now = datetime.utcnow()
        phone_normalized = Subscription.normalize_phone(phone)
        phone_mpesa = phone_normalized

        # Reuse same row forever for a (plan, phone) pair to avoid duplicates.
        sub = Subscription.query.filter_by(
            plan_id=plan.id,
            phone_normalized=phone_normalized
        ).first()

        if sub:
            sub.phone = phone
            sub.phone_normalized = phone_normalized
            sub.name = name
            sub.location = location
            sub.preferred_delivery_day = delivery_day
            sub.next_delivery_date = _next_delivery_datetime(delivery_day, now=now)
            sub.mark_pending()
            sub.delivery_status = "Pending"
        else:
            sub = Subscription(
                plan_id=plan.id,
                phone=phone,
                phone_normalized=phone_normalized,
                name=name,
                location=location,
                preferred_delivery_day=delivery_day,
                status=SubscriptionStatus.PENDING.value,
                start_date=now,
                current_period_end=now,
                next_delivery_date=_next_delivery_datetime(delivery_day, now=now),
                delivery_status="Pending",
            )
            db.session.add(sub)

        db.session.commit()

        reference_id = f"NESTGOLD-{sub.id}-{int(datetime.utcnow().timestamp())}"
        tracking_code = _new_tracking_code()
        while Payment.query.filter_by(tracking_code=tracking_code).first():
            tracking_code = _new_tracking_code()

        payment = Payment(
            subscription_id=sub.id,
            amount=plan.price_per_month,
            checkout_request_id=reference_id,
            reference_id=reference_id,
            customer_name=name,
            customer_phone=phone_mpesa,
            description=f"{plan.name} subscription - {name}",
            status=PaymentStatus.PENDING.value,
            manual_payment_status=ManualPaymentStatus.PENDING.value,
            payment_method="Manual",
            tracking_code=tracking_code,
            payment_date=now,
        )
        db.session.add(payment)
        sub.checkout_request_id = reference_id
        db.session.commit()

        instructions = get_manual_payment_instructions(
            reference_id=reference_id,
            amount_kes=plan.price_per_month,
            customer_name=name,
        )
        flash("Payment request submitted. Follow the manual instructions below.", "info")
        return render_template(
            "public/payment_instructions.html",
            payment=payment,
            subscription=sub,
            instructions=instructions,
            tracking_url=url_for("payments.track_payment", tracking_code=tracking_code),
        )

    return render_template('public/subscribe.html', plan=plan, form=form)



@sub_bp.route('/pending/<checkout_id>')
def pending(checkout_id):
    return render_template('public/pending.html', checkout_id=checkout_id)


@sub_bp.route('/check/<checkout_id>')
def check(checkout_id):
    sub = Subscription.query.filter_by(checkout_request_id=checkout_id).first()
    payment = Payment.query.filter_by(checkout_request_id=checkout_id).first()

    if payment and payment.status == PaymentStatus.COMPLETED.value and sub and sub.is_access_active:
        return jsonify({'status': 'completed'})

    if payment and payment.status in {PaymentStatus.FAILED.value, PaymentStatus.CANCELLED.value}:
        return jsonify({'status': 'failed'})

    if sub and sub.status in {SubscriptionStatus.FAILED.value, SubscriptionStatus.CANCELLED.value}:
        return jsonify({'status': 'failed'})

    if not sub and not payment:
        return jsonify({'status': 'not_found'})

    return jsonify({'status': 'pending'})


@sub_bp.route('/success')
def success():
    checkout_id = (request.args.get('checkout_id') or '').strip()
    payment, sub = _resolve_success_records(checkout_id)

    error_message = None
    if not checkout_id:
        error_message = "Missing payment reference. Add checkout_id to view full receipt details."
    elif not payment and not sub:
        error_message = "No payment/subscription found for this checkout reference."

    return render_template(
        'public/success.html',
        checkout_id=checkout_id,
        payment=payment,
        subscription=sub,
        error_message=error_message,
        can_download_receipt=bool(checkout_id and payment and sub),
    )


def _resolve_success_records(checkout_id):
    """Resolve payment/subscription deterministically from stored records only."""
    payment = None
    sub = None

    if checkout_id:
        payment = Payment.query.filter_by(checkout_request_id=checkout_id).first()
        if payment and payment.subscription_id:
            sub = Subscription.query.get(payment.subscription_id)
        if not sub:
            sub = Subscription.query.filter_by(checkout_request_id=checkout_id).first()

    return payment, sub


@sub_bp.route('/success/receipt')
def download_receipt():
    checkout_id = (request.args.get('checkout_id') or '').strip()
    payment, sub = _resolve_success_records(checkout_id)

    if not checkout_id or not payment or not sub:
        return Response(
            "Receipt not found. Provide a valid checkout_id tied to a completed payment/subscription.",
            status=404,
            mimetype='text/plain'
        )

    reference = payment.mpesa_receipt or payment.checkout_request_id or checkout_id
    paid_at = payment.payment_date.strftime('%Y-%m-%d %H:%M:%S') if payment.payment_date else '-'
    period_start = sub.start_date.strftime('%Y-%m-%d') if sub.start_date else '-'
    period_end = sub.current_period_end.strftime('%Y-%m-%d') if sub.current_period_end else '-'

    # Plain-text receipt generated only from persisted DB records (no external API calls).
    receipt_lines = [
        "NESTGOLD PROVISIONS - PAYMENT RECEIPT",
        "====================================",
        f"Checkout ID: {checkout_id}",
        f"Customer Name: {sub.name}",
        f"Customer Phone: {sub.phone}",
        f"Plan: {sub.plan.name if sub.plan else '-'}",
        f"Billing Period: {period_start} to {period_end}",
        f"Amount Paid (KES): {payment.amount:.2f}",
        f"Payment Reference: {reference}",
        f"Payment Method: {payment.payment_method or 'M-Pesa'}",
        f"Payment Date/Time: {paid_at}",
        "",
        "Thank you for your subscription.",
    ]
    body = "\n".join(receipt_lines)

    response = Response(body, mimetype='text/plain; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename="receipt_{checkout_id}.txt"'
    return response


@sub_bp.route('/failed')
def failed():
    return render_template('public/failed.html')
