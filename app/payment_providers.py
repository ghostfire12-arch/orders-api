import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app import config

logger = logging.getLogger(__name__)

# Both providers use the same header name and signing method, matching
# Paystack's documentation: HMAC SHA512 of the raw request body, written as
# hexadecimal, sent in the "x-paystack-signature" header.
SIGNATURE_HEADER = "x-paystack-signature"


class PaymentProviderError(Exception):
    """The payment provider could not be reached or answered badly."""


class MalformedEvent(ValueError):
    """A correctly signed webhook whose contents are not what we expect."""


@dataclass(frozen=True)
class PaymentEvent:
    """A confirmed successful payment, in a provider-neutral shape."""

    reference: str
    amount_cents: int
    currency: str


class PaymentProvider(Protocol):
    """What the rest of the app needs from ANY payment company.

    Routes and services only know this shape. To support another provider
    (Flutterwave, Stripe), write one new class with these three methods. The
    business logic does not change.
    """

    name: str
    signature_header: str

    def initialize(self, *, reference: str, email: str, amount_cents: int, currency: str) -> str:
        """Start a payment and return the URL the customer must open to pay."""

    def signature_is_valid(self, body: bytes, signature: str | None) -> bool:
        """Is this webhook really from the provider?"""

    def parse_event(self, payload: object) -> PaymentEvent | None:
        """Return a PaymentEvent for a successful charge, None for anything else."""


def sign_body(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()


def signature_matches(secret: str, body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    expected = sign_body(secret, body)
    # compare_digest takes the same time however many characters match. A
    # normal == stops at the first difference, which leaks (through tiny timing
    # differences) how much of a guessed signature was right.
    return hmac.compare_digest(expected.encode(), signature.strip().lower().encode())


def parse_charge_success(payload: object) -> PaymentEvent | None:
    """Read a Paystack-style event. Only "charge.success" matters to us."""
    if not isinstance(payload, dict) or payload.get("event") != "charge.success":
        return None
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("status") != "success":
        return None
    reference = data.get("reference")
    amount = data.get("amount")
    currency = data.get("currency")
    if (
        not isinstance(reference, str)
        or not reference
        or not isinstance(amount, int)
        or isinstance(amount, bool)  # True is an int in Python. Reject it.
        or not isinstance(currency, str)
    ):
        raise MalformedEvent("charge.success without a valid reference, amount and currency")
    return PaymentEvent(reference=reference, amount_cents=amount, currency=currency.upper())


class FakeProvider:
    """A pretend payment company for development and tests. Charges nothing."""

    name = "fake"
    signature_header = SIGNATURE_HEADER

    def __init__(self, webhook_secret: str) -> None:
        self._secret = webhook_secret

    def initialize(self, *, reference: str, email: str, amount_cents: int, currency: str) -> str:
        # ".invalid" is a domain name reserved so it can never exist.
        return f"https://fake-pay.invalid/checkout/{reference}"

    def sign(self, body: bytes) -> str:
        """Used by tests and the simulate script to play the provider's part."""
        return sign_body(self._secret, body)

    def signature_is_valid(self, body: bytes, signature: str | None) -> bool:
        return signature_matches(self._secret, body, signature)

    def parse_event(self, payload: object) -> PaymentEvent | None:
        return parse_charge_success(payload)


class PaystackProvider:
    """Talks to the real Paystack API (https://paystack.com/docs)."""

    name = "paystack"
    signature_header = SIGNATURE_HEADER

    def __init__(
        self,
        secret_key: str,
        client: httpx.Client | None = None,
        base_url: str = "https://api.paystack.co",
    ) -> None:
        self._secret_key = secret_key
        self._base_url = base_url
        # A timeout is essential: without one, a slow provider would freeze
        # our request forever.
        self._client = client or httpx.Client(timeout=10.0)

    def initialize(self, *, reference: str, email: str, amount_cents: int, currency: str) -> str:
        try:
            response = self._client.post(
                f"{self._base_url}/transaction/initialize",
                headers={"Authorization": f"Bearer {self._secret_key}"},
                # Paystack's docs show the amount as a string, in the smallest
                # unit of the currency (kobo for NGN).
                json={
                    "email": email,
                    "amount": str(amount_cents),
                    "currency": currency,
                    "reference": reference,
                },
            )
        except httpx.HTTPError:
            # Deliberately vague: error text from HTTP libraries can contain
            # request details, and nothing here should ever mention the key.
            raise PaymentProviderError("Could not reach Paystack") from None

        if response.status_code != 200:
            raise PaymentProviderError(f"Paystack answered HTTP {response.status_code}")
        try:
            body = response.json()
            ok = body["status"] is True
            url = body["data"]["authorization_url"]
            echoed_reference = body["data"]["reference"]
        except (ValueError, KeyError, TypeError):
            raise PaymentProviderError("Paystack sent an unexpected response") from None
        # Only send customers to an https address that we asked for.
        if not ok or echoed_reference != reference or not isinstance(url, str) or not url.startswith("https://"):
            raise PaymentProviderError("Paystack sent an unexpected response")
        return url

    def signature_is_valid(self, body: bytes, signature: str | None) -> bool:
        # Paystack signs webhooks with the same secret key used for API calls.
        return signature_matches(self._secret_key, body, signature)

    def parse_event(self, payload: object) -> PaymentEvent | None:
        return parse_charge_success(payload)


def build_payment_provider(
    name: str, *, paystack_secret_key: str | None = None, webhook_secret: str | None = None
) -> PaymentProvider:
    if name == "paystack":
        if not paystack_secret_key:
            # Fail at startup, loudly, not at the first customer's checkout.
            raise RuntimeError("PAYSTACK_SECRET_KEY is required when PAYMENT_PROVIDER=paystack")
        return PaystackProvider(paystack_secret_key)
    if name == "fake":
        if not webhook_secret:
            webhook_secret = secrets.token_urlsafe(32)
            logger.warning("PAYMENT_WEBHOOK_SECRET is not set. Using a random one for the fake provider.")
        return FakeProvider(webhook_secret)
    raise RuntimeError(f"Unknown PAYMENT_PROVIDER: {name!r} (use 'fake' or 'paystack')")


@lru_cache
def get_payment_provider() -> PaymentProvider:
    """The one provider the whole app uses. Built once, then reused."""
    return build_payment_provider(
        config.PAYMENT_PROVIDER,
        paystack_secret_key=config.PAYSTACK_SECRET_KEY,
        webhook_secret=config.PAYMENT_WEBHOOK_SECRET,
    )
