import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Where the database lives. A SQLite URL like "sqlite:///./orders.db" means
# "a file called orders.db in the current folder". Later, setting the
# DATABASE_URL environment variable lets us point the same code at PostgreSQL
# without editing any file.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./orders.db")

# The engine is the connection to the database. SQLite normally refuses to be
# used from more than one thread, but FastAPI runs routes in a thread pool, so
# we switch that check off. Only SQLite needs this.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)

# A session is one conversation with the database: read some rows, change
# some, then commit (save) or roll back (undo). SessionLocal creates them.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Parent of every table class. It collects them so we can create them."""


def init_db() -> None:
    """Create any tables that do not exist yet. Safe to call every start."""
    # Importing models registers the table classes on Base.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """Give a route its own session, and always close it afterwards.

    FastAPI calls this for each request. Everything before "yield" is setup,
    the code in "finally" is cleanup that runs even if the route crashes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
