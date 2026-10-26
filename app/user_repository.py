from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import UserRow


class EmailAlreadyRegistered(Exception):
    """Raised when someone registers an email that already has an account."""


class UserRepository:
    """All the database work for users."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, email: str, password_hash: str, is_admin: bool = False) -> UserRow:
        user = UserRow(email=email, password_hash=password_hash, is_admin=is_admin)
        self.db.add(user)
        try:
            self.db.commit()
        except IntegrityError:
            # The unique rule on "email" fired. This also covers two requests
            # racing each other, which a plain "check first" cannot.
            self.db.rollback()
            raise EmailAlreadyRegistered(email) from None
        self.db.refresh(user)
        return user

    def get_by_email(self, email: str) -> UserRow | None:
        return self.db.scalar(select(UserRow).where(UserRow.email == email))

    def get_by_id(self, user_id: int) -> UserRow | None:
        return self.db.get(UserRow, user_id)
