import logging
import os
import secrets

logger = logging.getLogger(__name__)

# The secret key signs login tokens. Anyone who knows it can forge a token and
# log in as anyone, so it must never be written in code or committed to git.
# It is read from an environment variable instead.
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    # Safe fallback for development: a random key made fresh at every start.
    # The cost is that all tokens stop working when the server restarts.
    SECRET_KEY = secrets.token_urlsafe(32)
    logger.warning("SECRET_KEY is not set. Using a random key; logins reset on every restart.")

# HS256 means "sign with one shared secret". We pin the algorithm when we
# verify tokens, which blocks a classic attack (see lesson 4).
JWT_ALGORITHM = "HS256"

# Short-lived tokens limit the damage if one is stolen.
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "30"))

# --- Payments ---------------------------------------------------------------
# "fake" is for development and demos: nothing is charged. "paystack" talks to
# the real Paystack API and needs PAYSTACK_SECRET_KEY.
PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "fake").lower()

# Your Paystack secret key (starts with sk_test_ or sk_live_). It lets whoever
# holds it charge and refund your customers: never put it in code or git.
# It also signs Paystack's webhooks, so we use it to check them.
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")

# Signs webhooks for the FAKE provider only. Random if you do not set it.
PAYMENT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET")

# Amounts are stored in the smallest unit (kobo for NGN), same as Paystack.
CURRENCY = os.getenv("CURRENCY", "NGN").upper()
