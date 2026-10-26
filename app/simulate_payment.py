"""Pretend to be the payment company, in development.

With the FAKE provider nobody can really pay, so this script plays the
provider's part: it sends the server a signed "charge.success" notification,
exactly like Paystack would after a customer pays.

1. Start the server with a known webhook secret:

       $env:PAYMENT_WEBHOOK_SECRET = "any-long-random-text"
       .venv\\Scripts\\python.exe -m uvicorn app.main:app

2. Start a payment (POST /orders/{id}/pay in /docs) and copy the reference
   and amount from the response. The amount is in the smallest unit (4448
   means 44.48).

3. In another terminal, with the SAME secret set:

       .venv\\Scripts\\python.exe -m app.simulate_payment REFERENCE 4448
"""

import argparse
import json
import os
import sys

import httpx

from app.payment_providers import FakeProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a signed fake payment notification.")
    parser.add_argument("reference", help="the reference returned by POST /orders/{id}/pay")
    parser.add_argument("amount", type=int, help="amount in the smallest unit, e.g. 4448 for 44.48")
    parser.add_argument("--currency", default=os.getenv("CURRENCY", "NGN"))
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhooks/payments")
    args = parser.parse_args()

    secret = os.getenv("PAYMENT_WEBHOOK_SECRET")
    if not secret:
        print("Set PAYMENT_WEBHOOK_SECRET to the same value the server is using.")
        return 1

    event = {
        "event": "charge.success",
        "data": {
            "status": "success",
            "reference": args.reference,
            "amount": args.amount,
            "currency": args.currency.upper(),
        },
    }
    # Sign the exact bytes we send. The server checks the signature against
    # the raw body, so we must not let the HTTP library re-encode it.
    body = json.dumps(event).encode()
    provider = FakeProvider(secret)
    response = httpx.post(
        args.url,
        content=body,
        headers={"content-type": "application/json", provider.signature_header: provider.sign(body)},
        timeout=10.0,
    )
    print(response.status_code, response.text)
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
