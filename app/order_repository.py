from datetime import timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import OrderItemRow, OrderRow, ProductRow
from app.repository import from_cents
from app.schemas import Order, OrderCreate, OrderItem, OrderStatus

# The status "state machine": from each status, which ones may come next.
# Orders only move forward. "delivered" and "cancelled" are the end.
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}


class ProductNotFound(Exception):
    def __init__(self, product_id: int) -> None:
        super().__init__(product_id)
        self.product_id = product_id


class InsufficientStock(Exception):
    def __init__(self, product_name: str, available: int) -> None:
        super().__init__(product_name)
        self.product_name = product_name
        self.available = available


class InvalidTransition(Exception):
    def __init__(self, current: str, requested: str) -> None:
        super().__init__(current, requested)
        self.current = current
        self.requested = requested


def to_order(row: OrderRow) -> Order:
    """Convert database rows into the Order shape the API returns."""
    created_at = row.created_at
    if created_at.tzinfo is None:
        # SQLite forgets timezones. We always store UTC, so label it as UTC
        # again, otherwise clients cannot tell what time zone the value is in.
        created_at = created_at.replace(tzinfo=timezone.utc)
    return Order(
        id=row.id,
        user_id=row.user_id,
        status=OrderStatus(row.status),
        total=from_cents(row.total_cents),
        created_at=created_at,
        items=[
            OrderItem(
                product_id=item.product_id,
                product_name=item.product_name,
                unit_price=from_cents(item.unit_price_cents),
                quantity=item.quantity,
                line_total=from_cents(item.unit_price_cents * item.quantity),
            )
            for item in row.items
        ],
    )


class OrderRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user_id: int, data: OrderCreate) -> OrderRow:
        """Create an order, take the stock and work out the total.

        Everything happens inside ONE transaction. Either the whole order is
        saved, or nothing is. If the third item is out of stock, the stock we
        already took for the first two is automatically given back.
        """
        order = OrderRow(user_id=user_id, status=OrderStatus.PENDING.value, total_cents=0)
        total_cents = 0
        try:
            for requested in data.items:
                product = self.db.get(ProductRow, requested.product_id)
                if product is None:
                    raise ProductNotFound(requested.product_id)

                # Take the stock with ONE statement that checks and subtracts
                # together. A "read the stock, then write it" approach has a
                # gap: two customers could both read "1 left" and both buy it.
                taken = self.db.execute(
                    update(ProductRow)
                    .where(ProductRow.id == product.id, ProductRow.stock >= requested.quantity)
                    .values(stock=ProductRow.stock - requested.quantity)
                )
                if taken.rowcount != 1:
                    self.db.refresh(product)
                    raise InsufficientStock(product.name, product.stock)

                # The price comes from OUR database, never from the client.
                total_cents += product.price_cents * requested.quantity
                order.items.append(
                    OrderItemRow(
                        product_id=product.id,
                        product_name=product.name,
                        unit_price_cents=product.price_cents,
                        quantity=requested.quantity,
                    )
                )

            order.total_cents = total_cents
            self.db.add(order)
            self.db.commit()
        except Exception:
            self.db.rollback()  # undo every stock change made above
            raise
        self.db.refresh(order)
        return order

    def get(self, order_id: int) -> OrderRow | None:
        return self.db.get(OrderRow, order_id)

    def list_for_user(self, user_id: int, skip: int, limit: int) -> list[OrderRow]:
        query = (
            select(OrderRow)
            .where(OrderRow.user_id == user_id)
            .order_by(OrderRow.id.desc())  # newest first
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(query))

    def list_all(self, status: OrderStatus | None, skip: int, limit: int) -> list[OrderRow]:
        query = select(OrderRow).order_by(OrderRow.id.desc()).offset(skip).limit(limit)
        if status is not None:
            query = query.where(OrderRow.status == status.value)
        return list(self.db.scalars(query))

    def change_status(self, order: OrderRow, new_status: OrderStatus) -> OrderRow:
        current = OrderStatus(order.status)
        if new_status not in ALLOWED_TRANSITIONS[current]:
            raise InvalidTransition(current.value, new_status.value)

        try:
            # Change the status only if it is STILL what we think it is. If two
            # requests race (for example, two cancels at once), only one wins,
            # so stock is never given back twice.
            changed = self.db.execute(
                update(OrderRow)
                .where(OrderRow.id == order.id, OrderRow.status == current.value)
                .values(status=new_status.value)
            )
            if changed.rowcount != 1:
                raise InvalidTransition(current.value, new_status.value)

            if new_status is OrderStatus.CANCELLED:
                for item in order.items:
                    self.db.execute(
                        update(ProductRow)
                        .where(ProductRow.id == item.product_id)
                        .values(stock=ProductRow.stock + item.quantity)
                    )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(order)
        return order
