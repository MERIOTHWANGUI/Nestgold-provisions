# app/routes/payments.py
from flask import Blueprint, request, jsonify, session, redirect, url_for, flash
from app.models import db, Subscription, Payment
from app.services.sms import send_admin_sms, send_customer_confirmation
from datetime import datetime
from app.models import db, User, Subscription  # etc.

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')

@payments_bp.route('/callback', methods=['POST'])
def callback():
    data = request.get_json(force=True)
    print("MPESA CALLBACK RECEIVED:", data)

    try:
        stk = data['Body']['stkCallback']
        checkout_id = stk['CheckoutRequestID']
        result_code = stk['ResultCode']

        # Find pending subscription by checkout_request_id (from session or DB)
        sub = Subscription.query.filter_by(checkout_request_id=checkout_id).first()

        if sub:
            if result_code == 0:
                # Payment success
                sub.status = "Active"
                sub.last_payment_date = datetime.utcnow()
                sub.checkout_request_id = checkout_id  # ensure it's saved

                # Save payment record
                payment = Payment(
                    subscription_id=sub.id,
                    amount=sub.plan.price_per_month,
                    status="Completed",
                    payment_date=datetime.utcnow(),
                    checkout_request_id=checkout_id,
                    mpesa_receipt=stk.get('CallbackMetadata', {}).get('Item', [{}])[1].get('Value')  # receipt number
                )
                db.session.add(payment)

                db.session.commit()
                print(f"Subscription {sub.id} activated, Payment saved")

                # Send SMS
                send_admin_sms(sub)
                send_customer_confirmation(sub)

                flash("Payment successful! Your subscription is active.", 'success')
            else:
                sub.status = "Failed"
                db.session.commit()
                flash("Payment failed. Please try again.", 'danger')

        else:
            print("No matching subscription found for checkout_id:", checkout_id)

        return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200

    except Exception as e:
        print("Callback error:", str(e))
        return jsonify({"ResultCode": 1, "ResultDesc": "Error"}), 200