import json

import pytest

from app.models import PaymentRow

SIGNATURE = "x-paystack-signature"


def place_order(client, headers, product_id, quantity=1):
    return client.post(
        "/orders", json={"items": [{"product_id": product_id, "quantity": quantity}]}, headers=headers
    ).json()


def start_payment(client, headers, order_id):
    return client.post(f"/orders/{order_id}/pay", headers=headers)


def charge_success(reference, amount, currency="NGN", **overrides):
    event = {
        "event": "charge.success",
        "data": {"id": 1, "status": "success", "reference": reference, "amount": amount, "currency": currency},
    }
    event.update(overrides)
    return event


def send_webhook(client, provider, event, *, signature=None, raw=None):
    """Play the part of the payment provider: sign the exact bytes we send."""
    body = raw if raw is not None else json.dumps(event).encode()
    headers = {"content-type": "application/json"}
    headers[SIGNATURE] = provider.sign(body) if signature is None else signature
    return client.post("/webhooks/payments", content=body, headers=headers)


@pytest.fixture
def order(plain_client, alice, shop):
    """A pending order for 44.48 (2 notebooks and 3 pens)."""
    plain_client.post(
        "/orders",
        json={"items": [{"product_id": shop["notebook"], "quantity": 2}, {"product_id": shop["pen"], "quantity": 3}]},
        headers=alice,
    )
    return plain_client.get("/orders", headers=alice).json()[0]


@pytest.fixture
def payment(plain_client, alice, order):
    return start_payment(plain_client, alice, order["id"]).json()


def order_status(client, headers, order_id):
    return client.get(f"/orders/{order_id}", headers=headers).json()["status"]


# --- starting a payment -----------------------------------------------------


def test_starting_a_payment_returns_where_to_pay(plain_client, alice, order):
    response = start_payment(plain_client, alice, order["id"])

    assert response.status_code == 201
    body = response.json()
    assert body["reference"].startswith(f"ord{order['id']}-")
    assert body["authorization_url"].startswith("https://")
    assert body["amount"] == "44.48"  # the order's total, worked out by the server
    assert body["currency"] == "NGN"
    assert body["status"] == "pending"


def test_the_provider_is_asked_to_charge_exactly_the_order_total(plain_client, alice, order, payment_provider, monkeypatch):
    # What we STORE matters less than what we ASK THE PROVIDER TO CHARGE. If
    # these ever differ, the customer pays one amount and we record another.
    sent = {}
    real_initialize = payment_provider.initialize

    def spy(**kwargs):
        sent.update(kwargs)
        return real_initialize(**kwargs)

    monkeypatch.setattr(payment_provider, "initialize", spy)

    response = start_payment(plain_client, alice, order["id"])

    assert sent["amount_cents"] == 4448
    assert sent["currency"] == "NGN"
    assert sent["email"] == "alice@example.com"
    assert sent["reference"] == response.json()["reference"]


def test_starting_a_payment_does_not_pay_the_order(plain_client, alice, order, payment):
    assert order_status(plain_client, alice, order["id"]) == "pending"


def test_each_attempt_gets_its_own_reference(plain_client, alice, order):
    first = start_payment(plain_client, alice, order["id"]).json()
    second = start_payment(plain_client, alice, order["id"]).json()

    assert first["reference"] != second["reference"]


def test_the_customer_cannot_choose_the_amount(plain_client, alice, order):
    response = plain_client.post(f"/orders/{order['id']}/pay", json={"amount": "0.01"}, headers=alice)

    assert response.json()["amount"] == "44.48"


def test_only_the_owner_can_start_a_payment(plain_client, bob, order):
    assert start_payment(plain_client, bob, order["id"]).status_code == 404


def test_paying_needs_a_login(plain_client, order):
    assert plain_client.post(f"/orders/{order['id']}/pay").status_code == 401


def test_a_missing_order_is_404(plain_client, alice):
    assert start_payment(plain_client, alice, 999).status_code == 404


def test_only_pending_orders_can_be_paid(plain_client, alice, admin, order):
    plain_client.post(f"/orders/{order['id']}/cancel", headers=alice)

    assert start_payment(plain_client, alice, order["id"]).status_code == 409


def test_a_provider_outage_is_a_502_and_leaves_no_payment(plain_client, session_factory, alice, order, payment_provider, monkeypatch):
    from app.payment_providers import PaymentProviderError

    def broken(**_):
        raise PaymentProviderError("boom")

    monkeypatch.setattr(payment_provider, "initialize", broken)

    response = start_payment(plain_client, alice, order["id"])

    assert response.status_code == 502
    assert "boom" not in response.text  # internal details stay internal
    with session_factory() as db:
        assert db.query(PaymentRow).count() == 0


# --- the webhook: the happy path ----------------------------------------------


def test_a_signed_webhook_marks_the_order_paid(plain_client, payment_provider, alice, order, payment):
    response = send_webhook(plain_client, payment_provider, charge_success(payment["reference"], 4448))

    assert response.status_code == 200
    assert response.json() == {"status": "paid"}
    assert order_status(plain_client, alice, order["id"]) == "paid"
    stored = plain_client.get(f"/orders/{order['id']}/payments", headers=alice).json()[0]
    assert stored["status"] == "succeeded"
    assert stored["paid_at"] is not None


def test_the_webhook_needs_no_login(plain_client, payment_provider, payment):
    # The provider has no account here. The signature is its proof.
    response = send_webhook(plain_client, payment_provider, charge_success(payment["reference"], 4448))

    assert response.status_code == 200


def test_the_signature_covers_the_exact_bytes_not_a_reformatted_copy(plain_client, payment_provider, order, alice, payment):
    # Same JSON, unusual spacing and key order. A server that parsed and
    # re-serialised the body would compute a different signature.
    raw = (
        '{ "data" : { "currency":"NGN", "amount":4448, "status":"success",'
        f' "reference":"{payment["reference"]}" }}, "event":"charge.success" }}'
    ).encode()

    response = send_webhook(plain_client, payment_provider, None, raw=raw)

    assert response.status_code == 200
    assert order_status(plain_client, alice, order["id"]) == "paid"


# --- the webhook: attacks and mistakes ------------------------------------------


@pytest.mark.parametrize("signature", [None, "", "not-a-signature", "0" * 128])
def test_forged_or_missing_signatures_are_rejected(plain_client, alice, order, payment, signature):
    body = json.dumps(charge_success(payment["reference"], 4448)).encode()
    headers = {"content-type": "application/json"}
    if signature is not None:
        headers[SIGNATURE] = signature

    response = plain_client.post("/webhooks/payments", content=body, headers=headers)

    assert response.status_code == 401
    assert order_status(plain_client, alice, order["id"]) == "pending"  # nothing changed


def test_a_body_changed_after_signing_is_rejected(plain_client, payment_provider, alice, order, payment):
    # The attacker captures a real signature for a SMALL amount, then reuses it
    # on a body that claims the full amount.
    small = json.dumps(charge_success(payment["reference"], 1)).encode()
    signature = payment_provider.sign(small)
    big = json.dumps(charge_success(payment["reference"], 4448)).encode()

    response = send_webhook(plain_client, payment_provider, None, raw=big, signature=signature)

    assert response.status_code == 401
    assert order_status(plain_client, alice, order["id"]) == "pending"


def test_a_signature_made_with_the_wrong_secret_is_rejected(plain_client, alice, order, payment):
    from app.payment_providers import FakeProvider

    attacker = FakeProvider("the attacker's own secret")

    response = send_webhook(plain_client, attacker, charge_success(payment["reference"], 4448))

    assert response.status_code == 401
    assert order_status(plain_client, alice, order["id"]) == "pending"


def test_an_uppercase_signature_is_accepted_but_nothing_else_is_loosened(plain_client, payment_provider, payment):
    body = json.dumps(charge_success(payment["reference"], 4448)).encode()

    response = send_webhook(plain_client, payment_provider, None, raw=body, signature=payment_provider.sign(body).upper())

    assert response.status_code == 200


def test_a_replayed_webhook_changes_nothing_the_second_time(plain_client, payment_provider, alice, order, payment):
    event = charge_success(payment["reference"], 4448)

    first = send_webhook(plain_client, payment_provider, event)
    second = send_webhook(plain_client, payment_provider, event)

    assert first.json() == {"status": "paid"}
    assert second.status_code == 200  # still 200, so the provider stops retrying
    assert second.json() == {"status": "already_processed"}
    assert order_status(plain_client, alice, order["id"]) == "paid"


def test_the_wrong_amount_never_pays_the_order(plain_client, payment_provider, alice, order, payment):
    response = send_webhook(plain_client, payment_provider, charge_success(payment["reference"], 100))

    assert response.json() == {"status": "amount_mismatch"}
    assert order_status(plain_client, alice, order["id"]) == "pending"
    stored = plain_client.get(f"/orders/{order['id']}/payments", headers=alice).json()[0]
    assert stored["status"] == "needs_review"


def test_the_wrong_currency_never_pays_the_order(plain_client, payment_provider, alice, order, payment):
    response = send_webhook(plain_client, payment_provider, charge_success(payment["reference"], 4448, "USD"))

    assert response.json() == {"status": "amount_mismatch"}
    assert order_status(plain_client, alice, order["id"]) == "pending"


def test_an_unknown_reference_is_acknowledged_and_ignored(plain_client, payment_provider, alice, order, payment):
    response = send_webhook(plain_client, payment_provider, charge_success("someone-elses-ref", 4448))

    assert response.status_code == 200
    assert response.json() == {"status": "unknown_reference"}
    assert order_status(plain_client, alice, order["id"]) == "pending"


def test_other_event_types_are_ignored(plain_client, payment_provider, alice, order, payment):
    event = charge_success(payment["reference"], 4448, event="transfer.success")

    response = send_webhook(plain_client, payment_provider, event)

    assert response.json() == {"status": "ignored"}
    assert order_status(plain_client, alice, order["id"]) == "pending"


def test_a_failed_charge_does_not_pay_the_order(plain_client, payment_provider, alice, order, payment):
    event = charge_success(payment["reference"], 4448)
    event["data"]["status"] = "failed"

    response = send_webhook(plain_client, payment_provider, event)

    assert response.json() == {"status": "ignored"}
    assert order_status(plain_client, alice, order["id"]) == "pending"


@pytest.mark.parametrize(
    "event",
    [
        {"event": "charge.success", "data": {"status": "success"}},  # no reference or amount
        {"event": "charge.success", "data": {"status": "success", "reference": "r", "amount": "4448", "currency": "NGN"}},
        {"event": "charge.success", "data": {"status": "success", "reference": "r", "amount": True, "currency": "NGN"}},
        {"event": "charge.success", "data": {"status": "success", "reference": "", "amount": 1, "currency": "NGN"}},
    ],
)
def test_signed_but_malformed_events_are_400(plain_client, payment_provider, event):
    assert send_webhook(plain_client, payment_provider, event).status_code == 400


def test_signed_garbage_that_is_not_json_is_400(plain_client, payment_provider):
    assert send_webhook(plain_client, payment_provider, None, raw=b"this is not json").status_code == 400


def test_an_oversized_body_is_refused_before_anything_else(plain_client, payment_provider):
    huge = b'{"padding": "' + b"x" * (70 * 1024) + b'"}'

    assert send_webhook(plain_client, payment_provider, None, raw=huge).status_code == 413


def test_payment_arriving_after_the_customer_cancelled_is_flagged_not_applied(plain_client, payment_provider, alice, order, payment):
    plain_client.post(f"/orders/{order['id']}/cancel", headers=alice)

    response = send_webhook(plain_client, payment_provider, charge_success(payment["reference"], 4448))

    assert response.json() == {"status": "order_not_payable"}
    assert order_status(plain_client, alice, order["id"]) == "cancelled"  # never revived
    stored = plain_client.get(f"/orders/{order['id']}/payments", headers=alice).json()[0]
    assert stored["status"] == "needs_review"


def test_the_payment_and_the_order_change_together_or_not_at_all(plain_client, payment_provider, session_factory, alice, order, payment, monkeypatch):
    from app import payment_service

    def explode(*_args, **_kwargs):
        raise RuntimeError("crash between the two updates")

    monkeypatch.setattr(payment_service.OrderRepository, "change_status", explode)

    with pytest.raises(RuntimeError):
        send_webhook(plain_client, payment_provider, charge_success(payment["reference"], 4448))
    monkeypatch.undo()

    with session_factory() as db:
        row = db.query(PaymentRow).one()
        assert row.status == "pending"  # rolled back, so the provider's retry can succeed
    retry = send_webhook(plain_client, payment_provider, charge_success(payment["reference"], 4448))
    assert retry.json() == {"status": "paid"}


# --- who can see payments -------------------------------------------------------


def test_owners_and_admins_can_list_payments_but_strangers_cannot(plain_client, alice, bob, admin, order, payment):
    assert len(plain_client.get(f"/orders/{order['id']}/payments", headers=alice).json()) == 1
    assert len(plain_client.get(f"/orders/{order['id']}/payments", headers=admin).json()) == 1
    assert plain_client.get(f"/orders/{order['id']}/payments", headers=bob).status_code == 404
    assert plain_client.get(f"/orders/{order['id']}/payments").status_code == 401
