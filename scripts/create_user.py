"""Create or reset an Odynza Radar account from the server's terminal.

    python scripts/create_user.py alice --admin       # first admin
    python scripts/create_user.py bob                  # team member
    python scripts/create_user.py sara --viewer        # can only view results
    python scripts/create_user.py acme --client        # client login: sees only Competitor watch
    python scripts/create_user.py bob --reset          # new password for an existing account

The password is typed at a hidden prompt; it is never taken from the command line or .env.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException  # noqa: E402

from api.security import clean_username, hash_password, password_problem  # noqa: E402
from db.database import AuthSession, SessionLocal, User, init_db  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('username')
    parser.add_argument('--admin', action='store_true', help='give the account admin rights (manage users)')
    parser.add_argument('--viewer', action='store_true', help='read-only account: can view results but not change anything')
    parser.add_argument('--client', action='store_true', help='client account: sees only Competitor watch (M0)')
    parser.add_argument('--reset', action='store_true', help='set a new password for an existing account')
    args = parser.parse_args()
    try:
        name = clean_username(args.username)
    except HTTPException as exc:
        sys.exit(exc.detail)
    role = 'admin' if args.admin else 'viewer' if args.viewer else 'client' if args.client else 'member'
    init_db()
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == name).first()
        if user and not args.reset:
            sys.exit(f'{name} already exists. Use --reset to set a new password.')
        if args.reset and not user:
            sys.exit(f'No account called {name}.')
        while True:
            password = getpass.getpass('Password (at least 10 characters): ')
            problem = password_problem(password, name)
            if problem:
                print(problem)
                continue
            if getpass.getpass('Repeat password: ') != password:
                print('The passwords did not match.')
                continue
            break
        if user:
            user.password_hash = hash_password(password)
            user.disabled = False
            if args.admin or args.viewer or args.client:
                user.role = role
            db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
        else:
            db.add(User(username=name, password_hash=hash_password(password), role=role))
        db.commit()
    print(f'{"Updated" if user else "Created"} {name} ({user.role if user else role}).')


if __name__ == '__main__':
    main()
