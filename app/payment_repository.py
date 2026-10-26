from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import PaymentRow
from app.repository import from_cents
from app.schemas import Payment, PaymentStatus


def _as_utc(value: datetime | None) -> datetime | None:
    # SQLite forgets time zones; we always store UTC (see to_order).
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def to_payment(row: PaymentRow) -> Payment:
    return Payment(
        id=row.id,
        order_id=row.order_id,
        reference=row.reference,
        provider=row.provider,
        amount=from_cents(row.amount_cents),
        currency=row.currency,
        status=PaymentStatus(row.status),
        created_at=_as_utc(row.created_at),
        paid_at=_as_utc(row.paid_at),
    )


class PaymentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        order_id: int,
        reference: str,
        provider: str,
        amount_cents: int,
        currency: str,
        authorization_url: str,
    ) -> PaymentRow:
        payment = PaymentRow(
            order_id=order_id,
            reference=reference,
            provider=provider,
            amount_cents=amount_cents,
            currency=currency,
            authorization_url=authorization_url,
            status=PaymentStatus.PENDING.value,
        )
        self.db.add(payment)
        self.db.commit()
        self.db.refresh(payment)
        return payment

    def get_by_reference(self, reference: str) -> PaymentRow | None:
        return self.db.scalar(select(PaymentRow).where(PaymentRow.reference == reference))

    def list_for_order(self, order_id: int) -> list[PaymentRow]:
        query = select(PaymentRow).where(PaymentRow.order_id == order_id).order_by(PaymentRow.id)
        return list(self.db.scalars(query))

    def claim(self, payment: PaymentRow, new_status: PaymentStatus) -> bool:
        """Move a payment out of "pending", but only if it is STILL pending.

        Returns True if this call made the change, False if someone else got
        there first. Providers send the same webhook more than once, and two
        copies can arrive at the same moment. Only one of them can win this
        conditional update, so a payment is processed exactly once.

        Does not commit: the caller commits together with the order change.
        """
        values: dict[str, object] = {"status": new_status.value}
        if new_status is PaymentStatus.SUCCEEDED:
            values["paid_at"] = datetime.now(timezone.utc)
        result = self.db.execute(
            update(PaymentRow)
            .where(PaymentRow.id == payment.id, PaymentRow.status == PaymentStatus.PENDING.value)
            .values(**values)
        )
        return result.rowcount == 1
