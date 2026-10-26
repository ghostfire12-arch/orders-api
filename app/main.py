from fastapi import FastAPI

# The FastAPI object is the whole application. Every route we add later is
# registered on it.
app = FastAPI(
    title="Orders API",
    version="0.1.0",
    description="A small ordering API: accounts, products, orders and payments.",
)


# "@app.get('/')" is a decorator. It tells FastAPI: when a browser or client
# sends a GET request to the path "/", run the function below it.
@app.get("/")
def root() -> dict[str, str]:
    # Whatever the function returns is converted to JSON automatically.
    return {"name": "Orders API", "status": "running", "docs": "/docs"}


# A health endpoint is a convention: monitoring tools and hosting platforms
# call it to check that the service is alive.
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
