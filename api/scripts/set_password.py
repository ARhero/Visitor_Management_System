"""Set a new password for a sign-in (super admin, or anyone in an organization).

    uv run python -m scripts.set_password root@vms.local
    uv run python -m scripts.set_password admin@yourcompany.com

The password is asked for (not shown, typed twice). Matches the sign-in email of a
super admin first, then of org staff (if it is in several orgs, all of them change).
The person is signed out everywhere.
"""

import asyncio
import getpass
import sys

from sqlalchemy import func, select

from app.core.db import dispose_engines, system_session
from app.core.security import hash_password
from app.models import PlatformUser, User
from app.services.auth import revoke_all_for_user

MIN_LENGTH = 10


async def main(email: str) -> None:
    pw = getpass.getpass("New password (at least 10 characters): ")
    if len(pw) < MIN_LENGTH:
        raise SystemExit("Too short.")
    if getpass.getpass("Again: ") != pw:
        raise SystemExit("The two don't match.")
    async with system_session() as db:
        pu = (
            await db.execute(select(PlatformUser).where(func.lower(PlatformUser.email) == email))
        ).scalar_one_or_none()
        users = (
            []
            if pu
            else (
                (await db.execute(select(User).where(func.lower(User.email) == email)))
                .scalars()
                .all()
            )
        )
        if not pu and not users:
            raise SystemExit(f"No sign-in with the email {email}")
        for u in [pu] if pu else users:
            u.password_hash = hash_password(pw)
            await revoke_all_for_user(db, u.id)
        await db.commit()
    await dispose_engines()
    orgs = f" ({len(users)} organizations)" if len(users) > 1 else ""
    print(f"Password changed for {email}{orgs}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: uv run python -m scripts.set_password <email>")
    asyncio.run(main(sys.argv[1].strip().lower()))
