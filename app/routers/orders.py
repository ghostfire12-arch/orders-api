from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser, require_admin
from app.models import OrderRow, UserRow
from app.order_repository import (
    InsufficientStock,
    InvalidTransition,
    OrderRepository,
    ProductNotFound,
    to_order,
)
from app.schemas import Order, OrderCreate, OrderStatus, StatusUpdate

router = APIRouter(tags=["orders"])


def get_order_repository(db: Annotated[Session, Depends(get_db)]) -> OrderRepository:
    return OrderRepository(db)


OrderRepo = Annotated[OrderRepository, Depends(get_order_repository)]


def _order_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")


def _load_visible_order(orders: OrderRepository, order_id: int, user: UserRow) -> OrderRow:
    """Find an order, but only if this user is allowed to see it.

    Customers may see their own orders. Admins may see all of them. For
    anyone else the answer is 404 "not found", NOT 403 "forbidden". A 403
    would confirm that the order exists, which tells a stranger that order
    number 17 is real. This is called preventing IDOR (insecure direct object
    reference), one of the most common API bugs.
    """
    order = orders.get(order_id)
    if order is None or (order.user_id != user.id and not user.is_admin):
        raise _order_not_found()
    return order


@router.post("/orders", response_model=Order, status_code=status.HTTP_201_CREATED)
def create_order(payload: OrderCreate, user: CurrentUser, orders: OrderRepo) -> Order:
    try:
        # The customer is whoever the TOKEN says. We never accept a user_id
        # from the request body, or someone could order as somebody else.
        row = orders.create(user_id=user.id, data=payload)
    except ProductNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Product {error.product_id} not found"
        ) from None
    except InsufficientStock as error:
        # 409 Conflict: the request is valid but clashes with current state.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Not enough stock for {error.product_name}: {error.available} available",
        ) from None
    return to_order(row)


@router.get("/orders", response_model=list[Order])
def list_my_orders(
    user: CurrentUser,
    orders: OrderRepo,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[Order]:
    # Filtered by the logged-in user's id: you only ever get your own orders.
    return [to_order(row) for row in orders.list_for_user(user.id, skip, limit)]


@router.get("/orders/{order_id}", response_model=Order)
def get_order(order_id: int, user: CurrentUser, orders: OrderRepo) -> Order:
    return to_order(_load_visible_order(orders, order_id, user))


@router.post("/orders/{order_id}/cancel", response_model=Order)
def cancel_order(order_id: int, user: CurrentUser, orders: OrderRepo) -> Order:
    order = orders.get(order_id)
    # Customers cancel only their OWN orders. Even admins use the status route.
    if order is None or order.user_id != user.id:
        raise _order_not_found()
    if order.status != OrderStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending orders can be cancelled by the customer",
        )
    try:
        return to_order(orders.change_status(order, OrderStatus.CANCELLED))
    except InvalidTransition:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Order is no longer pending"
        ) from None


@router.get(
    "/admin/orders",
    response_model=list[Order],
    dependencies=[Depends(require_admin)],
)
def list_all_orders(
    orders: OrderRepo,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[Order]:
    return [to_order(row) for row in orders.list_all(status_filter, skip, limit)]


@router.patch(
    "/orders/{order_id}/status",
    response_model=Order,
    dependencies=[Depends(require_admin)],
)
def update_order_status(order_id: int, payload: StatusUpdate, orders: OrderRepo) -> Order:
    order = orders.get(order_id)
    if order is None:
        raise _order_not_found()
    try:
        return to_order(orders.change_status(order, payload.status))
    except InvalidTransition as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot change status from {error.current} to {error.requested}",
        ) from None
