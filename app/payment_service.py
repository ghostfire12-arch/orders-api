import logging

from sqlalchemy.orm import Session

from app.order_repository import OrderRepository
from app.payment_providers import PaymentEvent
from app.payment_repository import PaymentRepository
from app.schemas import OrderStatus, PaymentStatus

logger = logging.getLogger(__name__)


def process_charge_success(db: Session, event: PaymentEvent) -> str:
    """Apply a verified "payment succeeded" event. Returns what happened.

    By the time this runs, the webhook's signature has already been checked.
    Even so, we do not simply believe it: we compare it with what WE recorded
    when the payment was started, and we make it safe to run twice.
    """
    payments = PaymentRepository(db)
    orders = OrderRepository(db)

    payment = payments.get_by_reference(event.reference)
    if payment is None:
        # Not ours (or a typo). Answer 200 anyway, otherwise the provider
        # keeps retrying for days. Log the reference only, never the body.
        logger.warning("Webhook for unknown payment reference %s", event.reference)
        return "unknown_reference"

    if payment.status != PaymentStatus.PENDING.value:
        return "already_processed"  # a duplicate delivery

    order = orders.get(payment.order_id)
    try:
        if event.amount_cents != payment.amount_cents or event.currency != payment.currency:
            # The customer paid a different amount than we asked for. Never
            # mark the order paid. Flag it for a human.
            payments.claim(payment, PaymentStatus.NEEDS_REVIEW)
            db.commit()
            logger.error(
                "Payment %s amount mismatch: expected %s %s, got %s %s",
                payment.reference, payment.amount_cents, payment.currency,
                event.amount_cents, event.currency,
            )
            return "amount_mismatch"

        if order is None or order.status != OrderStatus.PENDING.value:
            # Money arrived for an order that can no longer be paid (for
            # example the customer cancelled while paying). A human must
            # refund it. We never revive a cancelled order automatically.
            payments.claim(payment, PaymentStatus.NEEDS_REVIEW)
            db.commit()
            logger.error("Payment %s arrived for an order that is not payable", payment.reference)
            return "order_not_payable"

        # The decisive step. Two copies of the same webhook can arrive at the
        # same moment: only one wins this conditional update.
        if not payments.claim(payment, PaymentStatus.SUCCEEDED):
            db.rollback()
            return "already_processed"

        # Mark the order paid in the SAME transaction. A crash can never leave
        # "payment succeeded" with "order still pending".
        orders.change_status(order, OrderStatus.PAID, commit=False)
        db.commit()
        return "paid"
    except Exception:
        db.rollback()
        raise
