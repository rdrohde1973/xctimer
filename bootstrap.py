"""Bootstrap the sole Super Admin (handoff §0: Rob).

Usage:
    python -m xctimer.bootstrap <email> [name]

Creates a super_admin (district_id NULL) with a one-time setup token and prints
the setup link. If XCTIMER_BOOTSTRAP_PASSWORD is set in the env, the password is
set directly instead (dev convenience — skips the email round-trip).

Idempotent-ish: if the email already exists, prints its status and exits.
"""
import os
import sys

from . import db, auth


def main(argv):
    if not argv:
        print("usage: python -m xctimer.bootstrap <email> [name]")
        return 1
    email = argv[0].strip().lower()
    name = argv[1] if len(argv) > 1 else "Super Admin"

    db.init_db()
    existing = auth.find_user_by_email(email)
    if existing:
        state = "active" if existing["password_hash"] else "pending setup"
        print(f"User {email} already exists (role={existing['role']}, {state}).")
        return 0

    pw = os.environ.get("XCTIMER_BOOTSTRAP_PASSWORD")
    uid, token = auth.create_user(email, "super_admin", name=name)
    if pw:
        conn = db.connect()
        conn.execute(
            "UPDATE users SET password_hash=?, setup_token=NULL, token_expires=NULL WHERE id=?",
            (auth.hash_password(pw), uid),
        )
        conn.commit()
        conn.close()
        print(f"Created super_admin {email} (id={uid}) with password set directly.")
    else:
        base = os.environ.get("XC_PUBLIC_URL", "http://127.0.0.1:5006")
        print(f"Created super_admin {email} (id={uid}).")
        print(f"Setup link: {base}/setup?token={token}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
