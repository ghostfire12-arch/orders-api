# Lesson 3: A real database

In lesson 2 products lived in a Python dictionary, so every restart erased
them. Now they live in a database file on disk.

## What is a database?

A database stores data in **tables**, like spreadsheets:

| id | name     | description | price_cents | stock |
| -- | -------- | ----------- | ----------- | ----- |
| 1  | Notebook | A5          | 1999        | 10    |
| 2  | Pen      | blue        | 150         | 200   |

- A **table** holds one kind of thing (products).
- A **row** is one item. A **column** is one property.
- The **primary key** (`id`) is a number that identifies a row. The database
  assigns it, so two rows never share one.
- **SQL** is the language you use to ask the database for things:
  `SELECT * FROM products WHERE id = 1`.

## The tools

- **SQLite**: a database that is just one file (`orders.db`). It is built into
  Python, needs no server, and is perfect for learning and small apps.
- **SQLAlchemy**: a library that lets you work with tables using Python
  classes, and writes the SQL for you. This is called an **ORM** (object
  relational mapper).

## What changed

```
app/
  database.py     connection, sessions, table creation
  models.py       the table definition (ProductRow)
  repository.py   all the database work for products
  schemas.py      unchanged: the shape of JSON over the web
  routers/        routes now ask for a repository
  main.py         creates the tables when the server starts
```

`store.py` from lesson 2 is gone.

## Step 1: Connect (`app/database.py`)

- `DATABASE_URL = "sqlite:///./orders.db"` says where the data lives. It can be
  overridden with an environment variable, so later the same code can talk to
  PostgreSQL by changing one setting.
- The **engine** is the connection.
- A **session** is one conversation with the database: read, change, then
  **commit** (save for real) or **roll back** (undo). `SessionLocal` creates
  them.
- `get_db()` opens a session for one request and always closes it, even if the
  route crashes. The `try / finally` is what guarantees the cleanup.

## Step 2: Describe the table (`app/models.py`)

```python
class ProductRow(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    price_cents: Mapped[int] = mapped_column(BigInteger)
```

Each class attribute is a column. SQLAlchemy creates the table from this
class. At startup `init_db()` runs `create_all`, which creates any missing
tables and leaves existing ones alone.

### Schema or model, what is the difference?

| Schema (`schemas.py`)         | Model (`models.py`)           |
| ----------------------------- | ----------------------------- |
| shape of JSON on the web      | shape of a table on disk      |
| has rules like `gt=0`         | has column types              |
| price is a `Decimal`          | price is whole cents          |

Keeping them separate means you can change how you store data without
breaking everyone who uses your API.

### Why store money as cents?

`19.99` becomes `1999`. Whole numbers are exact in every database. Many
databases have no true decimal type, and floats cannot hold 0.1 exactly. So
the usual professional answer is: store the smallest unit as an integer and
convert at the edges. `to_cents` and `from_cents` in `repository.py` do that.

## Step 3: The repository (`app/repository.py`)

A **repository** is one class that holds all the database work for one kind of
thing. The routes call `add`, `get` and `list` and never see SQL.

```python
def add(self, data):
    row = ProductRow(name=data.name, price_cents=to_cents(data.price), ...)
    self.db.add(row)       # stage it
    self.db.commit()       # save it to disk
    self.db.refresh(row)   # reload it, so row.id (chosen by the database) is set
```

`list` builds the query `SELECT ... ORDER BY id LIMIT :limit OFFSET :skip`.

Because lesson 2 already hid storage behind these three methods, the routes
changed by only a few lines. That is the payoff of keeping layers separate.

## Step 4: Dependency injection (`app/routers/products.py`)

```python
def create_product(payload: ProductCreate, repo: Repo): ...
```

The route does not create its own repository. It *asks* for one, and FastAPI
builds it: `get_repository` needs a session, which comes from `get_db`. This
pattern is called **dependency injection**. It matters for testing, because a
test can replace `get_db` with a throwaway database.

## Step 5: Testing with a throwaway database

`tests/conftest.py` creates a database that lives only in memory
(`sqlite://`) and uses `app.dependency_overrides` to swap it in. Every test
gets a fresh empty database, and your real `orders.db` is never touched.

Two new tests in `tests/test_persistence.py` prove the point of this lesson:

- Prices are stored as cents in the real row.
- Data written by one "run" is still there for the next one (a real file, an
  engine closed and reopened).

Run everything:

```
.venv\Scripts\python.exe -m pytest -q
```

You should see `17 passed`.

## See it for yourself

1. Start the server, create a product in `/docs`.
2. Stop the server (Ctrl+C) and start it again.
3. `GET /products`. The product is still there.
4. A file called `orders.db` now sits in the project folder. It is listed in
   `.gitignore`, so it is never uploaded to GitHub.

To look inside the file:

```
.venv\Scripts\python.exe -c "import sqlite3; print(sqlite3.connect('orders.db').execute('select * from products').fetchall())"
```

## What we skipped on purpose

- **Migrations.** `create_all` creates tables but cannot *change* an existing
  one. When you add a column to a live database you use a migration tool
  (Alembic). We will add it once the tables settle.
- **Update and delete.** Coming with orders.

## Try it yourself

1. Add a `created_at` timestamp column to `ProductRow`. Delete `orders.db` and
   restart so the table is rebuilt. (This is exactly why migrations exist.)
2. Write a test that creates three products and checks `skip` and `limit`
   against the database.
3. Open the database with the one-line command above after creating a product
   and find the price. Is it `19.99` or `1999`?

## Words to remember

**Table, row, column, primary key**: how data is organized. **SQL**: the
language of databases. **ORM**: Python classes instead of hand-written SQL.
**Session / commit / rollback**: one conversation with the database, and how
you save or undo it. **Repository**: one class owning the database work.
**Dependency injection**: asking for what you need instead of building it.
