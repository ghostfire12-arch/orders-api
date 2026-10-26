"""Create the first admin account, or promote an existing user to admin.

Run it from the project folder:

    .venv\\Scripts\\python.exe -m app.create_admin

Why a script and not an API route? Anyone on the internet can call a route.
Only someone with access to this computer can run a script, so there is no
way for a stranger to make themselves an admin.
"""

import getpass
import sys

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import SessionLocal, init_db
from app.schemas import UserCreate
from app.security import hash_password
from app.user_repository import UserRepository


def create_or_promote_admin(db: Session, email: str, password: str | None) -> str:
    """Make `email` an admin. Returns "created" or "promoted"."""
    users = UserRepository(db)
    existing = users.get_by_email(email)
    if existing is not None:
        # Promote only. We never change an existing person's password here.
        existing.is_admin = True
        db.commit()
        return "promoted"
    if password is None:
        raise ValueError("A password is required to create a new account")
    users.add(email=email, password_hash=hash_password(password), is_admin=True)
    return "created"


def main() -> int:
    init_db()
    email = input("Admin email: ").strip().lower()
    with SessionLocal() as db:
        if UserRepository(db).get_by_email(email) is not None:
            print(f"{email} already has an account. Promoting to admin.")
            password = None
        else:
            # getpass hides what you type, and nothing is saved in your
            # terminal history.
            password = getpass.getpass("Password (8 or more characters): ")
            if password != getpass.getpass("Repeat password: "):
                print("The passwords do not match.")
                return 1
        try:
            if password is not None:
                UserCreate(email=email, password=password)  # reuse the API's rules
        except ValidationError as error:
            print("Invalid email or password:")
            for problem in error.errors():
                print(f"  {problem['loc'][-1]}: {problem['msg']}")
            return 1
        print(f"Admin {create_or_promote_admin(db, email, password)}: {email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
