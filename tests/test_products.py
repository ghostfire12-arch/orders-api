def make_product(client, **overrides):
    payload = {"name": "Notebook", "description": "A5, 120 pages", "price": "19.99", "stock": 10}
    payload.update(overrides)
    return client.post("/products", json=payload)


def test_create_product_returns_201_and_the_saved_product(client):
    response = make_product(client)

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["name"] == "Notebook"
    # Money is sent as a string so no precision is lost along the way.
    assert body["price"] == "19.99"
    assert body["stock"] == 10


def test_ids_increase_for_each_new_product(client):
    first = make_product(client).json()
    second = make_product(client, name="Pen").json()

    assert (first["id"], second["id"]) == (1, 2)


def test_stock_defaults_to_zero_and_description_is_optional(client):
    response = client.post("/products", json={"name": "Pen", "price": "1.50"})

    assert response.status_code == 201
    assert response.json()["stock"] == 0
    assert response.json()["description"] is None


def test_name_is_trimmed(client):
    response = make_product(client, name="  Notebook  ")

    assert response.json()["name"] == "Notebook"


def test_blank_name_is_rejected(client):
    assert make_product(client, name="   ").status_code == 422


def test_price_must_be_greater_than_zero(client):
    assert make_product(client, price="0").status_code == 422
    assert make_product(client, price="-5").status_code == 422


def test_price_cannot_have_more_than_two_decimal_places(client):
    assert make_product(client, price="1.999").status_code == 422


def test_stock_cannot_be_negative(client):
    assert make_product(client, stock=-1).status_code == 422


def test_missing_price_is_rejected(client):
    response = client.post("/products", json={"name": "Pen"})

    assert response.status_code == 422


def test_get_product_by_id(client):
    created = make_product(client).json()

    response = client.get(f"/products/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_product_returns_404(client):
    response = client.get("/products/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Product not found"}


def test_product_id_must_be_a_number(client):
    assert client.get("/products/abc").status_code == 422


def test_list_products_with_pagination(client):
    for number in range(5):
        make_product(client, name=f"Item {number}")

    page = client.get("/products", params={"skip": 2, "limit": 2}).json()

    assert [product["name"] for product in page] == ["Item 2", "Item 3"]


def test_list_limit_is_capped(client):
    assert client.get("/products", params={"limit": 101}).status_code == 422
    assert client.get("/products", params={"limit": 0}).status_code == 422
