# app/routes/payments.py
from flask import Blueprint, request, jsonify
from app import csrf
from app.models import db, Subscription, Payment
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
        stk = data['Body']['stkCallback']
        checkout_id = stk['CheckoutRequestID']
        result_code = stk['ResultCode']
        result_code_int = int(result_code)

        # Find subscription by checkout_request_id
        sub = Subscription.query.filter_by(checkout_request_id=checkout_id).first()

        if sub:
            if result_code_int == 0:
                # Payment success
                sub.status = "Active"

                receipt_number = None
                callback_items = stk.get('CallbackMetadata', {}).get('Item', [])
                for item in callback_items:
                    if item.get('Name') == 'MpesaReceiptNumber':
                        receipt_number = item.get('Value')
                        break

                existing_payment = Payment.query.filter_by(checkout_request_id=checkout_id).first()
                if not existing_payment:
                    payment = Payment(
                        subscription_id=sub.id,
                        amount=sub.plan.price_per_month,
                        status="Completed",
                        payment_date=datetime.utcnow(),
                        checkout_request_id=checkout_id,
                        mpesa_receipt=receipt_number
                    )
                    db.session.add(payment)

                db.session.commit()
                print(f"Subscription {sub.id} activated, Payment saved")

                # Send SMS
                send_admin_sms(sub)
                send_customer_confirmation(sub)
            else:
                sub.status = "Failed"
                db.session.commit()

        else:
            print("No matching subscription found for checkout_id:", checkout_id)

        return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200

    except (KeyError, TypeError, ValueError, SQLAlchemyError) as e:
        db.session.rollback()
        print("Callback error:", str(e))
        return jsonify({"ResultCode": 1, "ResultDesc": "Error"}), 200
