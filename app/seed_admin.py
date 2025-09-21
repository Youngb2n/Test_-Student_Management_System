"""
사용자 생성 스크립트
예시:
  python -m app.seed_admin --username admin --password admin123 --role admin
"""
import argparse
from sqlmodel import Session, select
from .database import engine, init_db
from .models import User

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default="admin")
    args = parser.parse_args()

    init_db()
    with Session(engine) as s:
        exists = s.exec(select(User).where(User.username == args.username)).first()
        if exists:
            print("[!] User already exists")
            return
        u = User(username=args.username, role=args.role, password_hash="")
        u.set_password(args.password)
        s.add(u)
        s.commit()
        print(f"[+] Created user: {args.username} ({args.role})")

if __name__ == "__main__":
    main()
