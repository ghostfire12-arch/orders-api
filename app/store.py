from app.schemas import Product, ProductCreate


class InMemoryProductStore:
    """Keeps products in a Python dictionary.

    This is temporary. The data disappears when the server restarts. In step 3
    we replace it with a real database, and the routes will barely change,
    because they only talk to this small set of methods.
    """

    def __init__(self) -> None:
        self._products: dict[int, Product] = {}
        self._next_id = 1

    def add(self, data: ProductCreate) -> Product:
        product = Product(id=self._next_id, **data.model_dump())
        self._products[product.id] = product
        self._next_id += 1
        return product

    def get(self, product_id: int) -> Product | None:
        return self._products.get(product_id)

    def list(self, skip: int, limit: int) -> list[Product]:
        products = list(self._products.values())
        return products[skip : skip + limit]

    def clear(self) -> None:
        """Empty the store. Used by tests so each test starts fresh."""
        self._products.clear()
        self._next_id = 1


# One shared store for the whole application.
store = InMemoryProductStore()
