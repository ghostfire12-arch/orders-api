from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import ProductRow
from app.repository import ProductRepository, from_cents, to_cents
from app.schemas import ProductCreate


def test_money_is_stored_as_whole_cents(client, session_factory):
    client.post("/products", json={"name": "Notebook", "price": "19.99"})

    with session_factory() as db:
        row = db.get(ProductRow, 1)

    assert row.price_cents == 1999


def test_cents_conversion_is_exact_and_reversible():
    assert to_cents(Decimal("19.99")) == 1999
    assert to_cents(Decimal("19.9")) == 1990
    assert to_cents(Decimal("5")) == 500
    assert from_cents(1990) == Decimal("19.90")
    assert str(from_cents(1990)) == "19.90"


def test_data_survives_a_restart(tmp_path):
    # A real file this time, not an in-memory database.
    url = f"sqlite:///{tmp_path / 'shop.db'}"

    first_run = create_engine(url)
    Base.metadata.create_all(first_run)
    with sessionmaker(bind=first_run)() as db:
        ProductRepository(db).add(ProductCreate(name="Notebook", price=Decimal("19.99"), stock=3))
    first_run.dispose()  # "the server stops"

    second_run = create_engine(url)  # "the server starts again"
    with sessionmaker(bind=second_run)() as db:
        products = ProductRepository(db).list(skip=0, limit=10)
    second_run.dispose()

    assert [(p.name, p.price, p.stock) for p in products] == [("Notebook", Decimal("19.99"), 3)]
