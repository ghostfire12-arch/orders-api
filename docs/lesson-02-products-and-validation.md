# Lesson 2: Products and validation

In lesson 1 the API only said hello. Now it accepts data from clients, checks
it, stores it and sends it back. This is the core of every real API.

## The big idea: never trust the client

Anyone can send anything to your API: a negative price, a name made of
spaces, text where a number should be. If you save that, your data is
broken. So every piece of incoming data is **validated** before your code
runs. In FastAPI you describe the rules once, in a *model*.

## Step 1: Models (`app/schemas.py`)

A model is a Python class that describes the shape of some data. We use
**Pydantic**, the library FastAPI is built on.

```python
class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    stock: int = Field(default=0, ge=0)
```

Reading it:

- `name: str` means the name must be text. `min_length=1` means not empty.
- `description: str | None` means text or nothing, and `default=None` makes it
  optional.
- `price: Decimal` with `gt=0` means greater than zero. `decimal_places=2`
  allows `19.99` but rejects `1.999`.
- `stock: int` with `ge=0` means zero or more. It defaults to 0.

### Why `Decimal` and not `float`?

Computers store floats in binary, and `0.1 + 0.2` gives `0.30000000000000004`.
Harmless for a game, a bug for money. `Decimal` does exact decimal arithmetic.
It travels as a string in JSON (`"19.99"`) so no precision is lost on the way.

### Two models: input and output

`Product` extends `ProductCreate` and adds an `id`. Clients send the first
shape and receive the second. The client must not choose the id, the server
does. Keeping input and output models separate is a habit worth building.

## Step 2: A place to keep products (`app/store.py`)

`InMemoryProductStore` keeps products in a dictionary. That is a deliberate
shortcut: the data disappears when the server restarts. In lesson 3 we swap
it for a real database. The routes only call `add`, `get` and `list`, so they
will barely change. Hiding storage behind a few methods is how you keep a
project easy to change.

## Step 3: Routes (`app/routers/products.py`)

A **router** groups related routes. `prefix="/products"` is added to every
path in the file.

| Request                    | What it does                 | Success code |
| -------------------------- | ---------------------------- | ------------ |
| `POST /products`           | create a product             | 201 Created  |
| `GET /products`            | list products, with paging   | 200 OK       |
| `GET /products/{id}`       | get one product              | 200 OK       |

Three kinds of input appear in these routes:

1. **Request body** (`payload: ProductCreate`): the JSON the client sends.
2. **Path parameter** (`/products/{product_id}`): part of the address.
3. **Query parameters** (`?skip=20&limit=10`): optional settings after `?`.

### Pagination

`limit` is capped at 100 (`le=100`). Without a cap, one request could ask for
a million rows and freeze the server. `skip` and `limit` let a client walk
through the list page by page.

### Status codes you now know

- `200` OK, `201` Created
- `404` Not Found: raised with `HTTPException` when an id does not exist
- `422` Unprocessable: FastAPI sends this by itself when validation fails

## What a validation error looks like

Request:

```
POST /products
{"name": "Notebook", "price": "-5"}
```

Response (HTTP 422), produced without you writing any error code:

```json
{
  "detail": [
    {
      "type": "greater_than",
      "loc": ["body", "price"],
      "msg": "Input should be greater than 0",
      "input": "-5",
      "ctx": {"gt": 0}
    }
  ]
}
```

`loc` tells the client exactly which field broke which rule.

## Step 4: Tests (`tests/`)

A test is a small program that uses your API and checks the result. It proves
the rules work today, and it protects you when you change code later.

```python
def test_price_must_be_greater_than_zero(client):
    assert make_product(client, price="0").status_code == 422
```

- `client` is a fixture: a helper pytest builds and hands to the test.
- `empty_store` in `conftest.py` runs before every test so tests never share
  data. Tests that depend on each other are a trap.
- `TestClient` calls the app directly, with no real server needed.

Run them:

```
.venv\Scripts\python.exe -m pytest -q
```

You should see `14 passed`.

## Try it yourself

1. Start the server, open `/docs`, click `POST /products`, choose "Try it
   out" and create a product. Then try a negative price and read the error.
2. Add a `sku` field (text, 3 to 20 characters) to `ProductCreate`. Run the
   tests, then add a test for it.
3. Add `GET /products?name=note` that returns products whose name contains
   the text. Write the test first, watch it fail, then make it pass.

## Words to remember

**Model**: the shape and rules of data. **Validation**: checking data against
the rules. **Router**: a group of routes. **Status code**: a number saying how
a request went. **Fixture**: a reusable test helper. **Pagination**: sending
data in pages.
