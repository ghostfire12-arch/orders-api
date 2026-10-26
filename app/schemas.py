from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


# A simple email shape check: something@something.something, no spaces.
# It rejects obvious mistakes. The only real proof an email works is sending a
# message to it, which a later step could add.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UserCreate(BaseModel):
    """What a person sends to register."""

    # Trim spaces and turn the email to lowercase, so "Ada@x.com " and
    # "ada@x.com" are the same account.
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    # Minimum length stops weak passwords. The maximum stops someone sending a
    # gigantic "password" to make the server waste time hashing it.
    password: str = Field(min_length=8, max_length=128)

    # mode="before" runs this cleanup BEFORE the length and pattern rules.
    # The default ("after") would check the raw text first, and reject an
    # email that only has stray spaces around it.
    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class UserPublic(BaseModel):
    """What the API may show about a user. Notice: no password, no hash."""

    # Lets us build this model straight from a database row.
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    is_admin: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OrderStatus(StrEnum):
    """The only values a status may have. Anything else is a 422 error."""

    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class OrderItemCreate(BaseModel):
    """One line the customer wants. Note: there is no price field.

    The client says WHAT and HOW MANY. The server decides the price. If the
    client could send a price, anyone could buy everything for 1 cent.
    """

    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=100)


class OrderCreate(BaseModel):
    items: list[OrderItemCreate] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def products_must_be_unique(self) -> "OrderCreate":
        ids = [item.product_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each product may appear only once; raise its quantity instead")
        return self


class StatusUpdate(BaseModel):
    status: OrderStatus


class OrderItem(BaseModel):
    product_id: int
    product_name: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal


class Order(BaseModel):
    id: int
    user_id: int
    status: OrderStatus
    total: Decimal
    created_at: datetime
    items: list[OrderItem]
