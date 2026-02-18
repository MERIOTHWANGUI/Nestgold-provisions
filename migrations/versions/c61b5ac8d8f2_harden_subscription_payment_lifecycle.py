"""harden subscription and payment lifecycle

Revision ID: c61b5ac8d8f2
Revises: a9102fdd2ee5
Create Date: 2026-02-18 12:10:00.000000
"""

from datetime import datetime, timedelta, timezone
import re

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c61b5ac8d8f2'
down_revision = 'a9102fdd2ee5'
branch_labels = None
depends_on = None


def _normalize_phone(phone):
    digits = re.sub(r"\D+", "", phone or "")
    if digits.startswith("0") and len(digits) == 10:
        return f"254{digits[1:]}"
    if digits.startswith("7") and len(digits) == 9:
        return f"254{digits}"
    if digits.startswith("254") and len(digits) == 12:
        return digits
    return digits


def _parse_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    dt = None
            if dt is None:
                return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _normalize_subscription_status(status):
    val = (status or "").strip().lower()
    if val == "pending":
        return "Pending"
    if val == "active":
        return "Active"
    if val == "failed":
        return "Failed"
    if val in {"cancelled", "canceled"}:
        return "Cancelled"
    if val == "expired":
        return "Expired"
    return "Pending"


def _status_from_period(status, current_period_end, now):
    if status == "Pending":
        return status
    if status in {"Failed", "Cancelled"}:
        return status
    if current_period_end and current_period_end > now:
        return "Active"
    return "Expired"


def _dedupe_subscriptions(bind):
    rows = bind.execute(sa.text("""
        SELECT id, plan_id, phone_normalized, current_period_end
        FROM subscriptions
        ORDER BY id DESC
    """)).mappings().all()

    winners = {}
    losers = []

    for row in rows:
        key = (row["plan_id"], row["phone_normalized"])
        cpe = _parse_dt(row["current_period_end"]) or datetime.min
        if key not in winners:
            winners[key] = {"id": row["id"], "current_period_end": cpe}
            continue

        winner = winners[key]
        if cpe > winner["current_period_end"]:
            losers.append((winner["id"], row["id"]))
            winners[key] = {"id": row["id"], "current_period_end": cpe}
        else:
            losers.append((row["id"], winner["id"]))

    for loser_id, winner_id in losers:
        bind.execute(
            sa.text("UPDATE payments SET subscription_id = :winner WHERE subscription_id = :loser"),
            {"winner": winner_id, "loser": loser_id},
        )
        bind.execute(
            sa.text("UPDATE deliveries SET subscription_id = :winner WHERE subscription_id = :loser"),
            {"winner": winner_id, "loser": loser_id},
        )
        bind.execute(sa.text("DELETE FROM subscriptions WHERE id = :id"), {"id": loser_id})


def _dedupe_payments(bind):
    rows = bind.execute(sa.text("""
        SELECT id, checkout_request_id, status
        FROM payments
        WHERE checkout_request_id IS NOT NULL
        ORDER BY id DESC
    """)).mappings().all()

    chosen = {}
    to_delete = []

    for row in rows:
        checkout_id = row["checkout_request_id"]
        status = (row["status"] or "").strip().lower()
        score = 1 if status == "completed" else 0

        if checkout_id not in chosen:
            chosen[checkout_id] = (row["id"], score)
            continue

        winner_id, winner_score = chosen[checkout_id]
        if score > winner_score:
            to_delete.append(winner_id)
            chosen[checkout_id] = (row["id"], score)
        else:
            to_delete.append(row["id"])

    for payment_id in to_delete:
        bind.execute(sa.text("DELETE FROM payments WHERE id = :id"), {"id": payment_id})


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "subscriptions" in existing_tables:
        subscription_columns = {col["name"] for col in inspector.get_columns("subscriptions")}
        with op.batch_alter_table("subscriptions", schema=None) as batch_op:
            if "current_period_end" not in subscription_columns:
                batch_op.add_column(sa.Column("current_period_end", sa.DateTime(), nullable=True))
            if "phone_normalized" not in subscription_columns:
                batch_op.add_column(sa.Column("phone_normalized", sa.String(length=20), nullable=True))
            if "checkout_request_id" in subscription_columns:
                batch_op.alter_column(
                    "checkout_request_id",
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=100),
                    existing_nullable=True,
                )

        now = datetime.utcnow()
        sub_rows = bind.execute(sa.text("""
            SELECT id, phone, status, start_date, next_delivery_date
            FROM subscriptions
        """)).mappings().all()

        for row in sub_rows:
            start_dt = _parse_dt(row["start_date"]) or now
            next_delivery = _parse_dt(row["next_delivery_date"])
            status = _normalize_subscription_status(row["status"])

            if status == "Active":
                period_end = start_dt + timedelta(days=30)
                if next_delivery and next_delivery > period_end:
                    period_end = next_delivery
            else:
                period_end = start_dt

            status = _status_from_period(status, period_end, now)

            bind.execute(
                sa.text("""
                    UPDATE subscriptions
                    SET phone_normalized = :phone_normalized,
                        current_period_end = :current_period_end,
                        status = :status
                    WHERE id = :id
                """),
                {
                    "id": row["id"],
                    "phone_normalized": _normalize_phone(row["phone"]),
                    "current_period_end": period_end,
                    "status": status,
                },
            )

        _dedupe_subscriptions(bind)

        inspector = sa.inspect(bind)
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("subscriptions")}
        existing_uniques = {uq["name"] for uq in inspector.get_unique_constraints("subscriptions")}

        with op.batch_alter_table("subscriptions", schema=None) as batch_op:
            batch_op.alter_column("current_period_end", existing_type=sa.DateTime(), nullable=False)
            batch_op.alter_column("phone_normalized", existing_type=sa.String(length=20), nullable=False)
            if "uq_subscriptions_plan_phone_normalized" not in existing_uniques:
                batch_op.create_unique_constraint(
                    "uq_subscriptions_plan_phone_normalized",
                    ["plan_id", "phone_normalized"],
                )
            if "ix_subscriptions_current_period_end" not in existing_indexes:
                batch_op.create_index("ix_subscriptions_current_period_end", ["current_period_end"], unique=False)
            if "ix_subscriptions_phone_normalized" not in existing_indexes:
                batch_op.create_index("ix_subscriptions_phone_normalized", ["phone_normalized"], unique=False)

    if "payments" in existing_tables:
        _dedupe_payments(bind)

        inspector = sa.inspect(bind)
        payment_columns = {col["name"] for col in inspector.get_columns("payments")}
        payment_indexes = {idx["name"] for idx in inspector.get_indexes("payments")}
        payment_uniques = {uq["name"] for uq in inspector.get_unique_constraints("payments")}

        if "ix_payments_checkout_request_id" in payment_indexes:
            op.drop_index("ix_payments_checkout_request_id", table_name="payments")

        with op.batch_alter_table("payments", schema=None) as batch_op:
            if "subscription_id" in payment_columns:
                batch_op.alter_column(
                    "subscription_id",
                    existing_type=sa.Integer(),
                    nullable=True,
                )
            if "uq_payments_checkout_request_id" not in payment_uniques:
                batch_op.create_unique_constraint("uq_payments_checkout_request_id", ["checkout_request_id"])

    if "audit_logs" not in existing_tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("table_name", sa.String(length=100), nullable=False),
            sa.Column("row_pk", sa.String(length=100), nullable=True),
            sa.Column("action", sa.String(length=20), nullable=False),
            sa.Column("changed_at", sa.DateTime(), nullable=False),
            sa.Column("actor_type", sa.String(length=30), nullable=False),
            sa.Column("actor_id", sa.String(length=100), nullable=True),
            sa.Column("request_id", sa.String(length=120), nullable=True),
            sa.Column("before_json", sa.Text(), nullable=True),
            sa.Column("after_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_audit_logs_changed_at"), "audit_logs", ["changed_at"], unique=False)
        op.create_index(op.f("ix_audit_logs_row_pk"), "audit_logs", ["row_pk"], unique=False)
        op.create_index(op.f("ix_audit_logs_table_name"), "audit_logs", ["table_name"], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "audit_logs" in existing_tables:
        op.drop_index(op.f("ix_audit_logs_table_name"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_row_pk"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_changed_at"), table_name="audit_logs")
        op.drop_table("audit_logs")

    if "payments" in existing_tables:
        with op.batch_alter_table("payments", schema=None) as batch_op:
            batch_op.drop_constraint("uq_payments_checkout_request_id", type_="unique")
            batch_op.create_index("ix_payments_checkout_request_id", ["checkout_request_id"], unique=False)
            batch_op.alter_column(
                "subscription_id",
                existing_type=sa.Integer(),
                nullable=False,
            )

    if "subscriptions" in existing_tables:
        with op.batch_alter_table("subscriptions", schema=None) as batch_op:
            batch_op.drop_index("ix_subscriptions_phone_normalized")
            batch_op.drop_index("ix_subscriptions_current_period_end")
            batch_op.drop_constraint("uq_subscriptions_plan_phone_normalized", type_="unique")
            batch_op.drop_column("phone_normalized")
            batch_op.drop_column("current_period_end")
