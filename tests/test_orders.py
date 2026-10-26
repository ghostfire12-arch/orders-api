from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import OrderRow, ProductRow


def place_order(client, headers, *lines):
    """lines are (product_id, quantity) pairs."""
    items = [{"product_id": product_id, "quantity": quantity} for product_id, quantity in lines]
    return client.post("/orders", json={"items": items}, headers=headers)


def stock_of(client, product_id) -> int:
    return client.get(f"/products/{product_id}").json()["stock"]


# --- creating orders --------------------------------------------------------


def test_total_is_calculated_by_the_server(plain_client, alice, shop):
    response = place_order(plain_client, alice, (shop["notebook"], 2), (shop["pen"], 3))

    assert response.status_code == 201
    order = response.json()
    assert order["status"] == "pending"
    assert order["total"] == "44.48"  # 2 x 19.99 + 3 x 1.50
    assert [(i["product_name"], i["unit_price"], i["quantity"], i["line_total"]) for i in order["items"]] == [
        ("Notebook", "19.99", 2, "39.98"),
        ("Pen", "1.50", 3, "4.50"),
    ]


def test_timestamps_are_labelled_as_utc(plain_client, alice, shop):
    order = place_order(plain_client, alice, (shop["pen"], 1)).json()

    assert order["created_at"].endswith("Z")


def test_clients_cannot_choose_the_price(plain_client, alice, shop):
    response = plain_client.post(
        "/orders",
        json={"items": [{"product_id": shop["notebook"], "quantity": 1, "unit_price": "0.01"}]},
        headers=alice,
    )

    assert response.json()["total"] == "19.99"


def test_clients_cannot_order_as_someone_else(plain_client, alice, shop):
    me = plain_client.get("/users/me", headers=alice).json()

    response = plain_client.post(
        "/orders",
        json={"user_id": 999, "items": [{"product_id": shop["pen"], "quantity": 1}]},
        headers=alice,
    )

    assert response.json()["user_id"] == me["id"]


def test_ordering_takes_stock(plain_client, alice, shop):
    place_order(plain_client, alice, (shop["notebook"], 3))

    assert stock_of(plain_client, shop["notebook"]) == 7


def test_not_enough_stock_is_a_409_and_changes_nothing(plain_client, alice, shop):
    response = place_order(plain_client, alice, (shop["notebook"], 11))

    assert response.status_code == 409
    assert response.json()["detail"] == "Not enough stock for Notebook: 10 available"
    assert stock_of(plain_client, shop["notebook"]) == 10


def test_orders_are_all_or_nothing(plain_client, alice, shop):
    # The pen is fine, the notebook is not. The pen stock taken first must be
    # given back, and no half-finished order may exist.
    response = place_order(plain_client, alice, (shop["pen"], 5), (shop["notebook"], 50))

    assert response.status_code == 409
    assert stock_of(plain_client, shop["pen"]) == 100
    assert plain_client.get("/orders", headers=alice).json() == []


def test_the_last_item_can_be_bought_exactly_once(plain_client, alice, bob, shop):
    place_order(plain_client, alice, (shop["notebook"], 10))

    second = place_order(plain_client, bob, (shop["notebook"], 1))

    assert second.status_code == 409
    assert stock_of(plain_client, shop["notebook"]) == 0


def test_unknown_product_is_404(plain_client, alice, shop):
    response = place_order(plain_client, alice, (999, 1))

    assert response.status_code == 404
    assert response.json()["detail"] == "Product 999 not found"


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"product_id": 1, "quantity": 0}],
        [{"product_id": 1, "quantity": 101}],
        [{"product_id": 1, "quantity": 1}, {"product_id": 1, "quantity": 2}],
        [{"product_id": 0, "quantity": 1}],
        [{"product_id": 1}],
    ],
)
def test_invalid_orders_are_rejected(plain_client, alice, shop, items):
    response = plain_client.post("/orders", json={"items": items}, headers=alice)

    assert response.status_code == 422


def test_ordering_needs_a_login(plain_client, shop):
    response = plain_client.post("/orders", json={"items": [{"product_id": 1, "quantity": 1}]})

    assert response.status_code == 401


def test_the_price_paid_is_frozen_at_purchase_time(plain_client, session_factory, alice, shop):
    order = place_order(plain_client, alice, (shop["notebook"], 1)).json()

    with session_factory() as db:  # the shop raises the price afterwards
        db.get(ProductRow, shop["notebook"]).price_cents = 5000
        db.commit()
    again = plain_client.get(f"/orders/{order['id']}", headers=alice).json()

    assert again["total"] == "19.99"
    assert again["items"][0]["unit_price"] == "19.99"


# --- who can see what -------------------------------------------------------


def test_customers_see_only_their_own_orders_newest_first(plain_client, alice, bob, shop):
    first = place_order(plain_client, alice, (shop["pen"], 1)).json()
    second = place_order(plain_client, alice, (shop["pen"], 2)).json()
    place_order(plain_client, bob, (shop["pen"], 3))

    mine = plain_client.get("/orders", headers=alice).json()

    assert [order["id"] for order in mine] == [second["id"], first["id"]]


def test_my_orders_are_paged(plain_client, alice, shop):
    for _ in range(3):
        place_order(plain_client, alice, (shop["pen"], 1))

    page = plain_client.get("/orders", params={"skip": 1, "limit": 1}, headers=alice).json()

    assert len(page) == 1


def test_a_customer_can_open_their_own_order(plain_client, alice, shop):
    order = place_order(plain_client, alice, (shop["pen"], 1)).json()

    response = plain_client.get(f"/orders/{order['id']}", headers=alice)

    assert response.status_code == 200
    assert response.json() == order


def test_another_customers_order_looks_like_it_does_not_exist(plain_client, alice, bob, shop):
    order = place_order(plain_client, alice, (shop["pen"], 1)).json()

    stranger = plain_client.get(f"/orders/{order['id']}", headers=bob)
    missing = plain_client.get("/orders/9999", headers=bob)

    assert stranger.status_code == missing.status_code == 404
    assert stranger.json() == missing.json()  # no hint that the order exists


def test_admins_can_open_any_order(plain_client, alice, admin, shop):
    order = place_order(plain_client, alice, (shop["pen"], 1)).json()

    assert plain_client.get(f"/orders/{order['id']}", headers=admin).status_code == 200


def test_viewing_orders_needs_a_login(plain_client, alice, shop):
    order = place_order(plain_client, alice, (shop["pen"], 1)).json()

    assert plain_client.get("/orders").status_code == 401
    assert plain_client.get(f"/orders/{order['id']}").status_code == 401


# --- cancelling -------------------------------------------------------------


def test_a_customer_can_cancel_a_pending_order_and_stock_comes_back(plain_client, alice, shop):
    order = place_order(plain_client, alice, (shop["notebook"], 4)).json()

    response = plain_client.post(f"/orders/{order['id']}/cancel", headers=alice)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert stock_of(plain_client, shop["notebook"]) == 10


def test_cancelling_twice_gives_the_stock_back_only_once(plain_client, alice, shop):
    order = place_order(plain_client, alice, (shop["notebook"], 4)).json()
    plain_client.post(f"/orders/{order['id']}/cancel", headers=alice)

    second = plain_client.post(f"/orders/{order['id']}/cancel", headers=alice)

    assert second.status_code == 409
    assert stock_of(plain_client, shop["notebook"]) == 10


def test_a_paid_order_cannot_be_cancelled_by_the_customer(plain_client, alice, admin, shop):
    order = place_order(plain_client, alice, (shop["pen"], 1)).json()
    plain_client.patch(f"/orders/{order['id']}/status", json={"status": "paid"}, headers=admin)

    response = plain_client.post(f"/orders/{order['id']}/cancel", headers=alice)

    assert response.status_code == 409


def test_a_customer_cannot_cancel_someone_elses_order(plain_client, alice, bob, shop):
    order = place_order(plain_client, alice, (shop["pen"], 1)).json()

    response = plain_client.post(f"/orders/{order['id']}/cancel", headers=bob)

    assert response.status_code == 404
    assert plain_client.get(f"/orders/{order['id']}", headers=alice).json()["status"] == "pending"


# --- admin: listing and status changes ---------------------------------------


def test_admins_can_list_every_order_and_filter_by_status(plain_client, alice, bob, admin, shop):
    paid = place_order(plain_client, alice, (shop["pen"], 1)).json()
    place_order(plain_client, bob, (shop["pen"], 1))
    plain_client.patch(f"/orders/{paid['id']}/status", json={"status": "paid"}, headers=admin)

    everything = plain_client.get("/admin/orders", headers=admin).json()
    only_paid = plain_client.get("/admin/orders", params={"status": "paid"}, headers=admin).json()

    assert len(everything) == 2
    assert [order["id"] for order in only_paid] == [paid["id"]]


def test_the_admin_list_is_for_admins_only(plain_client, alice):
    assert plain_client.get("/admin/orders").status_code == 401
    assert plain_client.get("/admin/orders", headers=alice).status_code == 403


def test_an_unknown_status_filter_is_rejected(plain_client, admin):
    response = plain_client.get("/admin/orders", params={"status": "teleported"}, headers=admin)

    assert response.status_code == 422


def test_an_order_moves_through_its_whole_life(plain_client, alice, admin, shop):
    order = place_order(plain_client, alice, (shop["pen"], 1)).json()

    seen = []
    for next_status in ["paid", "shipped", "delivered"]:
        response = plain_client.patch(
            f"/orders/{order['id']}/status", json={"status": next_status}, headers=admin
        )
        assert response.status_code == 200
        seen.append(response.json()["status"])

    assert seen == ["paid", "shipped", "delivered"]


@pytest.mark.parametrize(
    ("path", "illegal"),
    [
        (["shipped"], "pending -> shipped"),
        (["paid", "pending"], "paid -> pending"),
        (["paid", "shipped", "delivered", "paid"], "delivered -> paid"),
        (["cancelled", "paid"], "cancelled -> paid"),
    ],
)
def test_illegal_status_jumps_are_409(plain_client, alice, admin, shop, path, illegal):
    order = place_order(plain_client, alice, (shop["pen"], 1)).json()
    for step in path[:-1]:
        assert plain_client.patch(
            f"/orders/{order['id']}/status", json={"status": step}, headers=admin
        ).status_code == 200

    response = plain_client.patch(
        f"/orders/{order['id']}/status", json={"status": path[-1]}, headers=admin
    )

    assert response.status_code == 409
    assert response.json()["detail"] == f"Cannot change status from {illegal.replace(' -> ', ' to ')}"


def test_an_unknown_status_value_is_rejected(plain_client, alice, admin, shop):
    order = place_order(plain_client, alice, (shop["pen"], 1)).json()

    response = plain_client.patch(
        f"/orders/{order['id']}/status", json={"status": "teleported"}, headers=admin
    )

    assert response.status_code == 422


def test_customers_cannot_change_status(plain_client, alice, shop):
    order = place_order(plain_client, alice, (shop["pen"], 1)).json()

    response = plain_client.patch(
        f"/orders/{order['id']}/status", json={"status": "paid"}, headers=alice
    )

    assert response.status_code == 403


def test_changing_the_status_of_a_missing_order_is_404(plain_client, admin):
    response = plain_client.patch("/orders/999/status", json={"status": "paid"}, headers=admin)

    assert response.status_code == 404


def test_an_admin_cancelling_also_returns_the_stock(plain_client, alice, admin, shop):
    order = place_order(plain_client, alice, (shop["notebook"], 5)).json()
    plain_client.patch(f"/orders/{order['id']}/status", json={"status": "paid"}, headers=admin)

    response = plain_client.patch(
        f"/orders/{order['id']}/status", json={"status": "cancelled"}, headers=admin
    )

    assert response.status_code == 200
    assert stock_of(plain_client, shop["notebook"]) == 10


# --- the database itself ------------------------------------------------------


def test_the_database_refuses_an_order_for_a_user_that_does_not_exist(session_factory):
    with session_factory() as db:
        db.add(OrderRow(user_id=12345, status="pending", total_cents=100))
        with pytest.raises(IntegrityError):
            db.commit()


def test_money_math_uses_exact_decimals():
    # 3 x 19.99 as floats gives 59.97000000000001. As cents it is exact.
    assert Decimal(1999 * 3).scaleb(-2) == Decimal("59.97")
