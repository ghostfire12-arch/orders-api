from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRow(Base):
    """One row in the "users" table."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # unique=True makes the database itself refuse a second account with the
    # same email, even if two requests arrive at the same moment.
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    # We store the hash, never the password.
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class OrderRow(Base):
    """One row in the "orders" table: who ordered, the status, the total."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    # A foreign key points at a row in another table. It makes the database
    # refuse an order that belongs to a user who does not exist.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    total_cents: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # One order has many items. lazy="selectin" loads the items together with
    # the order, so showing 20 orders does not run 20 extra queries.
    items: Mapped[list["OrderItemRow"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OrderItemRow.id",
    )


class OrderItemRow(Base):
    """One line of an order: a product, a quantity, and the price paid."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    # Snapshots: we copy the name and price at the moment of purchase. If the
    # shop changes the price tomorrow, yesterday's order must not change.
    product_name: Mapped[str] = mapped_column(String(100))
    unit_price_cents: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[int]

    order: Mapped["OrderRow"] = relationship(back_populates="items")


class PaymentRow(Base):
    """One attempt to pay for an order.

    An order can have several payment rows (a customer may abandon one
    checkout and start another). Only a confirmed one moves the order to paid.
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    # The unique code that links OUR record to the provider's. When the
    # provider tells us "reference X was paid", this is how we find the row.
    reference: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(20))
    # What we asked the customer to pay. We compare the provider's report to
    # these values, we do not just believe it.
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    authorization_url: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductRow(Base):
    """One row in the "products" table.

    Do not confuse this with the Product schema. A schema describes JSON sent
    over the web. A model describes a table stored in the database. They are
    separate on purpose, so changing one does not break the other.
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    # Money is stored as a whole number of cents: 19.99 becomes 1999. Whole
    # numbers are exact in every database, unlike decimals or floats.
    price_cents: Mapped[int] = mapped_column(BigInteger)
    stock: Mapped[int] = mapped_column(default=0)
