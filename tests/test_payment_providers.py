import hashlib
import hmac
import json

import httpx
import pytest

from app.payment_providers import (
    FakeProvider,
    MalformedEvent,
    PaymentEvent,
    PaymentProviderError,
    PaystackProvider,
    build_payment_provider,
    parse_charge_success,
)

SECRET = "sk_test_not_a_real_key_for_tests_only"


def paystack_with(handler) -> PaystackProvider:
    """A PaystackProvider whose HTTP calls go to `handler`, not the internet."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return PaystackProvider(SECRET, client=client)


def ok_response(reference, url="https://checkout.paystack.com/abc123"):
    return httpx.Response(
        200,
        json={"status": True, "message": "Authorization URL created",
              "data": {"authorization_url": url, "access_code": "abc123", "reference": reference}},
    )


# --- starting a payment with Paystack -------------------------------------------


def test_initialize_sends_what_paystacks_documentation_asks_for():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return ok_response("ref-1")

    url = paystack_with(handler).initialize(
        reference="ref-1", email="ada@example.com", amount_cents=4448, currency="NGN"
    )

    assert url == "https://checkout.paystack.com/abc123"
    assert seen["method"] == "POST"
    assert seen["url"] == "https://api.paystack.co/transaction/initialize"
    assert seen["auth"] == f"Bearer {SECRET}"
    assert seen["body"] == {"email": "ada@example.com", "amount": "4448", "currency": "NGN", "reference": "ref-1"}


@pytest.mark.parametrize("status_code", [400, 401, 500, 503])
def test_an_error_from_paystack_becomes_a_provider_error(status_code):
    provider = paystack_with(lambda request: httpx.Response(status_code, json={"status": False}))

    with pytest.raises(PaymentProviderError):
        provider.initialize(reference="r", email="a@b.co", amount_cents=100, currency="NGN")


def test_a_network_failure_becomes_a_provider_error_without_leaking_the_key():
    def handler(request):
        raise httpx.ConnectError(f"cannot connect while sending {request.headers['authorization']}")

    with pytest.raises(PaymentProviderError) as error:
        paystack_with(handler).initialize(reference="r", email="a@b.co", amount_cents=100, currency="NGN")

    assert SECRET not in str(error.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"status": False, "data": {}}),
        httpx.Response(200, json={"status": True}),
        httpx.Response(200, json={"status": True, "data": {"authorization_url": "https://x.co", "reference": "WRONG"}}),
        httpx.Response(200, json={"status": True, "data": {"authorization_url": "http://insecure.example", "reference": "r"}}),
        httpx.Response(200, json={"status": True, "data": {"authorization_url": "javascript:alert(1)", "reference": "r"}}),
        httpx.Response(200, json={"status": True, "data": {"authorization_url": None, "reference": "r"}}),
    ],
)
def test_odd_responses_are_rejected_so_customers_are_never_sent_somewhere_unsafe(response):
    provider = paystack_with(lambda request: response)

    with pytest.raises(PaymentProviderError):
        provider.initialize(reference="r", email="a@b.co", amount_cents=100, currency="NGN")


# --- checking Paystack's webhooks -------------------------------------------------


def test_paystack_signatures_follow_the_documented_recipe():
    body = b'{"event":"charge.success"}'
    documented = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
    provider = PaystackProvider(SECRET)

    assert provider.signature_is_valid(body, documented) is True
    assert provider.signature_is_valid(body, "0" * 128) is False
    assert provider.signature_is_valid(body, None) is False
    assert provider.signature_is_valid(b'{"event":"changed"}', documented) is False


def test_both_providers_read_the_documented_charge_success_shape():
    # Field names copied from Paystack's webhook documentation.
    payload = {
        "event": "charge.success",
        "data": {"id": 302961, "domain": "live", "status": "success", "reference": "qTPrJoy9Bx",
                 "amount": 10000, "currency": "NGN", "customer": {"email": "bojack@horseman.com"}},
    }

    assert parse_charge_success(payload) == PaymentEvent("qTPrJoy9Bx", 10000, "NGN")
    assert FakeProvider("s").parse_event(payload) == PaymentEvent("qTPrJoy9Bx", 10000, "NGN")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "charge.success",
        {},
        {"event": "refund.processed", "data": {}},
        {"event": "charge.success", "data": None},
        {"event": "charge.success", "data": {"status": "failed", "reference": "r", "amount": 1, "currency": "NGN"}},
    ],
)
def test_things_that_are_not_successful_charges_are_ignored(payload):
    assert parse_charge_success(payload) is None


def test_a_successful_charge_with_bad_fields_is_malformed():
    with pytest.raises(MalformedEvent):
        parse_charge_success({"event": "charge.success", "data": {"status": "success", "reference": "r"}})


# --- choosing a provider -------------------------------------------------------------


def test_paystack_without_a_key_refuses_to_start():
    with pytest.raises(RuntimeError, match="PAYSTACK_SECRET_KEY"):
        build_payment_provider("paystack")


def test_an_unknown_provider_name_refuses_to_start():
    with pytest.raises(RuntimeError, match="Unknown PAYMENT_PROVIDER"):
        build_payment_provider("bitcoin")


def test_the_right_provider_is_built():
    assert build_payment_provider("paystack", paystack_secret_key=SECRET).name == "paystack"
    assert build_payment_provider("fake", webhook_secret="s").name == "fake"


def test_the_fake_provider_without_a_secret_gets_a_random_one():
    first = build_payment_provider("fake")
    second = build_payment_provider("fake")

    body = b"{}"
    assert first.sign(body) != second.sign(body)  # nobody can guess it
