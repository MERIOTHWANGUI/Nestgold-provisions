from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
from app.services.mpesa import initiate_stk_push
from app.models import db, Subscription, SubscriptionPlan
from .forms import SubscriptionForm

sub_bp = Blueprint('subscription', __name__, url_prefix='/subscribe')


@sub_bp.route('/<int:plan_id>', methods=['GET', 'POST'])
def new(plan_id):
    plan = SubscriptionPlan.query.get_or_404(plan_id)
    form = SubscriptionForm()

    if form.validate_on_submit():
        name = form.name.data.strip()
        phone = form.phone.data.strip()
        location = form.location.data.strip()
        delivery_day = form.delivery_day.data.strip()

        # Normalize phone for M-Pesa
        if phone.startswith('0'):
            phone_mpesa = '254' + phone[1:]
        elif phone.startswith('+254'):
            phone_mpesa = phone[1:]
        else:
            phone_mpesa = phone

        # Create subscription
        sub = Subscription(
            plan_id=plan.id,
            phone=phone,
            name=name,
            location=location,
            preferred_delivery_day=delivery_day,
            status="Pending",
            start_date=datetime.utcnow(),
            next_delivery_date=datetime.utcnow()
        )
        db.session.add(sub)
        db.session.commit()

        reference_id = f"NESTGOLD-{sub.id}-{int(datetime.utcnow().timestamp())}"

        checkout_id, error = initiate_stk_push(
            phone_mpesa=phone_mpesa,
            amount_kes=plan.price_per_month,
            reference_id=reference_id,
            customer_name=name,
            description=f"{plan.name} subscription - {name}"
        )

        if checkout_id:
            sub.checkout_request_id = checkout_id
            db.session.commit()
            flash(f'Payment prompt sent to {phone}. Complete on your phone.', 'info')
            return redirect(url_for('subscription.pending', checkout_id=checkout_id))
        else:
            flash(f'Payment start failed: {error}', 'danger')
            db.session.delete(sub)
            db.session.commit()
            return redirect(url_for('subscription.new', plan_id=plan.id))

    return render_template('public/subscribe.html', plan=plan, form=form)



@sub_bp.route('/pending/<checkout_id>')
def pending(checkout_id):
    return render_template('public/pending.html', checkout_id=checkout_id)


@sub_bp.route('/check/<checkout_id>')
def check(checkout_id):
    sub = Subscription.query.filter_by(checkout_request_id=checkout_id).first()
    if not sub:
        return jsonify({'status': 'not_found'})

    status = (sub.status or '').lower()
    if status == 'active':
        return jsonify({'status': 'completed'})
    if status in {'failed', 'cancelled', 'canceled'}:
        return jsonify({'status': 'failed'})
    return jsonify({'status': 'pending'})


@sub_bp.route('/success')
def success():
    return render_template('public/success.html')


@sub_bp.route('/failed')
def failed():
    return render_template('public/failed.html')
