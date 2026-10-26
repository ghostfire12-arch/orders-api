from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    """What a client must send to create a product.

    Every Field(...) below is a validation rule. If the request breaks one,
    FastAPI answers with a 422 error and never runs our code.
    """

    # Remove spaces around text, so "   " is treated as empty and rejected.
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    # Decimal, not float: floats cannot store 0.1 exactly, which is
    # unacceptable for money. gt=0 means "greater than zero".
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    # ge=0 means "greater than or equal to zero".
    stock: int = Field(default=0, ge=0)


class Product(ProductCreate):
    """What the API sends back: everything in ProductCreate, plus an id."""

    id: int
