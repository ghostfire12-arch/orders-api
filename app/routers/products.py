from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.repository import ProductRepository
from app.schemas import Product, ProductCreate

# A router groups related routes. Every path below starts with "/products",
# and "tags" groups them together in the /docs page.
router = APIRouter(prefix="/products", tags=["products"])


def get_repository(db: Annotated[Session, Depends(get_db)]) -> ProductRepository:
    return ProductRepository(db)


# Dependency injection: a route that asks for "Repo" gets a ProductRepository
# built for that request. FastAPI calls get_repository, which calls get_db,
# so the database session is opened and closed for us. Tests can swap get_db
# for a throwaway database without touching any route.
Repo = Annotated[ProductRepository, Depends(get_repository)]


@router.post(
    "",
    response_model=Product,
    status_code=status.HTTP_201_CREATED,
    # Only admins may create products. The dependency runs first: no token
    # gives 401, a non-admin token gives 403, and this function never starts.
    dependencies=[Depends(require_admin)],
)
def create_product(payload: ProductCreate, repo: Repo) -> Product:
    # "payload: ProductCreate" is validated before this function runs.
    # 201 means "created", the correct code for a new resource.
    return repo.add(payload)


@router.get("", response_model=list[Product])
def list_products(
    repo: Repo,
    skip: int = Query(default=0, ge=0, description="How many products to skip"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
) -> list[Product]:
    # skip and limit are query parameters: /products?skip=20&limit=10.
    return repo.list(skip=skip, limit=limit)


@router.get("/{product_id}", response_model=Product)
def get_product(product_id: int, repo: Repo) -> Product:
    product = repo.get(product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product
