# app/services/mpesa.py
import os
import base64
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
from app.models import db, User, Subscription  # etc.

MPESA_CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY')
MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET')
MPESA_SHORTCODE = os.getenv('MPESA_SHORTCODE', '174379')
MPESA_PASSKEY = os.getenv('MPESA_PASSKEY')
MPESA_CALLBACK_URL = os.getenv('MPESA_CALLBACK_URL')


def get_mpesa_access_token():
    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        r = requests.get(url, auth=HTTPBasicAuth(MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET), timeout=10)
        r.raise_for_status()
        token = r.json().get('access_token')
        if token:
            print("M-Pesa Access Token obtained ✅")
        return token
    except Exception as e:
        print(f"Failed to get token: {e}")
        return None


def initiate_stk_push(phone_mpesa, amount_kes, reference_id, customer_name, description):
    token = get_mpesa_access_token()
    if not token:
        return None, "Failed to get M-Pesa token"

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password_str = f"{MPESA_SHORTCODE}{MPESA_PASSKEY}{timestamp}"
    password = base64.b64encode(password_str.encode()).decode()

    payload = {
        "BusinessShortCode": MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount_kes),
        "PartyA": phone_mpesa,
        "PartyB": MPESA_SHORTCODE,
        "PhoneNumber": phone_mpesa,
        "CallBackURL": MPESA_CALLBACK_URL,
        "AccountReference": reference_id,
        "TransactionDesc": description
    }

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

    try:
        print("Sending STK push payload:", payload)
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        r.raise_for_status()
        result = r.json()
        print("STK push response:", result)
        if result.get("ResponseCode") == "0":
            return result.get("CheckoutRequestID"), None
        return None, result.get("errorMessage") or result.get("ResponseDescription") or "STK failed"
    except Exception as e:
        return None, str(e)