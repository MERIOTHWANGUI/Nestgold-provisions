# app/models.py
import json
import re
from datetime import datetime, timedelta
from enum import Enum

from flask import has_request_context, request
from flask_login import UserMixin, current_user
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from . import db


class SubscriptionStatus(str, Enum):
    PENDING = "Pending"
    ACTIVE = "Active"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    EXPIRED = "Expired"


class PaymentStatus(str, Enum):
    PENDING = "Pending"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class ManualPaymentStatus(str, Enum):
    PENDING = "Pending"
    CONFIRMED = "Confirmed"


class DeliveryStatus(str, Enum):
    SCHEDULED = "Scheduled"
    DELIVERED = "Delivered"
    SKIPPED = "Skipped"
    CANCELLED = "Cancelled"


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default='customer', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    subscriptions = db.relationship('Subscription', back_populates='user', lazy=True)

    @property
    def is_admin(self):
        return self.role == 'admin'

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

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
    is_recommended = db.Column(db.Boolean, default=False, nullable=False)
    button_color = db.Column(db.String(20), default='warning')

    subscriptions = db.relationship('Subscription', back_populates='plan', lazy=True)

    def __repr__(self):
        return f'<SubscriptionPlan {self.name}>'


class Subscription(db.Model):
    __tablename__ = 'subscriptions'
    __table_args__ = (
        db.UniqueConstraint('plan_id', 'phone_normalized', name='uq_subscriptions_plan_phone_normalized'),
        db.Index('ix_subscriptions_current_period_end', 'current_period_end'),
    )

    CANCELLED_RESULT_CODES = {1032, 1037, 1025}

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('subscription_plans.id'), nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    current_period_end = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    next_delivery_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=SubscriptionStatus.PENDING.value)
    preferred_delivery_day = db.Column(db.String(20), nullable=False)
    checkout_request_id = db.Column(db.String(100), index=True)
    phone = db.Column(db.String(20), nullable=False)
    phone_normalized = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    trays_remaining = db.Column(db.Integer, nullable=False, default=0)
    trays_allocated_total = db.Column(db.Integer, nullable=False, default=0)
    delivery_status = db.Column(db.String(30), nullable=False, default="Pending")

    plan = db.relationship('SubscriptionPlan', back_populates='subscriptions')
    user = db.relationship('User', back_populates='subscriptions')
    payments = db.relationship('Payment', back_populates='subscription', lazy=True)
    deliveries = db.relationship('Delivery', backref='subscription', lazy=True)

    @staticmethod
    def normalize_phone(phone):
        """Normalize Kenya phone formats to 2547XXXXXXXX for strict dedupe."""
        digits = re.sub(r'\D+', '', phone or '')
        if digits.startswith('0') and len(digits) == 10:
            return f'254{digits[1:]}'
        if digits.startswith('7') and len(digits) == 9:
            return f'254{digits}'
        if digits.startswith('254') and len(digits) == 12:
            return digits
        return digits

    @property
    def is_access_active(self):
        return bool(self.current_period_end and self.current_period_end > datetime.utcnow())

    @property
    def effective_status(self):
        if self.is_access_active:
            return SubscriptionStatus.ACTIVE.value
        if self.status in {
            SubscriptionStatus.PENDING.value,
            SubscriptionStatus.FAILED.value,
            SubscriptionStatus.CANCELLED.value,
        }:
            return self.status
        return SubscriptionStatus.EXPIRED.value

    def sync_status_from_period(self, now=None):
        now = now or datetime.utcnow()
        if self.status == SubscriptionStatus.PENDING.value:
            return self.status
        if self.current_period_end and self.current_period_end > now:
            self.status = SubscriptionStatus.ACTIVE.value
        elif self.status == SubscriptionStatus.ACTIVE.value:
            self.status = SubscriptionStatus.EXPIRED.value
        return self.status

    def mark_pending(self, checkout_request_id=None):
        self.status = SubscriptionStatus.PENDING.value
        if checkout_request_id:
            self.checkout_request_id = checkout_request_id

    def mark_payment_failed(self, result_code=None, result_desc=None):
        """Map user/system cancellation result codes into Cancelled; others to Failed."""
        code_int = None
        try:
            code_int = int(result_code) if result_code is not None else None
        except (TypeError, ValueError):
            code_int = None

        desc = (result_desc or '').lower()
        if code_int in self.CANCELLED_RESULT_CODES or 'cancel' in desc:
            self.status = SubscriptionStatus.CANCELLED.value
        else:
            self.status = SubscriptionStatus.FAILED.value

    def extend_period(self, days=30, now=None):
        """Access entitlement is period-based, independent of logistics delivery dates."""
        now = now or datetime.utcnow()
        base = self.current_period_end if self.current_period_end and self.current_period_end > now else now
        self.current_period_end = base + timedelta(days=days)
        self.status = SubscriptionStatus.ACTIVE.value

    def apply_successful_payment(self, now=None):
        self.extend_period(days=30, now=now)

    def __repr__(self):
        return f'<Subscription {self.id} - {self.status}>'


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscriptions.id'), nullable=True, index=True)
    amount = db.Column(db.Float, nullable=False)
    mpesa_receipt = db.Column(db.String(50))
    status = db.Column(db.String(50), default=PaymentStatus.PENDING.value, nullable=False)
    payment_status = db.Column(db.String(20), default=ManualPaymentStatus.PENDING.value, nullable=False, index=True)
    payment_date = db.Column(db.DateTime, default=datetime.utcnow)
    checkout_request_id = db.Column(db.String(100), unique=True, index=True)
    payment_method = db.Column(db.String(30), nullable=False, default='M-Pesa')
    manual_payment_status = db.Column(db.String(20), nullable=False, default=ManualPaymentStatus.PENDING.value)
    tracking_code = db.Column(db.String(40), unique=True, index=True)
    reference_id = db.Column(db.String(80), unique=True, index=True)
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    description = db.Column(db.Text)
    instruction_channel = db.Column(db.String(20))
    admin_transaction_reference = db.Column(db.String(100))
    admin_notes = db.Column(db.Text)

    subscription = db.relationship('Subscription', back_populates='payments')

    def __repr__(self):
        return f'<Payment {self.id} - {self.status}>'


class Delivery(db.Model):
    __tablename__ = 'deliveries'

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscriptions.id'), nullable=False, index=True)
    scheduled_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(50), default=DeliveryStatus.SCHEDULED.value, nullable=False)
    notes = db.Column(db.Text)

    def __repr__(self):
        return f'<Delivery {self.id} - {self.status}>'


class PaymentConfig(db.Model):
    __tablename__ = 'payment_configs'

    id = db.Column(db.Integer, primary_key=True)
    mpesa_paybill = db.Column(db.String(40), nullable=False, default='174379')
    mpesa_account_name = db.Column(db.String(100), nullable=False, default='NestGold Provisions')
    mpesa_account_number = db.Column(db.String(80), nullable=False, default='1234567890')
    bank_name = db.Column(db.String(100), nullable=False, default='NestGold Bank')
    bank_account_name = db.Column(db.String(100), nullable=False, default='NestGold Provisions')
    bank_account_number = db.Column(db.String(80), nullable=False, default='1234567890')
    instructions_footer = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<PaymentConfig {self.id}>'




class Feedback(db.Model):
    __tablename__ = "feedback"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<Feedback {self.id} - {self.rating} stars>"
class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(100), nullable=False, index=True)
    row_pk = db.Column(db.String(100), nullable=True, index=True)
    action = db.Column(db.String(20), nullable=False)
    changed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    actor_type = db.Column(db.String(30), nullable=False, default='system')
    actor_id = db.Column(db.String(100), nullable=True)
    request_id = db.Column(db.String(120), nullable=True)
    before_json = db.Column(db.Text, nullable=True)
    after_json = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<AuditLog {self.action} {self.table_name}:{self.row_pk}>'


def _serialize_model(obj):
    mapper = inspect(obj.__class__)
    payload = {}
    for column in mapper.columns:
        val = getattr(obj, column.key)
        if isinstance(val, datetime):
            payload[column.key] = val.isoformat()
        else:
            payload[column.key] = val
    return payload


def _capture_actor():
    actor_type = 'system'
    actor_id = None
    request_id = None

    if has_request_context():
        request_id = request.headers.get('X-Request-ID')
        if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
            actor_type = 'user'
            actor_id = str(current_user.id)

    return actor_type, actor_id, request_id


@event.listens_for(Session, 'before_flush')
def _stash_audit_entries(session, flush_context, instances):
    if session.info.get('audit_disabled'):
        return

    staged = []

    for obj in session.new:
        if isinstance(obj, AuditLog) or not isinstance(obj, db.Model):
            continue
        staged.append({'action': 'insert', 'obj': obj, 'before': None, 'after': _serialize_model(obj)})

    for obj in session.dirty:
        if isinstance(obj, AuditLog) or not isinstance(obj, db.Model):
            continue
        if not session.is_modified(obj, include_collections=False):
            continue
        state = inspect(obj)
        before = {}
        after = {}
        for attr in state.mapper.column_attrs:
            hist = state.attrs[attr.key].history
            if hist.has_changes():
                before[attr.key] = hist.deleted[0] if hist.deleted else None
                after[attr.key] = hist.added[0] if hist.added else getattr(obj, attr.key)
        staged.append({'action': 'update', 'obj': obj, 'before': before, 'after': after})

    for obj in session.deleted:
        if isinstance(obj, AuditLog) or not isinstance(obj, db.Model):
            continue
        staged.append({'action': 'delete', 'obj': obj, 'before': _serialize_model(obj), 'after': None})

    if staged:
        existing = session.info.get('audit_staged', [])
        existing.extend(staged)
        session.info['audit_staged'] = existing


@event.listens_for(Session, 'after_flush_postexec')
def _write_audit_entries(session, flush_context):
    staged = session.info.pop('audit_staged', None)
    if not staged:
        return

    actor_type, actor_id, request_id = _capture_actor()
    session.info['audit_disabled'] = True
    try:
        for entry in staged:
            obj = entry['obj']
            identity = inspect(obj).identity
            row_pk = str(identity[0]) if identity else None
            session.add(AuditLog(
                table_name=obj.__tablename__,
                row_pk=row_pk,
                action=entry['action'],
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
                before_json=json.dumps(entry['before'], default=str) if entry['before'] is not None else None,
                after_json=json.dumps(entry['after'], default=str) if entry['after'] is not None else None,
            ))
    finally:
        session.info['audit_disabled'] = False

