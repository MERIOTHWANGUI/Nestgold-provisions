# app/routes/payments.py
from flask import Blueprint, request, jsonify
from app import csrf
from app.models import (
    Payment,
    PaymentStatus,
    Subscription,
    db,
)
from app.services.sms import send_admin_sms, send_customer_confirmation
from datetime import datetime
from sqlalchemy.exc import SQLAlchemyError

payments_bp = Blueprint('payments', __name__)

@csrf.exempt
@payments_bp.route('/payments/callback', methods=['POST'])
@payments_bp.route('/mpesa_callback', methods=['POST'])
@payments_bp.route('/callback', methods=['POST'])
def callback():
    data = request.get_json(force=True)
    print("MPESA CALLBACK RECEIVED:", data)

    try:
        stk = (data or {}).get('Body', {}).get('stkCallback', {})
        checkout_id = stk.get('CheckoutRequestID')
        result_code = stk.get('ResultCode')
        result_desc = stk.get('ResultDesc')
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
                payment_method='M-Pesa',
            )
            db.session.add(payment)
        elif sub and payment.subscription_id is None:
            payment.subscription_id = sub.id
            payment.amount = sub.plan.price_per_month

        if result_code_int == 0:
            receipt_number = None
            callback_items = stk.get('CallbackMetadata', {}).get('Item', []) or []
            for item in callback_items:
                if item.get('Name') == 'MpesaReceiptNumber':
                    receipt_number = item.get('Value')
                    break

            first_success = payment.status != PaymentStatus.COMPLETED.value
            payment.status = PaymentStatus.COMPLETED.value
            payment.payment_date = now
            payment.mpesa_receipt = receipt_number
            payment.payment_method = 'M-Pesa'

            if sub and first_success:
                # Idempotent extension: only extend period first time this checkout succeeds.
                sub.apply_successful_payment(now=now)
                monthly_trays = sub.plan.trays_per_week * 4
                sub.trays_allocated_total = (sub.trays_allocated_total or 0) + monthly_trays
                sub.trays_remaining = (sub.trays_remaining or 0) + monthly_trays
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
