#!/usr/bin/env python3
# /scripts/seed_options.py (final aligned with models.py & main.py)

import os
import datetime as dt
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from passlib.hash import bcrypt

# ------------------------------------------------------------------
# env
# ------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATABASE_URL   = os.getenv("DATABASE_URL")
ADMIN_USER     = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
ADMIN_NAME     = os.getenv("ADMIN_NAME", "관리자")

engine = create_engine(DATABASE_URL, future=True)

current_year = dt.datetime.now().year

# ------------------------------------------------------------------
# option groups definition
# models.OptionGroup columns (from main.py usage):
#   key (str, unique)
#   title (group display name)
#   description
#   value_type
#
# models.OptionItem columns (from main.py usage):
#   group_key (fk to OptionGroup.key)
#   label (display label)
#   value_* (text/int/bool/date/json)  -> we will fill value_text
#   order (display order)
#   is_active (bool)
# ------------------------------------------------------------------

GROUPS = [
    ("degree", "학위과정", "학위 과정 구분", "string"),
    ("college", "소속 단위", "단과대학/대학원 등 소속 단위", "string"),
    ("collaborative_program", "협동과정 여부", "협동과정 해당/미해당", "string"),
    ("department", "학과(전공) 소속", "학과/전공 소속 명칭", "string"),
    ("major", "전공명", "정식 전공명", "string"),
    ("admission_year", "입학년도", "입학년도(연도)", "int"),
    ("admission_term", "입학학기", "입학 학기 (1학기/2학기)", "string"),
    ("admission_type", "입학유형", "입학 전형유형", "string"),
    ("academic_status", "학적상태", "재학/휴학/수료/졸업 등", "string"),
    ("leave_of_absence_flag", "휴학 여부", "휴학 여부(Y/N)", "string"),
    ("semester_simple", "학기 구분", "1학기/2학기", "string"),
    ("nationality", "국적", "국적(영문 표기)", "string"),
    ("email_domain", "이메일 도메인", "일반 이메일 도메인 선택", "string"),
]

DEGREES = [
    "학사",
    "석사",
    "박사",
    "석박통합",
]

COLLEGES = [
    "의과대학(의학과)",
    "의과대학(의학과 외)",
    "보건대학원",
    "의과대학 대학원",
    "치의학대학원",
    "간호대학 대학원",
    "약학대학원",
    "공과대학 대학원",
    "자연과학대학 대학원",
    "융합기술대학원",
]

COLLABORATIVE_PROGRAM = [
    "해당",
    "미해당",
]

ADMISSION_TERMS = [
    "1학기",
    "2학기",
]

ADMISSION_TYPES = [
    "일반전형(전일제)",
    "일반전형(파트타임)",
    "재직자 전형",
    "외국인 전형",
    "타학교 편입",
    "타과 편입",
]

ACADEMIC_STATUS = [
    "재학",
    "휴학",
    "수료",
    "졸업",
    "기타",
]

LEAVE_OF_ABSENCE_FLAG = [
    "Y",
    "N",
]

SEMESTER_SIMPLE = [
    "1학기",
    "2학기",
]

NATIONALITIES = [
    "Republic of Korea",
    "United States",
    "China",
    "Japan",
]

EMAIL_DOMAINS = [
    ("gmail.com", "gmail.com"),
    ("naver.com", "naver.com"),
    ("hanmail.net", "hanmail.net"),
    ("daum.net", "daum.net"),
    ("outlook.com", "outlook.com"),
]


def main():
    pwd_hash = bcrypt.hash(ADMIN_PASSWORD)

    with engine.begin() as conn:
        # wipe
        conn.execute(text("DELETE FROM optionitem"))
        conn.execute(text("DELETE FROM optiongroup"))

        # insert optiongroup
        # columns in DB must be: key, title, description, value_type
        for key, title, desc, vtype in GROUPS:
            conn.execute(
                text(
                    """
                    INSERT INTO optiongroup (key, title, description, value_type)
                    VALUES (:k, :t, :d, :vt)
                    """
                ),
                {"k": key, "t": title, "d": desc, "vt": vtype},
            )

        # helper for optionitem
        # DB columns used here:
        #   group_key, label, value_text, "order", is_active
        def insert_items(group_key, pairs):
            order_no = 1
            for value_text, label in pairs:
                conn.execute(
                    text(
                        """
                        INSERT INTO optionitem (group_key, label, value_text, "order", is_active)
                        VALUES (:g, :l, :v, :o, TRUE)
                        """
                    ),
                    {
                        "g": group_key,
                        "l": label,
                        "v": value_text,
                        "o": order_no,
                    },
                )
                order_no += 1

        insert_items("degree", [(d, d) for d in DEGREES])
        insert_items("college", [(c, c) for c in COLLEGES])
        insert_items("collaborative_program", [(c, c) for c in COLLABORATIVE_PROGRAM])

        # department / major left empty (to be managed later in admin UI)
        insert_items("department", [])
        insert_items("major", [])

        # admission_year: recent 10 years + current
        insert_items(
            "admission_year",
            [(str(y), str(y)) for y in range(current_year - 10, current_year + 1)],
        )

        insert_items("admission_term", [(t, t) for t in ADMISSION_TERMS])
        insert_items("admission_type", [(t, t) for t in ADMISSION_TYPES])

        insert_items("academic_status", [(s, s) for s in ACADEMIC_STATUS])
        insert_items("leave_of_absence_flag", [(f, f) for f in LEAVE_OF_ABSENCE_FLAG])
        insert_items("semester_simple", [(s, s) for s in SEMESTER_SIMPLE])

        insert_items("nationality", [(n, n) for n in NATIONALITIES])
        insert_items("email_domain", EMAIL_DOMAINS)

        # adminaccount ensure
        # columns assumed: admin_id, admin_hash, user_name
        conn.execute(
            text(
                """
                INSERT INTO adminaccount (admin_id, admin_hash, user_name)
                VALUES (:aid, :apw, :aname)
                ON CONFLICT (admin_id) DO NOTHING
                """
            ),
            {"aid": ADMIN_USER, "apw": pwd_hash, "aname": ADMIN_NAME},
        )

    print("✅ seed done")


if __name__ == "__main__":
    main()
