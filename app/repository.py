from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProductRow
from app.schemas import Product, ProductCreate


def to_cents(price: Decimal) -> int:
    # scaleb(2) multiplies by 10**2 exactly: Decimal("19.99") -> 1999.
    # Validation already guarantees at most two decimal places.
    return int(price.scaleb(2))


def from_cents(cents: int) -> Decimal:
    # The reverse: 1999 -> Decimal("19.99"), 1990 -> Decimal("19.90").
    return Decimal(cents).scaleb(-2)


def to_product(row: ProductRow) -> Product:
    """Convert a database row into the Product shape the API returns."""
    return Product(
        id=row.id,
        name=row.name,
        description=row.description,
        price=from_cents(row.price_cents),
        stock=row.stock,
    )


class ProductRepository:
    """All the database work for products lives in this one class.

    The routes call add, get and list and know nothing about SQL. This is the
    same three-method shape the in-memory store had in lesson 2, which is why
    swapping storage barely touched the routes.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, data: ProductCreate) -> Product:
        row = ProductRow(
            name=data.name,
            description=data.description,
            price_cents=to_cents(data.price),
            stock=data.stock,
        )
        self.db.add(row)  # stage the new row
        self.db.commit()  # write it to the database for real
        self.db.refresh(row)  # reload it so row.id (chosen by the database) is set
        return to_product(row)

    def get(self, product_id: int) -> Product | None:
        row = self.db.get(ProductRow, product_id)
        return to_product(row) if row else None

    def list(self, skip: int, limit: int) -> list[Product]:
        # SELECT * FROM products ORDER BY id LIMIT :limit OFFSET :skip
        query = select(ProductRow).order_by(ProductRow.id).offset(skip).limit(limit)
        return [to_product(row) for row in self.db.scalars(query)]
