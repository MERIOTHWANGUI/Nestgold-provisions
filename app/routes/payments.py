# app/routes/payments.py
from datetime import datetime
import secrets

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from app import csrf
from app.models import (
    Delivery,
    DeliveryStatus,
    ManualPaymentStatus,
    Payment,
    PaymentStatus,
    Subscription,
    db,
)
from app.routes.forms import PaymentRequestForm
from app.services.mpesa import get_manual_payment_instructions
from app.services.sms import send_admin_sms, send_customer_confirmation

payments_bp = Blueprint("payments", __name__)


def _new_tracking_code():
    return secrets.token_urlsafe(8).replace("-", "").replace("_", "").upper()


@payments_bp.route("/payment-request", methods=["GET", "POST"])
def payment_request():
    form = PaymentRequestForm()
    if form.validate_on_submit():
        reference_id = form.reference_id.data.strip().upper()

        if Payment.query.filter_by(reference_id=reference_id).first():
            flash("Reference ID already exists. Please use a unique one.", "warning")
            return redirect(url_for("payments.payment_request"))

        tracking_code = _new_tracking_code()
        while Payment.query.filter_by(tracking_code=tracking_code).first():
            tracking_code = _new_tracking_code()

        phone = Subscription.normalize_phone(form.phone.data.strip())
        now = datetime.utcnow()
        payment = Payment(
            amount=float(form.amount.data),
            reference_id=reference_id,
            customer_name=form.name.data.strip(),
            customer_phone=phone,
            description=(form.description.data or "").strip(),
            payment_method="Manual",
            status=PaymentStatus.PENDING.value,
            manual_payment_status=ManualPaymentStatus.PENDING.value,
            tracking_code=tracking_code,
            payment_date=now,
            checkout_request_id=reference_id,
        )

        db.session.add(payment)
        db.session.commit()

        instructions = get_manual_payment_instructions(
            reference_id=reference_id,
            amount_kes=payment.amount,
            customer_name=payment.customer_name,
        )
        flash("Payment request submitted successfully.", "success")
        return render_template(
            "public/payment_instructions.html",
            payment=payment,
            subscription=None,
            instructions=instructions,
            tracking_url=url_for("payments.track_payment", tracking_code=tracking_code),
        )

    return render_template("public/payment_request.html", form=form)


@payments_bp.route("/track/<tracking_code>")
def track_payment(tracking_code):
    token = (tracking_code or "").strip()
    payment = Payment.query.filter(
        (Payment.tracking_code == token) | (Payment.reference_id == token.upper())
    ).first_or_404()

    subscription = payment.subscription
    deliveries = []
    delivered_count = 0
    if subscription:
        deliveries = (
            Delivery.query.filter_by(subscription_id=subscription.id)
            .order_by(Delivery.scheduled_date.desc())
            .all()
        )
        delivered_count = sum(1 for d in deliveries if d.status == DeliveryStatus.DELIVERED.value)

    return render_template(
        "public/track_payment.html",
        payment=payment,
        subscription=subscription,
        deliveries=deliveries,
        delivered_count=delivered_count,
        trays_total=(subscription.trays_allocated_total if subscription else 0),
    )


@csrf.exempt
@payments_bp.route("/payments/callback", methods=["POST"])
@payments_bp.route("/mpesa_callback", methods=["POST"])
@payments_bp.route("/callback", methods=["POST"])
def callback():
    data = request.get_json(force=True)
    print("MPESA CALLBACK RECEIVED:", data)

    try:
        stk = (data or {}).get("Body", {}).get("stkCallback", {})
        checkout_id = stk.get("CheckoutRequestID")
        result_code = stk.get("ResultCode")
        result_desc = stk.get("ResultDesc")
        try:
            result_code_int = int(result_code)
        except (TypeError, ValueError):
            result_code_int = -1

        if not checkout_id:
            raise ValueError("Missing CheckoutRequestID in callback")

        sub = Subscription.query.filter_by(checkout_request_id=checkout_id).first()
        payment = Payment.query.filter_by(checkout_request_id=checkout_id).first()
        now = datetime.utcnow()

        if not payment:
            payment = Payment(
                subscription_id=sub.id if sub else None,
                amount=sub.plan.price_per_month if sub else 0.0,
                checkout_request_id=checkout_id,
                payment_date=now,
                status=PaymentStatus.PENDING.value,
                payment_method="M-Pesa",
                manual_payment_status=ManualPaymentStatus.PENDING.value,
            )
            db.session.add(payment)
        elif sub and payment.subscription_id is None:
            payment.subscription_id = sub.id
            payment.amount = sub.plan.price_per_month

        if result_code_int == 0:
            receipt_number = None
            callback_items = stk.get("CallbackMetadata", {}).get("Item", []) or []
            for item in callback_items:
                if item.get("Name") == "MpesaReceiptNumber":
                    receipt_number = item.get("Value")
                    break

            first_success = payment.status != PaymentStatus.COMPLETED.value
            payment.status = PaymentStatus.COMPLETED.value
            payment.payment_date = now
            payment.mpesa_receipt = receipt_number
            payment.payment_method = "M-Pesa"
            payment.manual_payment_status = ManualPaymentStatus.CONFIRMED.value

            if sub and first_success:
                sub.apply_successful_payment(now=now)
                monthly_trays = sub.plan.trays_per_week * 4
                sub.trays_allocated_total = (sub.trays_allocated_total or 0) + monthly_trays
                sub.trays_remaining = (sub.trays_remaining or 0) + monthly_trays
                sub.delivery_status = "Pending"
            elif sub:
                sub.sync_status_from_period(now=now)

            db.session.commit()
            if sub and first_success:
                print(f"Subscription {sub.id} extended and payment recorded")
                send_admin_sms(sub)
                send_customer_confirmation(sub)
        else:
            if result_code_int in Subscription.CANCELLED_RESULT_CODES:
                payment.status = PaymentStatus.CANCELLED.value
            else:
                payment.status = PaymentStatus.FAILED.value
            payment.payment_date = now

            if sub:
                sub.mark_payment_failed(result_code=result_code_int, result_desc=result_desc)
            db.session.commit()

        return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200

    except (KeyError, TypeError, ValueError, SQLAlchemyError) as e:
        db.session.rollback()
        print("Callback error:", str(e))
        return jsonify({"ResultCode": 1, "ResultDesc": "Error"}), 200
