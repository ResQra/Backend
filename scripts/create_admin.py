"""Create or update an admin (coordinator) account.

Usage:
    python scripts/create_admin.py <username> <password> [display_name]

Example:
    python scripts/create_admin.py resqra-admin resqra-admin-123 "Control Room"
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.auth.security import hash_password  # noqa: E402
from app.db.repos import users  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    username, password = sys.argv[1], sys.argv[2]
    display_name = sys.argv[3] if len(sys.argv) > 3 else username.title()

    existing = users.find_by_username(username)
    if existing:
        users.update_user_info(existing["id"], password_hash=hash_password(password))
        print(f"password updated for admin '{username}' ({existing['id']})")
        return

    user = users.create_user(
        name=display_name,
        role="coordinator",
        username=username,
        password_hash=hash_password(password),
    )
    print(f"admin '{username}' created ({user['id']}) — role: coordinator")


if __name__ == "__main__":
    main()
