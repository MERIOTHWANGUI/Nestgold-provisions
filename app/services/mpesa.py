"""Manual payment service utilities.

Automated M-Pesa API calls are intentionally disabled for now.
Legacy M-Pesa request code is preserved below as commented backup.
"""

import os

MPESA_SHORTCODE = os.getenv("MPESA_SHORTCODE", "174379")
MPESA_PAYBILL = os.getenv("MPESA_PAYBILL", MPESA_SHORTCODE)
MPESA_ACCOUNT_NAME = os.getenv("MPESA_ACCOUNT_NAME", "NestGold Provisions")
MANUAL_BANK_NAME = os.getenv("MANUAL_BANK_NAME", "NestGold Bank")
MANUAL_BANK_ACCOUNT = os.getenv("MANUAL_BANK_ACCOUNT", "1234567890")
MANUAL_BANK_ACCOUNT_NAME = os.getenv("MANUAL_BANK_ACCOUNT_NAME", "NestGold Provisions")


def get_manual_payment_instructions(reference_id, amount_kes, customer_name=None, payment_config=None):
    name_part = f" for {customer_name}" if customer_name else ""
    paybill = getattr(payment_config, "mpesa_paybill", None) or MPESA_PAYBILL
    bank_name = getattr(payment_config, "bank_name", None) or MANUAL_BANK_NAME
    bank_account_name = getattr(payment_config, "bank_account_name", None) or MANUAL_BANK_ACCOUNT_NAME
    bank_account_number = getattr(payment_config, "bank_account_number", None) or MANUAL_BANK_ACCOUNT
    footer = getattr(payment_config, "instructions_footer", None) or (
        "After payment, keep your receipt and share it with admin via WhatsApp/SMS/email."
    )
    return (
        f"Please complete your payment{name_part}.\n"
        f"Amount: KES {float(amount_kes):.2f}\n"
        f"Reference ID: {reference_id}\n\n"
        "Option 1 - M-Pesa Paybill\n"
        f"Business Number: {paybill}\n"
        f"Account Number: {reference_id}\n\n"
        "Option 2 - Bank Transfer\n"
        f"Bank: {bank_name}\n"
        f"Account Name: {bank_account_name}\n"
        f"Account Number: {bank_account_number}\n\n"
        f"{footer}"
    )


def get_mpesa_access_token():
    # Automation disabled by request.
    return None


def initiate_stk_push(phone_mpesa, amount_kes, reference_id, customer_name, description):
    # Automation disabled by request.
    return None, "M-Pesa STK automation is disabled. Use manual payment instructions."


# ---------------------------------------------------------------------------
# Legacy backup: previous M-Pesa integration implementation (disabled)
# ---------------------------------------------------------------------------
# import base64
# from datetime import datetime
# import requests
# from requests.auth import HTTPBasicAuth
#
# MPESA_CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY')
# MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET')
# MPESA_PASSKEY = os.getenv('MPESA_PASSKEY')
# MPESA_CALLBACK_URL = os.getenv('MPESA_CALLBACK_URL')
#
# def get_mpesa_access_token():
#     url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
#     try:
#         r = requests.get(
#             url,
#             auth=HTTPBasicAuth(MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET),
#             timeout=10,
#         )
#         r.raise_for_status()
#         return r.json().get('access_token')
#     except requests.RequestException:
#         return None
#
# def initiate_stk_push(phone_mpesa, amount_kes, reference_id, customer_name, description):
#     token = get_mpesa_access_token()
#     if not token:
#         return None, "Failed to get M-Pesa token"
#
#     timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
#     password_str = f"{MPESA_SHORTCODE}{MPESA_PASSKEY}{timestamp}"
#     password = base64.b64encode(password_str.encode()).decode()
#
#     payload = {
#         "BusinessShortCode": MPESA_SHORTCODE,
#         "Password": password,
#         "Timestamp": timestamp,
#         "TransactionType": "CustomerPayBillOnline",
#         "Amount": int(amount_kes),
#         "PartyA": phone_mpesa,
#         "PartyB": MPESA_SHORTCODE,
#         "PhoneNumber": phone_mpesa,
#         "CallBackURL": MPESA_CALLBACK_URL,
#         "AccountReference": reference_id,
#         "TransactionDesc": description,
#     }
#
#     headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
#     url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
#
#     try:
#         r = requests.post(url, json=payload, headers=headers, timeout=15)
#         r.raise_for_status()
#         result = r.json()
#         if result.get("ResponseCode") == "0":
#             return result.get("CheckoutRequestID"), None
#         return None, result.get("errorMessage") or result.get("ResponseDescription") or "STK failed"
#     except requests.RequestException as e:
#         return None, str(e)
