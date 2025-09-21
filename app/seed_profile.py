"""
학생 프로필 생성/업데이트 스크립트
예)
  python -m app.seed_profile --username student01 --name "홍길동" --student-no 20250001 \
    --college "공과대학" --department "컴퓨터공학과" --cert "IT인증제" \
    --extra "멘토링, 비교과캠프" --consortium "AI사업단 2과목 이수"
"""
import argparse
from sqlmodel import Session, select
from .database import engine, init_db
from .models import User, StudentProfile

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--student-no", dest="student_no", default=None)
    parser.add_argument("--college", default=None)
    parser.add_argument("--department", default=None)
    parser.add_argument("--cert", dest="certification_track", default=None)
    parser.add_argument("--extra", dest="extracurricular_programs", default=None)
    parser.add_argument("--consortium", dest="consortium_curriculum_status", default=None)
    args = parser.parse_args()

    init_db()
    with Session(engine) as s:
        user = s.exec(select(User).where(User.username == args.username)).first()
        if not user:
            print(f"[!] user '{args.username}' not found")
            return
        prof = s.exec(select(StudentProfile).where(StudentProfile.user_id == user.id)).first()
        if not prof:
            prof = StudentProfile(user_id=user.id)
        # 필드 채우기 (넘긴 값만 반영)
        for k in ["name","student_no","college","department","certification_track","extracurricular_programs","consortium_curriculum_status"]:
            v = getattr(args, k)
            if v is not None:
                setattr(prof, k, v)
        s.add(prof)
        s.commit()
        print(f"[+] upserted profile for {args.username}")

if __name__ == "__main__":
    main()
