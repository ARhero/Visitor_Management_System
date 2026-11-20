"""Create a super admin: the account that signs in at /platform and creates organizations.

    uv run python -m scripts.create_superadmin you@company.com "Your Name"

The password is asked for (not shown, typed twice). Needs the database running and up to
date (serve-public.bat or start.bat does both). To change a password later, use
scripts.set_password.
"""

import asyncio
import getpass
import sys

from sqlalchemy import func, select

from app.core.db import dispose_engines, system_session
from app.core.security import hash_password
from app.models import PlatformUser

MIN_LENGTH = 10


async def main(email: str, name: str) -> None:
    if "@" not in email:
        raise SystemExit("Give an email address.")
    async with system_session() as db:
        taken = (
            await db.execute(select(PlatformUser.id).where(func.lower(PlatformUser.email) == email))
        ).first()
        if taken:
            raise SystemExit(f"{email} is already a super admin (scripts.set_password changes it).")
        pw = getpass.getpass("Password (at least 10 characters): ")
        if len(pw) < MIN_LENGTH:
            raise SystemExit("Too short.")
        if getpass.getpass("Again: ") != pw:
            raise SystemExit("The two don't match.")
        db.add(PlatformUser(email=email, full_name=name, password_hash=hash_password(pw)))
        await db.commit()
    await dispose_engines()
    print(f"Super admin created: {email}. Sign in at <your address>/platform/login")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit('Usage: uv run python -m scripts.create_superadmin <email> "<full name>"')
    asyncio.run(main(sys.argv[1].strip().lower(), sys.argv[2].strip()))
