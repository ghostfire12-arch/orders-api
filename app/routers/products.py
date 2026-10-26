from fastapi import APIRouter, HTTPException, Query, status

from app.schemas import Product, ProductCreate
from app.store import store

# A router groups related routes. Every path below starts with "/products",
# and "tags" groups them together in the /docs page.
router = APIRouter(prefix="/products", tags=["products"])


@router.post("", response_model=Product, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate) -> Product:
    # "payload: ProductCreate" is the magic: FastAPI reads the JSON body,
    # checks it against ProductCreate, and only calls this function when the
    # data is valid. 201 means "created", the correct code for a new resource.
    return store.add(payload)


@router.get("", response_model=list[Product])
def list_products(
    skip: int = Query(default=0, ge=0, description="How many products to skip"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
) -> list[Product]:
    # skip and limit are query parameters: /products?skip=20&limit=10.
    # Pagination stops the API sending thousands of rows at once.
    return store.list(skip=skip, limit=limit)


@router.get("/{product_id}", response_model=Product)
def get_product(product_id: int) -> Product:
    # {product_id} in the path becomes the function argument. Because it is
    # typed as int, "/products/abc" is rejected automatically.
    product = store.get(product_id)
    if product is None:
        # 404 means "not found". HTTPException turns into a clean JSON error.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product
