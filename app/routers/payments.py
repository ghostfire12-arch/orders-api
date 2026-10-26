import json
import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app import config
from app.database import get_db
from app.deps import CurrentUser
from app.payment_providers import (
    MalformedEvent,
    PaymentProvider,
    PaymentProviderError,
    get_payment_provider,
)
from app.payment_repository import PaymentRepository, to_payment
from app.payment_service import process_charge_success
from app.repository import from_cents
from app.routers.orders import OrderRepo, load_visible_order
from app.schemas import OrderStatus, Payment, PaymentStart, PaymentStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payments"])

# A payment notification is a few hundred bytes. Refuse anything bigger.
MAX_WEBHOOK_BYTES = 64 * 1024

Provider = Annotated[PaymentProvider, Depends(get_payment_provider)]


def get_payment_repository(db: Annotated[Session, Depends(get_db)]) -> PaymentRepository:
    return PaymentRepository(db)


PaymentRepo = Annotated[PaymentRepository, Depends(get_payment_repository)]


@router.post(
    "/orders/{order_id}/pay",
    response_model=PaymentStart,
    status_code=status.HTTP_201_CREATED,
)
def start_payment(
    order_id: int,
    user: CurrentUser,
    orders: OrderRepo,
    payments: PaymentRepo,
    provider: Provider,
) -> PaymentStart:
    order = orders.get(order_id)
    # Only the owner pays for an order. Anyone else: "not found".
    if order is None or order.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.status != OrderStatus.PENDING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending orders can be paid")

    # A unique, unguessable reference ties our record to the provider's.
    reference = f"ord{order.id}-{secrets.token_hex(8)}"
    try:
        # The AMOUNT comes from our database, never from the request.
        authorization_url = provider.initialize(
            reference=reference,
            email=user.email,
            amount_cents=order.total_cents,
            currency=config.CURRENCY,
        )
    except PaymentProviderError as error:
        logger.error("Payment provider failed for order %s: %s", order.id, error)
        # 502 Bad Gateway: the problem is the service behind us, not the client.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The payment service is unavailable. Please try again shortly.",
        ) from None

    payment = payments.create(
        order_id=order.id,
        reference=reference,
        provider=provider.name,
        amount_cents=order.total_cents,
        currency=config.CURRENCY,
        authorization_url=authorization_url,
    )
    return PaymentStart(
        reference=payment.reference,
        authorization_url=payment.authorization_url,
        amount=from_cents(payment.amount_cents),
        currency=payment.currency,
        status=PaymentStatus(payment.status),
    )


@router.get("/orders/{order_id}/payments", response_model=list[Payment])
def list_order_payments(
    order_id: int, user: CurrentUser, orders: OrderRepo, payments: PaymentRepo
) -> list[Payment]:
    order = load_visible_order(orders, order_id, user)
    return [to_payment(row) for row in payments.list_for_order(order.id)]


@router.post("/webhooks/payments")
async def payment_webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    provider: Provider,
) -> dict[str, str]:
    """Where the payment company tells us "this customer paid".

    Anyone on the internet can send a request to this address, so the very
    first job is proving it really came from the provider. There is no login
    here: the SIGNATURE is the proof.
    """
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Body too large")

    # We need the RAW bytes. The signature was made over the exact bytes the
    # provider sent. If we parsed the JSON first and re-wrote it, spacing or
    # key order could change and a genuine signature would stop matching.
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Body too large")

    if not provider.signature_is_valid(body, request.headers.get(provider.signature_header)):
        # Nothing about the body is trusted, or even read, before this check.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    try:
        event = provider.parse_event(json.loads(body))
    except (ValueError, MalformedEvent):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed event") from None

    if event is None:
        # A real event we do not care about (refunds, transfers...). Answer
        # 200 so the provider does not keep re-sending it.
        return {"status": "ignored"}

    # The database work is regular (blocking) code, so run it off the event loop.
    outcome = await run_in_threadpool(process_charge_success, db, event)
    return {"status": outcome}
