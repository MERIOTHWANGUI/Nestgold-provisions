# app/services/sms.py
# app/services/sms.py
import os
import africastalking
from app.models import db, User, Subscription  # etc.
# Load from .env
AT_USERNAME = os.getenv("AT_USERNAME")
AT_API_KEY = os.getenv("AT_API_KEY")
ADMIN_PHONE = os.getenv('ADMIN_PHONE_NUMBER')

# Initialize the SDK (your downgraded version supports global initialize)
africastalking.initialize(AT_USERNAME, AT_API_KEY)
sms = africastalking.SMS


def send_admin_sms(subscription):
    """
    Sends a notification to the admin when a subscription payment succeeds.
    """
    message = (
        f"🐣 NestGold Provisions: New Paid Subscription!\n"
        f"Customer: {subscription.name}\n"
        f"Plan: {subscription.plan.name}\n"
        f"Trays/week: {subscription.plan.trays_per_week}\n"
        f"Location: {subscription.location}\n"
        f"Phone: {subscription.phone}"
    )
    try:
        # recipients must be a list
        response = sms.send(message, [ADMIN_PHONE])
        print(f"Admin SMS Response: {response}")
    except Exception as e:
        print(f"Admin SMS Error: {e}")


def send_customer_confirmation(subscription):
    """
    Sends welcome/confirmation SMS to the customer after successful payment.
    """
    message = (
        f"Welcome to NestGold Provisions! 🥚\n"
        f"Your {subscription.plan.name} plan is active.\n"
        f"First delivery: {subscription.next_delivery_date.strftime('%A, %d %b')}\n"
        f"Weekly on {subscription.preferred_delivery_day}s.\n"
        f"Questions? WhatsApp us!"
    )
    try:
        phone = subscription.phone
        if not phone.startswith('+254'):
            phone = '+254' + phone.lstrip('0')
        response = sms.send(message, [phone])
        print(f"Customer SMS Response: {response}")
    except Exception as e:
        print(f"Customer SMS Error: {e}")