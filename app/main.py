import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.payment_providers import get_payment_provider
from app.routers import auth, orders, payments, products

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Runs once when the server starts: make sure the tables exist.
    init_db()
    # Build the payment provider NOW. If it is misconfigured (for example
    # Paystack chosen but no key set) the server refuses to start, instead of
    # failing in front of the first customer.
    provider = get_payment_provider()
    if provider.name == "fake":
        logger.warning("Using the FAKE payment provider. No real money moves.")
    yield
    # Anything after "yield" would run when the server shuts down.


# The FastAPI object is the whole application. Every route we add later is
# registered on it.
app = FastAPI(
    title="Orders API",
    version="0.5.0",
    description="A small ordering API: accounts, products, orders and payments.",
    lifespan=lifespan,
)

# Attach the route groups to the application.
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(payments.router)


# "@app.get('/')" is a decorator. It tells FastAPI: when a client sends a GET
# request to the path "/", run the function below it.
@app.get("/")
def root() -> dict[str, str]:
    # Whatever the function returns is converted to JSON automatically.
    return {"name": "Orders API", "status": "running", "docs": "/docs"}


# A health endpoint is a convention: monitoring tools and hosting platforms
# call it to check that the service is alive.
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
