# Lesson 6: Payments and webhooks

Orders can now be paid. This is the most dangerous part of any shop, because
mistakes cost real money. The lesson is about one idea above all:

> **Never believe the customer. Never believe a request just because it
> claims to come from the payment company. Prove it.**

## How online payment really works

Your server never touches card details. A payment company (Paystack,
Flutterwave, Stripe) does that. The flow has five steps:

```
 Customer        Your API                    Payment company
    |                |                              |
    |-- pay order -->|                              |
    |                |-- "start a payment" -------->|   1. initialize
    |                |<-- checkout web address -----|
    |<-- address ----|                              |
    |------------------ opens the address, pays --->|   2. customer pays there
    |                |<-- WEBHOOK: "it was paid" ---|   3. the payment company calls YOU
    |                |   (verify, then mark paid)   |   4. you check it and update
    |-- sees order paid ->|                          |   5. the customer sees "paid"
```

A **webhook** is a web address on YOUR server that the payment company calls
when something happens. Instead of you asking "has it been paid yet?" again
and again (polling), they tell you.

### Why not trust the browser?

After paying, the customer's browser is sent back to your site ("callback").
You must NOT mark the order paid because of that. A customer can type that
address by hand without paying. Only the server-to-server webhook, after
verification, counts. Paystack's own docs say the same: webhooks are more
reliable than callbacks, because the customer's phone might lose signal or
switch off before the redirect.

## The provider layer (`app/payment_providers.py`)

Our code talks to a **shape**, not to Paystack directly:

```python
class PaymentProvider(Protocol):
    def initialize(...) -> str            # start a payment, return the checkout URL
    def signature_is_valid(body, sig)     # is this webhook genuine?
    def parse_event(payload)              # understand a successful charge
```

Two classes follow that shape:

- `FakeProvider`: charges nothing. For development and tests. You play the
  payment company yourself (see "Try it" below).
- `PaystackProvider`: calls the real Paystack API.

To support Flutterwave later, you write one more class. No route, table or
rule changes. This idea is called **abstraction**, and it is also why the tests
can run with no internet and no account.

Which provider runs is set by an environment variable (`PAYMENT_PROVIDER`).
If you choose `paystack` and forget `PAYSTACK_SECRET_KEY`, the server refuses
to start. A loud failure at startup is far better than a silent failure in
front of the first customer.

## Starting a payment (`POST /orders/{id}/pay`)

```python
reference = f"ord{order.id}-{secrets.token_hex(8)}"
provider.initialize(reference=reference, email=user.email,
                    amount_cents=order.total_cents, currency=config.CURRENCY)
```

- The **amount** comes from our database. The request has no amount field, and
  a test sends one to prove it is ignored. Another test checks the number we
  hand to the provider, because that is the number the customer is actually
  charged.
- The **reference** is a unique, unguessable code. It links OUR payment record
  to THEIR transaction. When they say "reference X was paid", we find our row.
- Only the owner of a pending order can start a payment.
- Money is in the **smallest unit**: `4448` means 44.48. Paystack uses kobo,
  and our cents-based storage from lesson 3 lines up with it.
- If the provider is down we answer **502 Bad Gateway** with a friendly
  message and log the details. The customer never sees internal errors.

### The payments table

One order can have several payment rows: a customer may abandon one checkout
and start another. Each row remembers what we asked for (`amount_cents`,
`currency`), so we can compare it later with what the provider reports.

## The webhook (`POST /webhooks/payments`)

Anyone on the internet can send a request to this address. There is no login,
because the payment company has no account with us. So the very first thing
we do is check a **signature**.

### What is a signature (HMAC)?

You and the provider share a secret key. For every webhook they compute:

```
signature = HMAC-SHA512(secret key, exact bytes of the request body)
```

and send it in the `x-paystack-signature` header (this is exactly what
Paystack documents). We compute the same thing and compare. A stranger does
not know the key, so they cannot produce a matching signature. Change one
character of the body and the signature no longer matches.

### Four details that matter

1. **Raw bytes.** We sign and check the exact bytes received. If we parsed the
   JSON first and re-wrote it, spacing or key order could change, and genuine
   signatures would fail. A test sends oddly-spaced JSON to prove we use the
   raw body.
2. **Constant-time comparison.** `hmac.compare_digest` takes the same time
   however many characters match. Plain `==` stops at the first wrong
   character, and an attacker can measure that tiny difference to guess a
   signature one character at a time.
3. **Check before reading.** Nothing in the body is trusted, or even parsed,
   until the signature passes.
4. **Size limit.** Real notifications are tiny. Bodies over 64 KB are refused
   with 413, so nobody can make the server swallow huge uploads.

### Even a genuine webhook is not blindly believed

After the signature passes, `payment_service.process_charge_success` checks:

| Situation                                   | What we do                                       |
| ------------------------------------------- | ------------------------------------------------ |
| reference we never issued                   | answer 200, change nothing, log it               |
| payment already processed (a repeat)        | answer 200, change nothing                       |
| amount or currency differs from our record  | payment becomes `needs_review`, order NOT paid   |
| order was cancelled meanwhile               | payment becomes `needs_review`, order stays cancelled |
| everything matches                          | payment `succeeded`, order `paid`                |

`needs_review` means "money arrived but something is wrong, a human must
decide" (usually a refund). We never revive a cancelled order automatically.

### Why answer 200 even when we ignore it?

Paystack keeps retrying any webhook that does not get a 200: every 3 minutes
four times, then hourly for 72 hours in live mode. Answering 4xx or 5xx for
something harmless creates days of repeated noise. We use 401 only for bad
signatures, and 400 for correctly signed but malformed events.

### Idempotency: safe to run twice

Providers send the same webhook more than once, and two copies can arrive at
the same moment. Handling must be **idempotent**: doing it twice has the same
effect as doing it once.

```python
update(PaymentRow).where(PaymentRow.id == payment.id,
                         PaymentRow.status == "pending")
                  .values(status="succeeded", paid_at=now)
```

This is the "check and change in one step" pattern from lesson 5. Only one
copy can change the row from `pending`, so the order is marked paid exactly
once.

### One transaction

The payment change and the order change are saved together with one
`commit()`. If the server crashes between them, both roll back, the provider
retries, and the retry succeeds. A test makes the second update crash on
purpose and checks that nothing was half-saved.

## Going live with Paystack

1. Create a Paystack account and get your **test** secret key
   (`sk_test_...`) from the dashboard.
2. Set the environment variables:

   ```
   $env:PAYMENT_PROVIDER = "paystack"
   $env:PAYSTACK_SECRET_KEY = "sk_test_..."
   ```

   Never paste this key into a chat, a file in git, or a screenshot. It can
   charge and refund your customers.
3. In the Paystack dashboard, set the webhook URL to
   `https://your-domain/webhooks/payments`. It must be public and use HTTPS.
   `localhost` cannot receive webhooks.
4. Pay with Paystack's test cards and watch the order become `paid`.

**Honest note:** the Paystack class is tested against a pretend Paystack
server, built from their documentation (the request we send and the replies
we expect). It has NOT been run against the real service, because that needs
your account. Test with your test key before you trust it.

## Try it yourself with the fake provider

1. Start the server with a secret you choose:

   ```
   $env:PAYMENT_WEBHOOK_SECRET = "any-long-random-text"
   .venv\Scripts\python.exe -m uvicorn app.main:app
   ```
2. In `/docs`: register, log in, create an order (an admin must create products
   first), then `POST /orders/{id}/pay`. Copy the `reference` and the `amount`.
3. In a second terminal, with the same secret set, play the payment company:

   ```
   .venv\Scripts\python.exe -m app.simulate_payment ord1-abc123 3998
   ```

   (the amount is in the smallest unit: 3998 means 39.98)
4. `GET /orders/1`. It is now `paid`.
5. Run the same command again. It answers `already_processed`.
6. Run it with a wrong amount such as `100` on a new payment. The payment turns
   `needs_review` and the order stays pending.

Real output from the first run of that flow:

```
POST /orders/1/pay   ->  {"reference": "ord1-5a2f04bef89889e6", "amount": "39.98",
                          "currency": "NGN", "status": "pending", ...}
forged webhook       ->  401 {"detail": "Invalid signature"}   (order still pending)
genuine webhook      ->  200 {"status": "paid"}
the same one again   ->  200 {"status": "already_processed"}
```

## Tests worth reading (`tests/test_payments.py`)

- Forged, missing and wrong-secret signatures are all rejected (401), and the
  order does not change.
- **A captured signature cannot be reused.** An attacker who sees a real
  signature for a 1-kobo payment cannot attach it to a body claiming the full
  amount.
- Replays, wrong amounts, wrong currencies, unknown references, cancelled
  orders and malformed events each have a test.

### Do the tests really protect us?

As in lesson 5, I broke six rules on purpose and checked that the tests notice:

1. skip the signature check
2. ignore the amount actually paid
3. revive a cancelled order when money arrives
4. process the same webhook twice
5. charge the provider the wrong amount
6. let a stranger pay for someone else's order

The first run **missed number 5**: our stored record stayed correct while the
provider would have charged a different amount. The fix was a new test that
checks exactly what we hand to the provider. All six are caught now. The
script that does this is a good habit to copy for any rule you care about.

## What we skipped on purpose (real shops need these)

- **Verify with the provider.** Paystack offers `GET /transaction/verify/{reference}`
  to double-check a payment. A strong extra layer on top of the signature.
- **IP allowlist.** Paystack publishes the addresses it sends from. Allowing
  only those adds protection, but behind a proxy it needs care so that nobody
  can fake the forwarded address.
- **Refunds.** `needs_review` payments need a refund flow.
- **Rate limiting** on starting payments, and **HTTPS** everywhere.
- **Failed and abandoned payments**, expiry of old pending payments.
- **Receipts and emails**, partial payments, other currencies.

## Words to remember

**Webhook**: an address on your server that another service calls.
**HMAC / signature**: a code proving a message came from someone with the
shared secret and was not changed. **Idempotent**: safe to repeat.
**Reference**: a unique code linking your record to the provider's.
**Abstraction**: code that talks to a shape, so the details can be swapped.
**Replay attack**: re-sending a real message. **Mutation testing**: breaking
code on purpose to see if the tests notice. **502**: the service behind us
failed.
