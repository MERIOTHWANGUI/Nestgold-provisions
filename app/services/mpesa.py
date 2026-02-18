# ----------------------------
# M-Pesa Integration Service
# ----------------------------
# This file handles:
# 1. Fetching M-Pesa OAuth access token
# 2. Initiating STK push requests
# ----------------------------

import os
import base64
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
from app.models import db, User, Subscription  # etc.

# ----------------------------
# Environment Variables
# ----------------------------
# Always set these in your environment. Do NOT hardcode real credentials.
MPESA_CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY')  # Your M-Pesa consumer key
MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET')  # Your M-Pesa consumer secret
MPESA_SHORTCODE = os.getenv('MPESA_SHORTCODE', '174379')  # Default sandbox Paybill
MPESA_PASSKEY = os.getenv('MPESA_PASSKEY')  # M-Pesa passkey
MPESA_CALLBACK_URL = os.getenv('MPESA_CALLBACK_URL')  # Your callback endpoint

# ----------------------------
# Fetch M-Pesa Access Token
# ----------------------------
# Returns a token string if successful, None otherwise
def get_mpesa_access_token():
    # Use sandbox URL for testing; switch to live when going production
    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    try:
        # HTTP Basic auth with consumer key/secret
        r = requests.get(url, auth=HTTPBasicAuth(MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET), timeout=10)
        r.raise_for_status()
        token = r.json().get('access_token')
        if token:
            print("M-Pesa Access Token obtained ✅")
        return token
    except requests.RequestException as e:
        # Handle network, timeout, or auth failures
        print(f"Failed to get token: {e}")
        return None

# ----------------------------
# Initiate STK Push
# ----------------------------
# Returns (CheckoutRequestID, None) if successful, or (None, error_message) on failure
def initiate_stk_push(phone_mpesa, amount_kes, reference_id, customer_name, description):
    # 1. Get M-Pesa access token
    token = get_mpesa_access_token()
    if not token:
        return None, "Failed to get M-Pesa token"

    # 2. Generate timestamp and password for request
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password_str = f"{MPESA_SHORTCODE}{MPESA_PASSKEY}{timestamp}"
    password = base64.b64encode(password_str.encode()).decode()

    # 3. Prepare STK push payload
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
    url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"  # Sandbox endpoint

    # 4. Send the STK push request
    try:
        print("Sending STK push payload:", payload)
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        r.raise_for_status()
        result = r.json()
        print("STK push response:", result)

        # 5. Handle M-Pesa response
        if result.get("ResponseCode") == "0":
            # Success → return checkout ID
            return result.get("CheckoutRequestID"), None
        # Fail → return error message from response
        return None, result.get("errorMessage") or result.get("ResponseDescription") or "STK failed"

    except requests.RequestException as e:
        # Catch network errors, timeouts, etc.
        return None, str(e)

# ----------------------------
# Notes on Handling Responses
# ----------------------------
# 1. Always check if CheckoutRequestID is returned before updating DB.
# 2. If None is returned, log the error and inform the user gracefully.
# 3. Retry logic can be added outside this function (do NOT retry automatically here).
# 4. Never log sensitive credentials in production.
# 5. For production, switch token and STK URLs to live endpoints.
# ----------------------------
# NOTE: For production/live, replace sandbox URLs with:
# Token URL: https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials
# STK push URL: https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest
# Do not hardcode credentials; use environment variables.
# ----------------------------
