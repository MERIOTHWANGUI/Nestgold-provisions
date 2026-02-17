# app/routes/subscription.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime
from app.services.mpesa import initiate_stk_push
from app.models import db, User, Subscription, SubscriptionPlan

sub_bp = Blueprint('subscription', __name__, url_prefix='/subscribe')


@sub_bp.route('/new')
def new():
    plan_id = request.args.get('plan_id')
    if not plan_id:
        flash('Please select a plan first.', 'danger')
        return redirect(url_for('main.index'))

    plan = SubscriptionPlan.query.get(plan_id)
    if not plan:
        flash('Invalid plan selected.', 'danger')
        return redirect(url_for('main.index'))

    return render_template('public/subscribe.html', plan=plan)


@sub_bp.route('/process', methods=['POST'])
def process():
    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    location = request.form.get('location', '').strip()
    delivery_day = request.form.get('delivery_day', '').strip()
    plan_id = request.form.get('plan_id')

    if not all([name, phone, location, delivery_day, plan_id]):
        flash('Please fill all required fields.', 'danger')
        return redirect(url_for('subscription.new', plan_id=plan_id))

    plan = SubscriptionPlan.query.get(plan_id)
    if not plan:
        flash('Invalid plan.', 'danger')
        return redirect(url_for('main.index'))

    # Normalize phone for M-Pesa (2547xx format)
    if phone.startswith('0'):
        phone_mpesa = '254' + phone[1:]
    elif phone.startswith('+254'):
        phone_mpesa = phone[1:]
    else:
        phone_mpesa = phone

    # Step 1: Create pending subscription in DB
    sub = Subscription(
        plan_id=plan.id,
        phone=phone,
        name=name,
        location=location,
        preferred_delivery_day=delivery_day,
        status="Pending",  # Pending until STK push succeeds
        start_date=datetime.utcnow(),
        next_delivery_date=datetime.utcnow()  # you can adjust later
    )
    db.session.add(sub)
    db.session.commit()

    # Step 2: Reference ID for STK push
    reference_id = f"NESTGOLD-{sub.id}-{int(datetime.utcnow().timestamp())}"

    # Step 3: Trigger M-Pesa STK push
    checkout_id, error = initiate_stk_push(
        phone_mpesa=phone_mpesa,
        amount_kes=plan.price_per_month,
        reference_id=reference_id,
        customer_name=name,
        description=f"{plan.name} subscription - {name}"
    )

    if checkout_id:
        # Save checkout_id in subscription
        sub.checkout_request_id = checkout_id
        db.session.commit()

        flash(f'Payment prompt sent to {phone}. Complete on your phone.', 'info')
        return redirect(url_for('subscription.pending', checkout_id=checkout_id))
    else:
        flash(f'Payment start failed: {error}', 'danger')
        # Optional: remove pending subscription since STK failed
        db.session.delete(sub)
        db.session.commit()
        return redirect(url_for('subscription.new', plan_id=plan.id))



@sub_bp.route('/pending/<checkout_id>')
def pending(checkout_id):
    return render_template('public/pending.html', checkout_id=checkout_id)


@sub_bp.route('/check/<checkout_id>')
def check(checkout_id):
    # Placeholder: replace with actual DB check
    return jsonify({'status': 'pending'})
