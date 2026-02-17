# app/models.py

from datetime import datetime
from flask_login import UserMixin
from . import db


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default='customer', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    subscriptions = db.relationship('Subscription', back_populates='user', lazy=True)

    def __repr__(self):
        return f'<User {self.username}>'


class SubscriptionPlan(db.Model):
    __tablename__ = 'subscription_plans'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    trays_per_week = db.Column(db.Integer, nullable=False)
    price_per_month = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # app/models.py, inside SubscriptionPlan
    is_recommended = db.Column(db.Boolean, default=False, nullable=False)
    button_color = db.Column(db.String(20), default='warning')  # bootstrap color: warning, primary, success etc.

    subscriptions = db.relationship('Subscription', back_populates='plan', lazy=True)

    def __repr__(self):
        return f'<SubscriptionPlan {self.name}>'


class Subscription(db.Model):
    __tablename__ = 'subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # <-- make nullable
    plan_id = db.Column(db.Integer, db.ForeignKey('subscription_plans.id'), nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    next_delivery_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False)
    preferred_delivery_day = db.Column(db.String(20), nullable=False)
    checkout_request_id = db.Column(db.String(50))
    phone = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200), nullable=False)

    plan = db.relationship('SubscriptionPlan', back_populates='subscriptions')
    user = db.relationship('User', back_populates='subscriptions')

    def __repr__(self):
        return f'<Subscription {self.id} - {self.status}>'


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscriptions.id'), nullable=False, index=True)

    amount = db.Column(db.Float, nullable=False)
    mpesa_receipt = db.Column(db.String(50))
    status = db.Column(db.String(50), default='Pending', nullable=False)
    payment_date = db.Column(db.DateTime, default=datetime.utcnow)
    checkout_request_id = db.Column(db.String(100), index=True)

    def __repr__(self):
        return f'<Payment {self.id} - {self.status}>'


class Delivery(db.Model):
    __tablename__ = 'deliveries'

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscriptions.id'), nullable=False, index=True)

    scheduled_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(50), default='Scheduled', nullable=False)
    notes = db.Column(db.Text)

    def __repr__(self):
        return f'<Delivery {self.id} - {self.status}>'
