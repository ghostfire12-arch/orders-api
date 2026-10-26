# Lesson 5: Orders

This is where the project becomes a shop. A customer picks products, the API
works out the price, reserves the stock, and an admin moves the order from
"pending" to "delivered". It is also where most real-world API bugs live, so
this lesson is about **thinking like someone trying to cheat**.

## The data: two tables

An order has many items, so we use two tables linked together.

```
orders                           order_items
------                           -----------
id                               id
user_id  -> users.id             order_id  -> orders.id
status                           product_id -> products.id
total_cents                      product_name      (copied)
created_at                       unit_price_cents  (copied)
                                 quantity
```

- A **foreign key** (`user_id -> users.id`) is a column that points at a row in
  another table. The database refuses an order for a user who does not exist.
  SQLite ignores foreign keys unless you switch them on, so `database.py`
  runs `PRAGMA foreign_keys=ON` for every connection. A test proves it works.
- **One-to-many**: `OrderRow.items` is a list of `OrderItemRow`. With
  `lazy="selectin"` the items load together with the order, so listing 20
  orders does not trigger 20 more queries (the "N+1 problem").

### Snapshots: copy the price, do not point at it

Each item stores `product_name` and `unit_price_cents` **at the time of
purchase**. If the shop raises the Notebook's price tomorrow, last week's
order must still say 19.99. Never rebuild an old receipt from live prices.
`test_the_price_paid_is_frozen_at_purchase_time` checks this.

## Rule 1: never trust the client with money

```python
class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int
```

There is no `price` field. The client says WHAT and HOW MANY. The server looks
up the price and adds up the total. If the client could send a price, anyone
could buy everything for one cent. Extra fields in the request (like
`unit_price`) are simply ignored, and a test sends one to prove it.

For the same reason there is no `user_id` in the request. The customer is
whoever the **token** says. Otherwise anyone could place orders as somebody
else.

## Rule 2: the stock must be safe

Imagine one notebook left and two customers click "buy" at the same moment.
A naive version does:

```
1. read the stock      -> both see 1
2. check stock >= 1    -> both pass
3. write stock - 1     -> both write 0   (two people bought one notebook)
```

The fix is one SQL statement that checks and subtracts together:

```python
update(ProductRow)
  .where(ProductRow.id == product.id, ProductRow.stock >= quantity)
  .values(stock=ProductRow.stock - quantity)
```

The database runs it as a single step. If it changed zero rows, there was not
enough stock, and we raise `InsufficientStock`. This is called an **atomic**
update.

## Rule 3: all or nothing (transactions)

An order with three items must not be half-saved. If item three is out of
stock, the stock already taken for items one and two must come back.

A **transaction** groups several database changes so they succeed together or
fail together. In `OrderRepository.create`, nothing is final until
`commit()`. If anything raises an error, `rollback()` undoes everything since
the last commit. `test_orders_are_all_or_nothing` creates exactly that
situation.

## Rule 4: who may see what (IDOR)

The most common serious API bug is **IDOR**, insecure direct object
reference. It looks like this:

```
GET /orders/17      <- a customer changes 17 to 18 and reads a stranger's order
```

Our defenses:

- `GET /orders` filters by the logged-in user's id. You only get your own.
- `GET /orders/{id}` returns the order only to its owner or an admin.
- For anyone else the answer is **404 Not Found, not 403 Forbidden**. A 403
  would confirm the order exists. With 404, "someone else's order" and "no such
  order" look identical. A test compares the two responses byte for byte.

## Rule 5: a status is a state machine

Orders do not jump around. `order_repository.py` defines the allowed moves:

```
pending -> paid -> shipped -> delivered
   |        |
   +--------+--> cancelled
```

```python
ALLOWED_TRANSITIONS = {
    PENDING:   {PAID, CANCELLED},
    PAID:      {SHIPPED, CANCELLED},
    SHIPPED:   {DELIVERED},
    DELIVERED: set(),
    CANCELLED: set(),
}
```

Anything else is **409 Conflict**: "Cannot change status from pending to
shipped". Writing the rules as data, not as a pile of `if` statements, makes
them easy to read, easy to test, and easy to change.

`OrderStatus` is an **enum**: a fixed list of allowed values. Sending
`"teleported"` is rejected with 422 before your code runs.

### Cancelling gives the stock back, exactly once

Cancelling restores the stock. If two cancel requests arrive together, stock
must not be restored twice. So the status change is also conditional:

```python
update(OrderRow).where(OrderRow.id == order.id, OrderRow.status == current)
                .values(status=new_status)
```

Only one request can win that race. The loser changes zero rows and gets a 409.

## The routes

| Request                        | Who             | What                              |
| ------------------------------ | --------------- | --------------------------------- |
| `POST /orders`                 | logged in       | create an order (201)             |
| `GET /orders`                  | logged in       | my orders, newest first, paged    |
| `GET /orders/{id}`             | owner or admin  | one order                         |
| `POST /orders/{id}/cancel`     | owner           | cancel while still pending        |
| `GET /admin/orders?status=paid`| admin           | all orders, optional filter       |
| `PATCH /orders/{id}/status`    | admin           | move to the next status           |

A real response:

```json
{
  "id": 1,
  "user_id": 2,
  "status": "pending",
  "total": "44.48",
  "created_at": "2026-10-26T12:57:42.424595Z",
  "items": [
    {"product_id": 1, "product_name": "Notebook", "unit_price": "19.99",
     "quantity": 2, "line_total": "39.98"},
    {"product_id": 2, "product_name": "Pen", "unit_price": "1.50",
     "quantity": 3, "line_total": "4.50"}
  ]
}
```

And the errors:

```json
{"detail": "Not enough stock for Notebook: 8 available"}
{"detail": "Cannot change status from pending to shipped"}
```

## A bug we found while writing this lesson

The first version showed `created_at` without a time zone marker, because
SQLite forgets time zones. A client cannot tell if `12:57` means Lagos or
London. `to_order` now labels it UTC again (`...Z`), and a test guards it.
Lesson: look at your real output, not only at passing tests.

## Do tests really protect you? (mutation testing)

Before finishing, I broke two rules on purpose and ran the tests:

1. Removed the ownership check from `GET /orders/{id}`.
2. Removed `stock >= quantity` from the atomic update.

Four tests failed, which is what we want: the tests noticed. A test suite that
cannot fail is worthless. Try this yourself on any rule you care about.

## Tests got faster too

Argon2 is slow on purpose, so a suite that registers many users crawled (60
seconds). `conftest.py` now swaps in the cheapest Argon2 settings **for tests
only**. The real settings are untouched. The suite runs in about 9 seconds.

## Run it

```
.venv\Scripts\python.exe -m pytest -q
```

You should see `91 passed`.

## What we skipped on purpose

- **Payment.** Orders go to "paid" by an admin for now. Step 6 connects a real
  payment flow.
- **Concurrency proof.** SQLite allows one writer at a time, so our race tests
  are about correct logic. On PostgreSQL the same atomic updates matter even
  more.
- **Money in other currencies, taxes, shipping, discounts.**
- **Emails** when status changes.
- **Pagination totals** (how many pages exist).

## Try it yourself

1. In `/docs`, register two users. As user A place an order, then as user B
   request `GET /orders/1`. What do you get, and why not 403?
2. Add a `note` field (optional text, max 200 characters) to orders, through
   the schema, the model and the response. Delete `orders.db` first. Why is
   that needed? (Hint: lesson 3, migrations.)
3. Add a rule: an order total may not exceed 1,000,000. Write the test first.
4. Break a rule yourself, as in the mutation test above, and watch which test
   fails.

## Words to remember

**Foreign key**: a column pointing at another table's row. **One-to-many**:
one order, many items. **Snapshot**: a copy of data as it was. **Atomic**:
done in one indivisible step. **Transaction**: a group of changes that succeed
or fail together. **Rollback**: undo the group. **IDOR**: reading someone
else's data by guessing an id. **State machine**: allowed moves between
statuses. **Enum**: a fixed list of allowed values. **409**: the request clashes
with the current state.
