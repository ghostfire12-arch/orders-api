from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

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
