#!/usr/bin/env python3
import asyncio
import os
import sys

import asyncpg


async def main():
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("RAILWAY_DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL not found in environment", file=sys.stderr)
        sys.exit(2)

    print("Connecting to:", dsn.split("@")[-1])
    conn = await asyncpg.connect(dsn)

    select_q = (
        "SELECT id, username, email FROM users "
        "WHERE LOWER(username) LIKE 'smoke_resend_%' OR LOWER(email) LIKE 'onboarding+smoke%@resend.dev' "
        "ORDER BY id"
    )
    rows = await conn.fetch(select_q)
    print(f"Found {len(rows)} matching users")
    for r in rows:
        print(f"- id={r['id']} username={r['username']} email={r['email']}")

    if not rows:
        print("Nothing to delete.")
        await conn.close()
        return

    # Proceed with deletion (user already confirmed)
    print("Deleting matching registration_verifications...")
    del_rv = (
        "DELETE FROM registration_verifications "
        "WHERE LOWER(email) LIKE 'onboarding+smoke%@resend.dev' OR LOWER(username) LIKE 'smoke_resend_%'"
    )
    res1 = await conn.execute(del_rv)
    print("registration_verifications:", res1)

    print("Deleting matching users...")
    del_users = (
        "DELETE FROM users "
        "WHERE LOWER(email) LIKE 'onboarding+smoke%@resend.dev' OR LOWER(username) LIKE 'smoke_resend_%'"
    )
    res2 = await conn.execute(del_users)
    print("users:", res2)

    await conn.close()
    print("Done.")


if __name__ == '__main__':
    asyncio.run(main())
