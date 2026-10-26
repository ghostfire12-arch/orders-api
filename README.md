# Orders API

A small ordering API built with Python and FastAPI: accounts, products,
orders and payments. Built step by step, with a lesson for each step in
`docs/`.

## Run it

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-dev.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs for the interactive documentation.

## Run the tests

```
.venv\Scripts\python.exe -m pytest -q
```

## Database

Data is stored in a SQLite file, `orders.db`, created on first start (it is
git-ignored). Set the `DATABASE_URL` environment variable to use another
database.

## Configuration

Settings come from environment variables (see `.env.example`). Set
`SECRET_KEY` to a long random value; without it a random key is used and
logins reset on every restart.

## First admin

```
.venv\Scripts\python.exe -m app.create_admin
```

## Endpoints

| Method | Path             | Auth    | Description                  |
| ------ | ---------------- | ------- | ---------------------------- |
| GET    | `/health`        | none    | Service health check         |
| POST   | `/auth/register` | none    | Create an account            |
| POST   | `/auth/login`    | none    | Get an access token          |
| GET    | `/users/me`      | token   | The logged-in user           |
| POST   | `/products`      | admin   | Create a product (validated) |
| GET    | `/products`      | none    | List products with paging    |
| GET    | `/products/{id}` | none    | Get one product              |
| POST   | `/orders`        | token   | Create an order              |
| GET    | `/orders`        | token   | List my orders               |
| GET    | `/orders/{id}`   | token   | Get one order (owner/admin)  |
| POST   | `/orders/{id}/cancel` | token | Cancel my pending order    |
| GET    | `/admin/orders`  | admin   | List all orders, filter by status |
| PATCH  | `/orders/{id}/status` | admin | Change an order's status   |

## Lessons

1. [A first API that runs](docs/lesson-01-hello-api.md)
2. [Products and validation](docs/lesson-02-products-and-validation.md)
3. [A real database](docs/lesson-03-real-database.md)
4. [Accounts, password hashing and login](docs/lesson-04-accounts-and-login.md)
5. [Orders](docs/lesson-05-orders.md)
