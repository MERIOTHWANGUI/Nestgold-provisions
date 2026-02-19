# app/routes/payments.py
from datetime import datetime

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, url_for

from app import csrf
from app.models import Delivery, DeliveryStatus, ManualPaymentStatus, Payment, PaymentConfig
from app.routes.forms import TrackingLookupForm

payments_bp = Blueprint("payments", __name__)


def _resolve_payment_by_token(token):
    raw = (token or "").strip()
    if not raw:
        return None
    return Payment.query.filter(
        (Payment.tracking_code == raw)
        | (Payment.reference_id == raw.upper())
        | (Payment.checkout_request_id == raw)
    ).first()


def _escape_pdf(text):
    return (text or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _simple_pdf(lines):
    text_ops = ["BT", "/F1 12 Tf", "50 790 Td", "14 TL"]
    for line in lines:
        text_ops.append(f"({_escape_pdf(line)}) Tj")
        text_ops.append("T*")
    text_ops.append("ET")
    stream = "\n".join(text_ops).encode("latin-1", "replace")

    objs = []
    objs.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objs.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
    objs.append(
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >> endobj\n"
    )
    objs.append(f"4 0 obj << /Length {len(stream)} >> stream\n".encode("ascii") + stream + b"\nendstream endobj\n")
    objs.append(b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")

    out = b"%PDF-1.4\n"
    offsets = [0]
    for obj in objs:
        offsets.append(len(out))
        out += obj
    xref_pos = len(out)
    out += f"xref\n0 {len(offsets)}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode("ascii")
    return out


@payments_bp.route("/track", methods=["GET", "POST"])
def track_lookup():
    form = TrackingLookupForm()
    if form.validate_on_submit():
        token = form.tracking_id.data.strip()
        payment = _resolve_payment_by_token(token)
        if payment:
            return redirect(url_for("payments.track_payment", tracking_code=token))
        flash("No payment found for that tracking ID/reference.", "warning")
    return render_template("public/track_lookup.html", form=form)


@payments_bp.route("/track/<tracking_code>")
def track_payment(tracking_code):
    payment = _resolve_payment_by_token(tracking_code)
    if not payment:
        flash("Payment tracking record not found.", "warning")
        return redirect(url_for("payments.track_lookup"))

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
        can_download_receipt=(payment.payment_status == ManualPaymentStatus.CONFIRMED.value),
    )


@payments_bp.route("/track/<tracking_code>/receipt")
def track_receipt_download(tracking_code):
    payment = _resolve_payment_by_token(tracking_code)
    if not payment:
        return Response("Receipt record not found.", status=404, mimetype="text/plain")

    sub = payment.subscription
    ref = payment.admin_transaction_reference or payment.reference_id or payment.checkout_request_id or "-"
    paid_at = payment.payment_date.strftime("%Y-%m-%d %H:%M:%S") if payment.payment_date else "-"
    payment_config = PaymentConfig.query.order_by(PaymentConfig.id.desc()).first()
    paybill = payment_config.mpesa_paybill if payment_config else "174379"
    mpesa_acc_name = payment_config.mpesa_account_name if payment_config else "NestGold Provisions"
    mpesa_acc_no = payment_config.mpesa_account_number if payment_config else ref
    tracking_token = payment.tracking_code or payment.reference_id or payment.checkout_request_id or "-"

    if payment.payment_status == ManualPaymentStatus.CONFIRMED.value:
        lines = [
            "NESTGOLD PROVISIONS - RECEIPT",
            "----------------------------------------",
            f"Receipt Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Payment ID: {payment.id}",
            f"Reference: {ref}",
            f"Tracking ID: {tracking_token}",
            f"Customer: {payment.customer_name or (sub.name if sub else '-')}",
            f"Phone: {payment.customer_phone or (sub.phone if sub else '-')}",
            f"Amount (KES): {payment.amount:.2f}",
            f"Payment Status: {payment.payment_status}",
            f"Confirmed At: {paid_at}",
            f"Plan: {(sub.plan.name if sub and sub.plan else '-')}",
            f"Trays Remaining: {(sub.trays_remaining if sub else 0)}",
        ]
        filename = f"receipt_{payment.id}.pdf"
    else:
        lines = [
            "NESTGOLD PROVISIONS - PAYMENT SLIP",
            "----------------------------------------",
            f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Payment ID: {payment.id}",
            f"Reference: {ref}",
            f"Tracking ID: {tracking_token}",
            f"Customer: {payment.customer_name or (sub.name if sub else '-')}",
            f"Phone: {payment.customer_phone or (sub.phone if sub else '-')}",
            f"Amount (KES): {payment.amount:.2f}",
            f"Payment Status: {payment.payment_status}",
            "",
            "How to pay:",
            f"M-Pesa Paybill: {paybill}",
            f"Account Name: {mpesa_acc_name}",
            f"Account Number: {mpesa_acc_no}",
            f"Payment Note Reference: {ref}",
            "",
            "Keep this slip to recover your tracking details any time.",
        ]
        filename = f"payment_slip_{payment.id}.pdf"

    body = _simple_pdf(lines)
    response = Response(body, mimetype="application/pdf")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@csrf.exempt
@payments_bp.route("/payments/callback", methods=["POST"])
@payments_bp.route("/mpesa_callback", methods=["POST"])
@payments_bp.route("/callback", methods=["POST"])
def callback():
    # Intentionally disabled: manual workflow does not process automatic callbacks.
    return jsonify({"ResultCode": 0, "ResultDesc": "Manual workflow active. Callback ignored."}), 200
