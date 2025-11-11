from datetime import datetime, date, timezone
from typing import List, Optional, Any, Dict, Tuple
import bcrypt
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from starlette.templating import Jinja2Templates
from app.database import get_session
from app import models
import json
from sqlalchemy.orm import joinedload, noload
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, and_, or_
from pydantic import BaseModel
import datetime as dt
from itertools import zip_longest
import csv
from io import StringIO
from starlette.responses import Response
from sqlalchemy.orm import aliased

app = FastAPI()

# static mount (CSS/JS)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# templates
templates = Jinja2Templates(directory="app/templates")

# session middleware
app.add_middleware(
    SessionMiddleware,
    secret_key="change-this-in-production",
    same_site="lax",
    https_only=False,
)

# -------------------------------------------------
# helpers
# -------------------------------------------------

def build_option_map(db: Session) -> dict:
    """
    OptionGroup / OptionItem 테이블에서 select 박아온 값을
    { group_key: [ {value, label}, ... ], ... } 형태로 만든다.
    템플릿에서 select 옵션 렌더에 사용.
    """
    groups = db.exec(select(models.OptionGroup)).all()
    items = db.exec(select(models.OptionItem)).all()

    mapped: dict[str, list[dict[str, str]]] = {}
    for g in groups:
        arr = []
        for it in items:
            if it.group_key != g.key:
                continue
            if not it.is_active:
                continue

            if it.value_text is not None:
                v = it.value_text
            elif it.value_int is not None:
                v = str(it.value_int)
            elif it.value_bool is not None:
                v = "true" if it.value_bool else "false"
            elif it.value_date is not None:
                v = it.value_date.isoformat()
            elif it.value_json is not None:
                v = it.value_json
            else:
                v = ""

            arr.append({"value": v, "label": it.label})
        mapped[g.key] = arr
    return mapped


def require_admin(request: Request) -> bool:
    return bool(request.session.get("admin_id"))


def parse_birthdate_safe(raw: str) -> Optional[date]:
    """
    'YYYY-MM-DD' -> date
    1900~2100년 사이만 허용.
    잘못되면 None.
    """
    try:
        y_s, m_s, d_s = raw.split("-")
        y, m, d = int(y_s), int(m_s), int(d_s)
        if y < 1900 or y > 2100:
            return None
        return date(y, m, d)
    except Exception:
        return None


def _college_code_from_scope(scope: str) -> str:
    """
    ProgramRequirement.requirement_code 생성용.
    의대 계열이면 'M', 아니면 'E'.
    """
    scope = (scope or "").strip()
    if scope.startswith("의과대"):
        return "M"
    return "E"


def _degree_code_from_scope(scope: str) -> str:
    """
    학위 구분 코드화:
    학부=B, 석사=M, 박사=D, 대학원생/통합=C (임시 공통 코드)
    """
    s = (scope or "").strip()
    if s == "학부":
        return "B"
    if s == "석사":
        return "M"
    if s == "박사":
        return "D"
    if s in ("대학원생", "통합"):
        return "C"
    return "C"


def _next_requirement_seq_for_year(db: Session, year_prefix: str) -> int:
    """
    requirement_code 앞 4자(연도)가 year_prefix 인 것들 중
    seq(0001 등) 최댓값+1 리턴.
    """
    existing = db.exec(
        select(models.ProgramRequirement.requirement_code)
        .where(models.ProgramRequirement.requirement_code.like(f"{year_prefix}%"))
    ).all()

    max_seq = 0
    for code in existing:
        if not code or len(code) < 10:
            continue
        seq_part = code[4:8]  # YYYY[0001]MC 가정
        try:
            num = int(seq_part)
            if num > max_seq:
                max_seq = num
        except ValueError:
            pass

    return max_seq + 1


def _generate_requirement_code(
    db: Session,
    college_scope: str,
    degree_scope: str,
    year: int
) -> str:
    """
    2025 + 0001 + M + C => "20250001MC"
    """
    year_str = str(year)
    seq_int = _next_requirement_seq_for_year(db, year_str)
    seq_str = f"{seq_int:04d}"

    college_code = _college_code_from_scope(college_scope)
    degree_code = _degree_code_from_scope(degree_scope)

    return f"{year_str}{seq_str}{college_code}{degree_code}"


# -------------------------------------------------
# auth / home
# -------------------------------------------------

@app.get("/")
def root():
    return RedirectResponse(url="/login", status_code=302)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "active_role": "admin",
            "error": None,
        },
    )


@app.post("/login")
def login_submit(
    request: Request,
    db: Session = Depends(get_session),
    role: str = Form(...),
    username: str = Form(None),
    password: str = Form(None),
    name: str = Form(None),
    student_no: str = Form(None),
    remember: str = Form(None),
):
    # admin login
    if role == "admin":
        if not username or not password:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "active_role": "admin",
                    "error": "invalid_admin",
                },
                status_code=400,
            )

        admin_row = db.exec(
            select(models.AdminAccount).where(
                models.AdminAccount.admin_id == username
            )
        ).first()

        if (
            admin_row is None
            or admin_row.admin_hash is None
            or not bcrypt.checkpw(
                password.encode("utf-8"),
                admin_row.admin_hash.encode("utf-8"),
            )
        ):
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "active_role": "admin",
                    "error": "invalid_admin",
                },
                status_code=401,
            )

        request.session["admin_id"] = admin_row.admin_id
        return RedirectResponse(url="/admin", status_code=302)

    # student login (이름+학번 매칭)
    if role == "student":
        if not name or not student_no:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "active_role": "student",
                    "error": "invalid_student",
                },
                status_code=400,
            )

        student_row = db.exec(
            select(models.Student).where(
                (models.Student.name == name)
                & (models.Student.student_no == student_no)
            )
        ).first()

        if student_row is None:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "active_role": "student",
                    "error": "invalid_student",
                },
                status_code=401,
            )

        request.session["student_no"] = student_row.student_no
        return RedirectResponse(url="/student", status_code=302)

    # role 이상함
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "active_role": "admin",
            "error": "invalid_role",
        },
        status_code=400,
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@app.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "admin_home.html",
        {
            "request": request,
            "active": "dashboard",
        },
    )


# -------------------------------------------------
# register pages (GET)
# -------------------------------------------------

@app.get("/admin/register/student", response_class=HTMLResponse)
def admin_register_student(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    option_map = build_option_map(db)
    current_year = datetime.now().year

    # ▼ 추가: CurriculumProgram을 option_map["curriculum_program"]에 주입
    programs = db.exec(
        select(models.CurriculumProgram)
        .order_by(models.CurriculumProgram.course_name.asc())
    ).all()

    option_map["curriculum_program"] = [
        {
            "value": str(p.id),
            "label": f"{p.program_type}-{p.course_name}" + (f"({p.open_year})" if getattr(p, "open_year", None) else "")
        }
        for p in programs
    ]

    return templates.TemplateResponse(
        "admin_register_student.html",
        {
            "request": request,
            "active": "register",
            "option_map": option_map,
            "current_year": current_year,
        },
    )


@app.get("/admin/register/business", response_class=HTMLResponse)
def admin_register_business_get(
    request: Request,
    edit_id: int | None = Query(default=None),
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    edit_obj = db.get(models.BusinessInitiative, edit_id) if edit_id else None
    return templates.TemplateResponse(
        "admin_register_business_initiative.html",
        {
            "request": request,
            "active": "register",
            "edit_id": edit_id,
            "edit_obj": edit_obj,
        },
    )


@app.get("/admin/register/curriculum", response_class=HTMLResponse)
def admin_register_curriculum_program(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    option_map = build_option_map(db)
    current_year = datetime.now().year

    initiatives = db.exec(
        select(models.BusinessInitiative)
        .order_by(models.BusinessInitiative.project_name.asc())
    ).all()

    return templates.TemplateResponse(
        "admin_register_curriculum_program.html",
        {
            "request": request,
            "active": "register",
            "option_map": option_map,
            "initiatives": initiatives,
            "current_year": current_year,
        },
    )


@app.get("/admin/register/course", response_class=HTMLResponse)
def admin_register_course(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    option_map = build_option_map(db)
    current_year = datetime.now().year

    curricula = db.exec(
        select(models.CurriculumProgram)
        .order_by(models.CurriculumProgram.course_name.asc())
    ).all()

    return templates.TemplateResponse(
        "admin_register_course.html",
        {
            "request": request,
            "active": "register",
            "option_map": option_map,
            "curricula": curricula,
            "current_year": current_year,
        },
    )


@app.get("/admin/register/extracurricular", response_class=HTMLResponse)
def admin_register_extracurricular_program(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    current_year = datetime.now().year

    # 비교과 등록 시 교육과정 드롭다운에 쓸 리스트
    curricula = db.exec(
        select(models.CurriculumProgram)
        .order_by(models.CurriculumProgram.course_name.asc())
    ).all()

    return templates.TemplateResponse(
        "admin_register_extracurricular_program.html",
        {
            "request": request,
            "active": "register",
            "curricula": curricula,
            "current_year": current_year,
        },
    )


# -------------------------------------------------
# register POST handlers
# -------------------------------------------------

@app.post("/admin/register/student")
async def admin_register_student_post(
    request: Request,
    db: Session = Depends(get_session),

    # --- 학생 기본/재학 정보 ---
    student_no: str = Form(...),
    name: str = Form(...),
    name_en: str = Form(...),
    birthdate: str = Form(...),
    researcher_id: str = Form(...),

    nationality: str = Form(...),
    nationality_custom: str = Form(""),

    foreigner_reg_no: str = Form(""),
    mobile_phone_num: str = Form(...),
    phone_num: str = Form(""),

    email_snu_local: str = Form(...),
    email_other_local: str = Form(""),
    email_other_domain: str = Form(""),
    email_other_custom: str = Form(""),

    degree: str = Form(...),
    college: str = Form(...),
    collaborative_program: str = Form(...),
    department: str = Form(...),
    major: str = Form(...),
    admission_type: str = Form(...),
    admission_year: int = Form(...),
    admission_term: str = Form(...),
    academic_status: str = Form(...),
    leave_of_absence: str = Form("N"),

    advisor_name: str = Form(...),
    supervisor_name: str = Form(""),

    workplace: str = Form(""),
    health_insurance_certificate: str = Form(""),

    previous_degree: str = Form(...),
    previous_major: str = Form(...),
    previous_degree_year: int = Form(...),
    previous_institution: str = Form(...),

    # --- 휴학 이력 (반복) ---
    leave_year: List[int] = Form([]),
    leave_semester: List[str] = Form([]),

    # --- 학생↔교육과정 매핑 (반복) ---
    curriculum_program_id: List[str] = Form([]),     # select(name="curriculum_program_id")
    requirement_id: List[str] = Form([]),            # select(name="requirement_id")
    enroll_start_year: List[str] = Form([]),         # hidden(name="enroll_start_year")
    enroll_start_semester: List[str] = Form([]),     # hidden(name="enroll_start_semester")
    enroll_end_year: List[str] = Form([]),           # hidden(name="enroll_end_year")
    enroll_end_semester: List[str] = Form([]),       # hidden(name="enroll_end_semester")
    enroll_is_active: List[str] = Form([]),          # hidden(name="enroll_is_active") (항상 "Y")
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    # -----------------------------
    # 0) 입력 전처리/검증
    # -----------------------------
    # 생년월일
    birthdate_parsed = parse_birthdate_safe(birthdate)
    if birthdate_parsed is None:
        return JSONResponse(
            {"error": "잘못된 생년월일 형식입니다. (1900~2100년만 허용, YYYY-MM-DD)"},
            status_code=400,
        )

    # 이메일 조립
    def _build_optional_email(local: str, domain_sel: str, domain_custom: str):
        local = (local or "").strip()
        domain_sel = (domain_sel or "").strip()
        domain_custom = (domain_custom or "").strip()
        domain_final = domain_custom if domain_sel == "__OTHER__" else domain_sel
        if not local and not domain_final:
            return None
        if not local or not domain_final:
            return None
        return f"{local}@{domain_final}"

    email_snu_full = f"{email_snu_local.strip()}@snu.ac.kr"
    email_other_full = _build_optional_email(email_other_local, email_other_domain, email_other_custom)

    # 국적
    if nationality == "__OTHER__":
        nat_final = (nationality_custom or "").strip()
        if not nat_final:
            return RedirectResponse(
                "/admin/register/student?error=nationality_required",
                status_code=302
            )
    else:
        nat_final = nationality

    # 재직자 전형 보조 필드
    is_employed_type = ("재직" in (admission_type or ""))
    workplace_final = workplace.strip() if (is_employed_type and workplace.strip()) else None
    health_cert_final = (
        health_insurance_certificate.strip()
        if (is_employed_type and health_insurance_certificate.strip())
        else None
    )

    now_utc = datetime.utcnow()

    # -----------------------------
    # 1) Student INSERT
    # -----------------------------
    stu = models.Student(
        student_no=student_no.strip(),
        name=name.strip(),
        name_en=name_en.strip(),
        birthdate=birthdate_parsed,
        researcher_id=researcher_id.strip(),

        nationality=nat_final,
        foreigner_reg_no=(foreigner_reg_no.strip() or None),

        mobile_phone_num=mobile_phone_num.strip(),
        phone_num=(phone_num.strip() or None),

        email_snu=email_snu_full,
        email_other=email_other_full,

        degree=degree.strip(),
        college=college.strip(),
        collaborative_program=collaborative_program.strip(),
        department=department.strip(),
        major=major.strip(),

        admission_type=admission_type.strip(),
        admission_year=int(admission_year),
        admission_term=admission_term.strip(),

        academic_status=academic_status.strip(),
        leave_of_absence=(leave_of_absence or "N").strip(),

        advisor_name=advisor_name.strip(),
        supervisor_name=(supervisor_name.strip() or None),

        workplace=workplace_final,
        health_insurance_certificate=health_cert_final,

        previous_degree=previous_degree.strip(),
        previous_major=previous_major.strip(),
        previous_degree_year=int(previous_degree_year),
        previous_institution=previous_institution.strip(),

        created_at=now_utc,
        updated_at=now_utc,
    )
    db.add(stu)
    db.flush()  # stu.id 확보

    # -----------------------------
    # 2) 휴학 이력 INSERT (옵션)
    # -----------------------------
    if (leave_of_absence or "N").upper() == "Y":
        for y, sem in zip(leave_year or [], leave_semester or []):
            if not y or not sem:
                continue
            db.add(models.StudentLeaveHistory(
                student_id=stu.id,
                leave_year=int(y),
                leave_semester=str(sem).strip(),
                created_at=now_utc,
                updated_at=now_utc,
            ))

    # -----------------------------
    # 3) 학생 ↔ 교육과정 매핑 INSERT(다건)
    #    - 프런트 name 그대로 List[...]로 수신
    # -----------------------------
    # 안전 파서
    def _to_int_or_none(x):
        try:
            return int(x)
        except Exception:
            return None
    def to_semester(v):
        v = (v or "").strip()
        return v if v else None   # "" → None

    def _norm(x: Optional[str]) -> str:
        return (x or "").strip()

    rows = zip_longest(
        curriculum_program_id or [],
        requirement_id or [],
        enroll_start_year or [],
        enroll_start_semester or [],
        enroll_end_year or [],
        enroll_end_semester or [],
        enroll_is_active or [],
        fillvalue=""
    )

    for raw_cur, raw_req, sy, ss, ey, es, act in rows:
        cur_id = _to_int_or_none(raw_cur)
        if not cur_id:
            continue  # 교육과정이 비어있으면 스킵 (행 자체 무시)

        req_id = _to_int_or_none(raw_req)

        sy = _norm(sy)
        ss = _norm(ss)
        ey = _norm(ey)
        es = _norm(es)

        # 시작학기(필수): 하나라도 비면 스킵
        if not sy or not ss:
            continue

        joined_year = _to_int_or_none(sy)
        joined_term = ss if ss else None

        # 종료학기(옵션)
        completed_year = _to_int_or_none(ey) if ey else None
        completed_term = es if es else None

        status = "completed" if (completed_year and completed_term) else "ongoing"

        # 중복 방지: 같은 (student_id, curriculum_program_id) 존재 시 skip
        exists = db.exec(
            select(models.StudentCurriculumEnrollment.id).where(
                and_(
                    models.StudentCurriculumEnrollment.student_id == stu.id,
                    models.StudentCurriculumEnrollment.curriculum_program_id == cur_id,
                )
            )
        ).first()
        if exists:
            # 이미 있으면 업데이트? → 요청은 "추가" 중심이므로 우선 skip
            continue

        db.add(models.StudentCurriculumEnrollment(
            student_id=stu.id,
            curriculum_program_id=cur_id,
            requirement_id=req_id,          # None 허용 (이수조건 선택 안 했을 때)
            status=status,
            joined_year=joined_year,
            joined_term=joined_term,
            completed_year=completed_year,
            completed_term=completed_term,
            note=None,
            created_at=now_utc,
            updated_at=now_utc,
        ))

    # -----------------------------
    # 4) 커밋
    # -----------------------------
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        return JSONResponse({"error": "저장 중 제약조건 위반이 발생했습니다.", "detail": str(e)}, status_code=400)

    return RedirectResponse(
        url="/admin/register/student?success=1",
        status_code=302,
    )

@app.post("/admin/register/business")
async def admin_register_business_post(
    request: Request,
    db: Session = Depends(get_session),

    # ---- 기존 필드 그대로 ----
    project_name: str = Form(...),
    support_agency: str = Form(""),
    specialized_institute: str = Form(""),
    research_task_name: str = Form(""),

    start_date: str = Form(...),
    end_date: str = Form(...),

    beneficiary_target: Optional[float] = Form(None),
    output_target: Optional[float] = Form(None),
    career_linked_target: Optional[float] = Form(None),

    # ---- 추가: 수정 모드 식별자 ----
    edit_id: Optional[int] = Form(None),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    # 일정 검증 (기존 형식/메시지 유지)
    try:
        start_date_parsed = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_date_parsed = datetime.strptime(end_date, "%Y-%m-%d").date()
        if end_date_parsed < start_date_parsed:
            return JSONResponse(
                {"error": "종료일은 시작일보다 이후여야 합니다."},
                status_code=400,
            )
    except ValueError:
        return JSONResponse(
            {"error": "날짜 형식이 잘못되었습니다. (YYYY-MM-DD)"},
            status_code=400,
        )

    now_utc = datetime.utcnow()

    if edit_id:
        # ===== 수정 모드 =====
        biz = db.get(models.BusinessInitiative, int(edit_id))
        if biz is None:
            # 잘못된 edit_id면 신규와 동일하게 처리 (혹은 404/에러 응답으로 바꿔도 됨)
            biz = models.BusinessInitiative(created_at=now_utc)

        # 필드 업데이트 (created_at은 보존, updated_at만 갱신)
        biz.project_name = project_name.strip()
        biz.support_agency = (support_agency or "").strip() or None
        biz.specialized_institute = (specialized_institute or "").strip() or None
        biz.research_task_name = (research_task_name or "").strip() or None

        biz.start_date = start_date_parsed
        biz.end_date = end_date_parsed

        biz.beneficiary_target = beneficiary_target
        biz.output_target = output_target
        biz.career_linked_target = career_linked_target

        biz.updated_at = now_utc

        db.add(biz)
        db.commit()
        db.refresh(biz)

        # 수정 후: 목록으로 (요청하신 흐름에 맞춤)
        return RedirectResponse(
            url="/admin/view/business?updated=1",
            status_code=302,
        )
    else:
        # ===== 신규 생성 모드 =====
        biz = models.BusinessInitiative(
            project_name=project_name.strip(),
            support_agency=(support_agency or "").strip() or None,
            specialized_institute=(specialized_institute or "").strip() or None,
            research_task_name=(research_task_name or "").strip() or None,

            start_date=start_date_parsed,
            end_date=end_date_parsed,

            beneficiary_target=beneficiary_target,
            output_target=output_target,
            career_linked_target=career_linked_target,

            created_at=now_utc,
            updated_at=now_utc,
        )

        db.add(biz)
        db.commit()

        # 기존 리다이렉트 패턴 그대로 유지
        return RedirectResponse(
            url="/admin/register/business?success=1",
            status_code=302,
        )
    
@app.post("/admin/register/curriculum")
async def admin_register_curriculum_post(
    request: Request,
    db: Session = Depends(get_session),

    program_type: str = Form(...),
    course_name: str = Form(...),
    degree_type: str = Form(...),
    department_type: str = Form(...),

    open_year: Optional[int] = Form(None),
    open_semester: str = Form(""),
    close_year: Optional[int] = Form(None),
    close_semester: str = Form(""),

    business_initiative_id: Optional[int] = Form(None),

    college_scope: List[str] = Form([]),
    degree_scope: List[str] = Form([]),
    required_credit: List[float] = Form([]),
    total_converted_required: List[float] = Form([]),
    total_internship_required: List[float] = Form([]),

    min_ai_med_talks: List[int] = Form([]),
    min_company_visit: List[int] = Form([]),
    min_hospital_visit: List[int] = Form([]),
    min_seminar: List[int] = Form([]),
    min_exchange_forum: List[int] = Form([]),
    min_expo: List[int] = Form([]),
    min_academic_conf: List[int] = Form([]),
    min_competition: List[int] = Form([]),
    min_etc: List[int] = Form([]),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    now_utc = datetime.utcnow()
    this_year = datetime.now().year
    
    curriculum_row = models.CurriculumProgram(
        business_initiative_id=business_initiative_id if business_initiative_id else None,

        program_type=program_type.strip(),
        course_name=course_name.strip(),
        degree_type=degree_type.strip(),
        department_type=department_type.strip(),

        open_year        = open_year or None,
        open_semester    = open_semester or None,
        close_year       = close_year or None,
        close_semester   = close_semester or None,
        created_at=now_utc,
        updated_at=now_utc,
    )

    db.add(curriculum_row)
    db.flush()  # curriculum_row.id

    # 여러 ProgramRequirement insert
    req_count = max(
        len(college_scope),
        len(degree_scope),
        len(required_credit),
        len(total_converted_required),
        len(total_internship_required),
        len(min_ai_med_talks),
        len(min_company_visit),
        len(min_hospital_visit),
        len(min_seminar),
        len(min_exchange_forum),
        len(min_expo),
        len(min_academic_conf),
        len(min_competition),
        len(min_etc),
    )

    for i in range(req_count):
        col_scope = college_scope[i] if i < len(college_scope) else ""
        deg_scope = degree_scope[i] if i < len(degree_scope) else ""

        gen_code = _generate_requirement_code(
            db,
            college_scope=col_scope,
            degree_scope=deg_scope,
            year=this_year,
        )

        pr = models.ProgramRequirement(
            curriculum_id=curriculum_row.id,
            requirement_code=gen_code,

            college_scope=col_scope,
            degree_scope=deg_scope,

            required_credit=float(required_credit[i]) if i < len(required_credit) else 0.0,
            total_converted_required=float(total_converted_required[i]) if i < len(total_converted_required) else 0.0,
            total_internship_required=float(total_internship_required[i]) if i < len(total_internship_required) else 0.0,

            min_ai_med_talks=int(min_ai_med_talks[i]) if i < len(min_ai_med_talks) else 0,
            min_company_visit=int(min_company_visit[i]) if i < len(min_company_visit) else 0,
            min_hospital_visit=int(min_hospital_visit[i]) if i < len(min_hospital_visit) else 0,
            min_seminar=int(min_seminar[i]) if i < len(min_seminar) else 0,
            min_exchange_forum=int(min_exchange_forum[i]) if i < len(min_exchange_forum) else 0,
            min_expo=int(min_expo[i]) if i < len(min_expo) else 0,
            min_academic_conf=int(min_academic_conf[i]) if i < len(min_academic_conf) else 0,
            min_competition=int(min_competition[i]) if i < len(min_competition) else 0,
            min_etc=int(min_etc[i]) if i < len(min_etc) else 0,
        )
        db.add(pr)

    db.commit()

    return RedirectResponse(
        url="/admin/register/curriculum?success=1",
        status_code=302,
    )


# ==== 변환 헬퍼 ====
def _to_int(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        return None

def _norm_str(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None   # "" -> None

def _safe_get(lst, idx, default=None):
    if lst is None:
        return default
    return lst[idx] if idx < len(lst) else default


@app.post("/admin/register/course")
async def admin_register_course_post(
    request: Request,
    db: Session = Depends(get_session),

    # 필수 문자열
    course_code: str = Form(...),
    course_name_ko: str = Form(...),

    # 선택 문자열 (빈문자 허용 → 내부에서 None 처리)
    course_name_en: Optional[str] = Form(None),

    # 기타 필수들
    degree_level: str = Form(...),
    grade_level: int = Form(...),
    offering_semester: str = Form(...),
    offering_cycle: str = Form(...),

    grading_scheme: str = Form(...),
    credit: int = Form(...),
    lecture_hours: int = Form(...),
    lab_hours: int = Form(...),

    department_name: str = Form(...),
    instructor_name: str = Form(...),

    # ✅ 숫자지만 빈문자 가능 → 문자열로 받아 변환
    capacity: Optional[str] = Form(None),
    enrollment: Optional[str] = Form(None),

    # 매핑 관련
    curriculum_id: List[Optional[str]] = Form([]),
    required_flag: List[str] = Form([]),

    initial_year: List[int] = Form([]),         # 최초 인정 연도는 필수 리스트로 유지
    initial_semester: List[str] = Form([]),

    # ✅ 빈문자 섞일 수 있으므로 문자열 리스트로 받아 변환
    final_year: Optional[List[Optional[str]]] = Form(None),
    final_semester: Optional[List[Optional[str]]] = Form(None),
):
    """
    Course + CurriculumCourseMap[*]

    규칙:
    - course_code 중복이면 insert 안하고 redirect(?error=duplicate_code)
    - final_year 비어있으면 final_year/final_semester 둘 다 NULL
    - curriculum_id 가 "" (미해당) 이거나 숫자변환 불가면 매핑 row 저장 안함
    - capacity/enrollment 등 빈 문자열이 오면 None 처리
    """
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    # 중복 코드 체크
    exists = db.exec(
        select(models.Course).where(models.Course.course_code == course_code)
    ).first()
    if exists:
        redirect_url = (
            "/admin/register/course"
            "?error=duplicate_code"
            f"&code={course_code}"
        )
        return RedirectResponse(url=redirect_url, status_code=303)

    now = datetime.now(timezone.utc)

    # 옵션 숫자 필드 변환
    capacity_i   = _to_int(capacity)
    enrollment_i = _to_int(enrollment)

    # 본문 생성 (빈문자 → None 정리)
    new_course = models.Course(
        course_code      = course_code.strip(),
        course_name_ko   = course_name_ko.strip(),
        course_name_en   = _norm_str(course_name_en),

        degree_level     = degree_level.strip(),
        grade_level      = int(grade_level),
        offering_semester= offering_semester.strip(),
        offering_cycle   = offering_cycle.strip(),

        grading_scheme   = grading_scheme.strip(),
        credit           = int(credit),
        lecture_hours    = int(lecture_hours),
        lab_hours        = int(lab_hours),

        department_name  = department_name.strip(),
        instructor_name  = instructor_name.strip(),
        capacity         = capacity_i,
        enrollment       = enrollment_i,

        created_at       = now,
        updated_at       = now,
    )
    db.add(new_course)
    db.flush()  # PK 확보( course_code가 PK/UK 조합이면 생략 가능, 상황에 맞게)

    # 매핑 행 수 계산
    row_count = max(
        len(curriculum_id),
        len(required_flag),
        len(initial_year),
        len(initial_semester),
    )

    for i in range(row_count):
        raw_cur_id = curriculum_id[i] if i < len(curriculum_id) else None

        # 교육과정 미해당 → skip
        cur_id_norm = _norm_str(raw_cur_id)
        if not cur_id_norm:
            continue
        try:
            cur_id_db = int(cur_id_norm)
        except (TypeError, ValueError):
            continue

        # 필수 여부
        req_flag_val = (
            required_flag[i].strip()
            if i < len(required_flag) and required_flag[i]
            else "선택"
        )

        # 최초 인정 (필수로 유지)
        init_year_val = int(initial_year[i]) if i < len(initial_year) else None
        init_sem_val  = (
            initial_semester[i].strip()
            if i < len(initial_semester) and initial_semester[i]
            else ""
        )

        # 최종 인정 (빈문자 → None)
        fin_year_raw = _safe_get(final_year, i, None)
        fin_sem_raw  = _safe_get(final_semester, i, None)

        fin_year_val = _to_int(fin_year_raw)
        fin_sem_val  = _norm_str(fin_sem_raw)

        # 연도 없으면 학기도 None (무결성 보호)
        if fin_year_val is None:
            fin_sem_val = None

        new_map = models.CurriculumCourseMap(
            curriculum_id    = cur_id_db,
            course_code      = new_course.course_code,
            required_flag    = req_flag_val,

            initial_year     = init_year_val,
            initial_semester = init_sem_val,

            final_year       = fin_year_val,
            final_semester   = fin_sem_val,
        )
        db.add(new_map)

    db.commit()

    redirect_url = (
        "/admin/register/course"
        "?success=1"
        f"&course_name={course_name_ko}"
    )
    return RedirectResponse(url=redirect_url, status_code=303)

# -------------------------------------------------
# register POST handlers (비교과: 수정본)
# -------------------------------------------------

@app.post("/admin/register/extracurricular")
async def admin_register_extracurricular_post(
    request: Request,
    db: Session = Depends(get_session),

    # 기본 정보
    program_name: str = Form(...),
    program_type: str = Form(...),

    # ★추가: 세부 프로그램명 / 주관(Organizer)
    sub_program_name: Optional[str] = Form(None),
    organizer: Optional[str] = Form(None),

    open_year: int = Form(...),
    open_month: int = Form(...),

    # (옵션) 설명 필드가 모델에 있으면 사용, 없으면 무시돼도 무방
    description: Optional[str] = Form(None),

    # 교육과정 매핑
    curriculum_id: List[str] = Form([]),
    recognized_credit_ratio: List[str] = Form([]),
):
    """
    비교과 Program 1건 + CurriculumProgramMap[*]

    규칙:
    - curriculum_id 가 "" (미해당) 이면 insert 안 함
    - curriculum_id 정수 변환 실패해도 insert 안 함
    - recognized_credit_ratio 비어있으면 None
    """
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    # 간단 검증
    try:
        oy = int(open_year)
        om = int(open_month)
        if not (2000 <= oy <= 2100):
            return JSONResponse({"error": "개최 연도는 2000~2100 사이여야 합니다."}, status_code=400)
        if not (1 <= om <= 12):
            return JSONResponse({"error": "개최 월은 1~12 사이여야 합니다."}, status_code=400)
    except Exception:
        return JSONResponse({"error": "연/월 형식이 잘못되었습니다."}, status_code=400)

    now = datetime.now(timezone.utc)

    # Program INSERT (models.Program에 컬럼 존재 전제: sub_program_name, organizer)
    prog = models.Program(
        program_name=program_name.strip(),
        program_type=program_type.strip(),
        sub_program_name=(sub_program_name or "").strip() or None,
        organizer=(organizer or "").strip() or None,
        open_year=oy,
        open_month=om,
        # description 컬럼이 있으면 사용
        **({"description": (description or "").strip() or None} if hasattr(models.Program, "description") else {}),
        created_at=now,
        updated_at=now,
    )
    db.add(prog)
    db.flush()  # prog.id 확보

    # 매핑 저장
    row_count = max(len(curriculum_id), len(recognized_credit_ratio))
    for i in range(row_count):
        raw_cur = curriculum_id[i] if i < len(curriculum_id) else ""
        raw_ratio = recognized_credit_ratio[i] if i < len(recognized_credit_ratio) else ""

        # 미해당/공란 → skip
        if raw_cur is None or raw_cur.strip() == "":
            continue

        # curriculum_id → int
        try:
            cur_id_int = int(raw_cur)
        except (TypeError, ValueError):
            continue

        # 환산점수
        if raw_ratio is None or raw_ratio.strip() == "":
            ratio_val = None
        else:
            try:
                ratio_val = float(raw_ratio)
            except ValueError:
                ratio_val = None

        # CurriculumProgramMap INSERT
        db.add(models.CurriculumProgramMap(
            program_id=prog.id,
            curriculum_id=cur_id_int,
            recognized_credit_ratio=ratio_val,
            created_at=now,
            updated_at=now,
        ))

    db.commit()
    return RedirectResponse(
        url=f"/admin/register/extracurricular?success=1&program_name={program_name}",
        status_code=303,
    )


# -------------------------------------------------
# view pages (GET)
# -------------------------------------------------
@app.get("/admin/view/students", response_class=HTMLResponse)
def admin_view_students_modal(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        "admin_view_students.html",
        {"request": request, "active": "view_students"},
    )


@app.get("/admin/view/business", response_class=HTMLResponse)
def admin_view_business(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse(
        "admin_view_business.html",
        {
            "request": request,
            "active": "view_business",
        },
    )


# ---- 템플릿(목록+상세) 페이지 ----
@app.get("/admin/view/curriculum", response_class=HTMLResponse)
def view_curriculum_page(request: Request):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        "admin_view_curriculum.html",
        {"request": request, "active": "view_curriculum"}
    )

@app.get("/admin/view/courses", response_class=HTMLResponse)
def admin_view_courses(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        "admin_view_courses.html",
        {"request": request, "active": "view_courses"},
    )

@app.get("/admin/view/extracurricular", response_class=HTMLResponse)
def admin_view_extracurricular(request: Request, db: Session = Depends(get_session)):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        "admin_view_extracurricular.html",   # ← 여기만 변경
        {"request": request, "active": "view"}
    )

# (기존에 있다면 중복 정의 금지) Tabulator 목록 응답용 스키마
class TStudentRow(BaseModel):
    id: int
    student_no: str | None = None
    name: str | None = None
    name_en: str | None = None
    degree: str | None = None
    college: str | None = None
    department: str | None = None
    major: str | None = None
    admission_year: int | None = None
    admission_term: str | None = None
    academic_status: str | None = None
    leave_of_absence: str | None = None
    mobile_phone_num: str | None = None
    phone_num: str | None = None
    email_snu: str | None = None
    email_other: str | None = None
    researcher_id: str | None = None
    nationality: str | None = None
    advisor_name: str | None = None
    supervisor_name: str | None = None
    updated_at: str | None = None
    taken_count: int = 0
    program_count: int = 0


# ▶ app/main.py

from fastapi import Query

# 동일 경로 - GET 지원
@app.get("/api/tabulator/students", response_class=JSONResponse)
def tab_students_get(
    request: Request,
    db: Session = Depends(get_session),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1),
):
    if not require_admin(request):
        return JSONResponse({"error": "not_authorized"}, status_code=401)

    S = models.Student
    # 페이지 데이터
    rows = db.exec(
        select(S)
        .order_by(getattr(S, "updated_at", getattr(S, "created_at", None)).desc().nullslast())
        .offset((page - 1) * size)
        .limit(size)
    ).all()

    # 전체 개수
    total = db.exec(select(func.count(S.id))).one()
    total = int(total[0] if isinstance(total, tuple) else total or 0)
    last_page = max(1, (total + size - 1) // size)

    # 응답 포맷 맞추기 (TStudentRow와 동일 필드)
    out = []
    for s in rows:
        ts = getattr(s, "updated_at", None) or getattr(s, "created_at", None)
        out.append({
            "id": s.id,
            "student_no": getattr(s, "student_no", None),
            "name": getattr(s, "name", None),
            "name_en": getattr(s, "name_en", None),
            "degree": getattr(s, "degree", None),
            "college": getattr(s, "college", None),
            "department": getattr(s, "department", None),
            "major": getattr(s, "major", None),
            "admission_year": getattr(s, "admission_year", None),
            "admission_term": getattr(s, "admission_term", None),
            "academic_status": getattr(s, "academic_status", None),
            "leave_of_absence": getattr(s, "leave_of_absence", None),
            "mobile_phone_num": getattr(s, "mobile_phone_num", None),
            "phone_num": getattr(s, "phone_num", None),
            "email_snu": getattr(s, "email_snu", None),
            "email_other": getattr(s, "email_other", None),
            "researcher_id": getattr(s, "researcher_id", None),
            "nationality": getattr(s, "nationality", None),
            "advisor_name": getattr(s, "advisor_name", None),
            "supervisor_name": getattr(s, "supervisor_name", None),
            "updated_at": ts.isoformat() if hasattr(ts, "isoformat") and ts else ts,
            # 필요 시 수강/프로그램 개수 계산 추가 가능
            "taken_count": 0,
            "program_count": 0,
        })
    return JSONResponse({"last_page": last_page, "data": out})

@app.post("/api/tabulator/students", response_class=JSONResponse)
async def tab_students(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return JSONResponse({"error": "not_authorized"}, status_code=401)

    try:
        form = await request.form()
    except Exception:
        form = {}
    page = max(1, int(form.get("page", 1)))
    size = max(1, int(form.get("size", 20)))

    S = models.Student
    rows = db.exec(
        select(S).order_by(getattr(S, "updated_at", getattr(S, "created_at", None)).desc().nullslast())
        .offset((page - 1) * size)
        .limit(size)
    ).all()

    total = db.exec(select(func.count(S.id))).one()
    total = int(total[0] if isinstance(total, tuple) else total)
    last_page = max(1, (total + size - 1) // size)

    SCE = models.StudentCourseEnrollment
    PEN = getattr(models, "ProgramEnrollment", None)

    def count_courses(sid: int) -> int:
        c = db.exec(select(func.count(SCE.id)).where(SCE.student_id == sid)).one()
        return int(c[0] if isinstance(c, tuple) else c or 0)

    def count_programs(sid: int) -> int:
        if PEN is None:
            return 0
        c = db.exec(select(func.count(PEN.id)).where(PEN.student_id == sid)).one()
        return int(c[0] if isinstance(c, tuple) else c or 0)

    out = []
    for s in rows:
        ts = getattr(s, "updated_at", None) or getattr(s, "created_at", None)
        out.append(TStudentRow(
            id=s.id,
            student_no=getattr(s, "student_no", None),
            name=getattr(s, "name", None),
            name_en=getattr(s, "name_en", None),
            degree=getattr(s, "degree", None),
            college=getattr(s, "college", None),
            department=getattr(s, "department", None),
            major=getattr(s, "major", None),
            admission_year=getattr(s, "admission_year", None),
            admission_term=getattr(s, "admission_term", None),
            academic_status=getattr(s, "academic_status", None),
            leave_of_absence=getattr(s, "leave_of_absence", None),
            mobile_phone_num=getattr(s, "mobile_phone_num", None),
            phone_num=getattr(s, "phone_num", None),
            email_snu=getattr(s, "email_snu", None),
            email_other=getattr(s, "email_other", None),
            researcher_id=getattr(s, "researcher_id", None),
            nationality=getattr(s, "nationality", None),
            advisor_name=getattr(s, "advisor_name", None),
            supervisor_name=getattr(s, "supervisor_name", None),
            updated_at=(ts.strftime("%Y-%m-%d") if ts else None),
            taken_count=count_courses(s.id),
            program_count=count_programs(s.id),
        ))

    return JSONResponse({"last_page": last_page, "data": [r.model_dump() for r in out]})

@app.get("/api/tabulator/students/{student_id}/tree", response_class=JSONResponse)
def tab_student_tree(
    student_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return JSONResponse({"error": "not_authorized"}, status_code=401)

    st = db.get(models.Student, student_id)
    if not st:
        return JSONResponse([], status_code=200)

    SEnroll = models.StudentCurriculumEnrollment
    enrolls = db.exec(
        select(SEnroll)
        .where(SEnroll.student_id == student_id)
        .order_by(SEnroll.updated_at.desc())
    ).all()

    # 과목 연결만
    SCE = models.StudentCourseEnrollment
    cols = [SCE.course_code]
    if hasattr(SCE, "year"):     cols.append(SCE.year)
    if hasattr(SCE, "semester"): cols.append(SCE.semester)

    course_rows = db.exec(select(*cols).where(SCE.student_id == student_id)).all()
    per_course = []
    for row in course_rows:
        rec = {"course_code": row[0]}
        idx = 1
        if hasattr(SCE, "year"):     rec["year"] = row[idx]; idx += 1
        if hasattr(SCE, "semester"): rec["semester"] = row[idx]; idx += 1
        per_course.append(rec)

    root = {
        "id": f"student:{st.id}",
        "title": f"{st.name} ({st.student_no})",
        "degree": getattr(st, "degree", None),
        "college": getattr(st, "college", None),
        "major": getattr(st, "major", None),
        "academic_status": getattr(st, "academic_status", None),
        "_children": [],
    }

    CP = models.CurriculumProgram
    CCM = models.CurriculumCourseMap

    for e in enrolls:
        prog = db.get(CP, e.curriculum_program_id)
        prog_title = f"{prog.program_type} - {prog.course_name} ({prog.open_year})" if prog else f"프로그램 ID {e.curriculum_program_id}"
        node = {
            "id": f"prog:{e.id}",
            "title": prog_title,
            "_children": [],
        }

        mapped_set = set()
        if prog:
            mapped = db.exec(select(CCM.course_code).where(CCM.curriculum_id == prog.id)).all()
            mapped_set = {m[0] for m in mapped}

        for rec in per_course:
            if mapped_set and rec.get("course_code") not in mapped_set:
                continue
            node["_children"].append({
                "id": f"course:{rec.get('course_code')}:{rec.get('year')}:{rec.get('semester')}",
                "title": rec.get("course_code"),
                "year": rec.get("year"),
                "semester": rec.get("semester"),
                "_children": [],
            })

        root["_children"].append(node)

    return JSONResponse([root])


# ─────────────────────────────────────────────────────────────
# Course Viewer
# ─────────────────────────────────────────────────────────────
# 1) 코스 목록 (Tabulator 원격 페이지네이션)
class TCourseRow(BaseModel):
    course_code: str
    course_name_ko: str | None = None
    course_name_en: str | None = None
    degree_level: str | None = None
    grade_level: int | None = None
    offering_semester: str | None = None
    offering_cycle: str | None = None
    grading_scheme: str | None = None
    credit: int | None = None
    lecture_hours: int | None = None
    lab_hours: int | None = None
    department_name: str | None = None
    instructor_name: str | None = None
    capacity: int | None = None
    enrollment: int | None = None     # (모델 필드 그대로)
    updated_at: str | None = None

@app.post("/api/tabulator/courses")
def tab_courses(request: Request, db: Session = Depends(get_session),
                page: int = Form(1), size: int = Form(20)):
    q = select(models.Course).order_by(models.Course.updated_at.desc())
    total = db.exec(select(func.count()).select_from(models.Course)).one()
    items = db.exec(q.offset((page-1)*size).limit(size)).all()

    def row(c: models.Course):
        return {
            "course_code": c.course_code,
            "course_name_ko": c.course_name_ko,
            "course_name_en": c.course_name_en,
            "degree_level": c.degree_level,
            "grade_level": c.grade_level,
            "offering_semester": c.offering_semester,
            "offering_cycle": c.offering_cycle,
            "grading_scheme": c.grading_scheme,
            "credit": c.credit,
            "lecture_hours": c.lecture_hours,
            "lab_hours": c.lab_hours,
            "department_name": c.department_name,
            "instructor_name": c.instructor_name,
            "capacity": c.capacity,
            "enrollment": c.enrollment,
            "updated_at": (c.updated_at.isoformat() if c.updated_at else None),
        }

    last_page = max(1, (total + size - 1) // size)
    return {"data": [row(x) for x in items], "last_page": last_page}


@app.get("/api/course/{course_code}/curricula")
def course_curricula(course_code: str, db: Session = Depends(get_session)):
    rows = db.exec(
        select(
            models.CurriculumProgram.course_name.label("course_name"),  # ✅ program_name 아님
            models.CurriculumCourseMap.required_flag,
            models.CurriculumCourseMap.initial_year,
            models.CurriculumCourseMap.initial_semester,
            models.CurriculumCourseMap.final_year,
            models.CurriculumCourseMap.final_semester,
        )
        .join(
            models.CurriculumCourseMap,
            models.CurriculumCourseMap.curriculum_id == models.CurriculumProgram.id,
        )
        .where(models.CurriculumCourseMap.course_code == course_code)
        .order_by(models.CurriculumProgram.course_name)
    ).all()

    return [dict(r._mapping) for r in rows]

# 2) 코스 개요 (모달 상단 카드)
@app.get("/api/course/{code}/overview")
def course_overview(code: str, db: Session = Depends(get_session)):
    c = db.get(models.Course, code)
    if not c:
        return {"ok": False, "message": "not found"}
    # 실제 수강 연결 수
    enrolled_count = db.exec(
        select(func.count()).select_from(models.StudentCourseEnrollment).where(
            models.StudentCourseEnrollment.course_code == code
        )
    ).one()
    return {
        "ok": True,
        "data": {
            "course_code": c.course_code,
            "course_name_ko": c.course_name_ko,
            "course_name_en": c.course_name_en,
            "degree_level": c.degree_level,
            "grade_level": c.grade_level,
            "offering_semester": c.offering_semester,
            "offering_cycle": c.offering_cycle,
            "grading_scheme": c.grading_scheme,
            "credit": c.credit,
            "lecture_hours": c.lecture_hours,
            "lab_hours": c.lab_hours,
            "department_name": c.department_name,
            "instructor_name": c.instructor_name,
            "capacity": c.capacity,
            "enrollment": c.enrollment,
            "enrolled_count": enrolled_count,
            "updated_at": (c.updated_at.isoformat() if c.updated_at else None),
        },
    }

# 3) 특정 코스를 수강하는 학생 리스트
@app.get("/api/course/{course_code}/students")
def course_students(course_code: str, db: Session = Depends(get_session)):
    # ORM 버전 (권장): Row -> dict(r._mapping)
    rows = db.exec(
        select(
            models.Student.id.label("student_id"),
            models.Student.student_no,
            models.Student.name.label("name"),
            models.Student.college,
            models.Student.major,
        )
        .join(
            models.StudentCourseEnrollment,
            models.StudentCourseEnrollment.student_id == models.Student.id,
        )
        .where(models.StudentCourseEnrollment.course_code == course_code)
    ).all()

    return [dict(r._mapping) for r in rows]

# 4) 학생 검색(오토컴플릿: 이름/학번)
@app.get("/api/students/search", response_class=JSONResponse)
def search_students(
    q: str,
    request: Request,
    db: Session = Depends(get_session),
    limit: int = 20,
):
    if not require_admin(request):
        return JSONResponse({"error":"not_authorized"}, status_code=401)

    Student = models.Student
    q_like = f"%{q.strip()}%"
    rows = db.exec(
        select(Student.id, Student.student_no, Student.name, Student.college, Student.major)
        .where(getattr(Student, "status", "active") == "active")
        .where(or_(Student.name.ilike(q_like), Student.student_no.ilike(q_like)))
        .order_by(Student.name.asc())
        .limit(limit)
    ).all()

    return JSONResponse([
        {"student_id": sid, "label": f"{name} ({sno})", "student_no": sno, "name": name, "college": college, "major": major}
        for sid, sno, name, college, major in rows
    ])

# 5) 코스에 학생 추가 / 제거 (수강 연결 생성/해제)
@app.post("/api/course/{course_code}/add_student")
def add_student_to_course(
    course_code: str,
    student_id: int = Form(...),
    db: Session = Depends(get_session),
):
    # 이미 존재하는지 체크 (unique 제약 있을 때 안전)
    exists = db.exec(
        select(models.StudentCourseEnrollment).where(
            models.StudentCourseEnrollment.course_code == course_code,
            models.StudentCourseEnrollment.student_id == student_id,
        )
    ).first()
    if exists:
        return {"ok": True, "message": "이미 등록되어 있습니다."}

    item = models.StudentCourseEnrollment(course_code=course_code, student_id=student_id)
    db.add(item)
    db.commit()
    return {"ok": True}

@app.post("/api/course/{course_code}/{student_id}/remove")
def remove_student_from_course(
    course_code: str,
    student_id: int,
    db: Session = Depends(get_session),
):
    row = db.exec(
        select(models.StudentCourseEnrollment).where(
            models.StudentCourseEnrollment.course_code == course_code,
            models.StudentCourseEnrollment.student_id == student_id,
        )
    ).first()
    if not row:
        return {"ok": False, "message": "연결 기록이 없습니다."}

    db.delete(row)
    db.commit()
    return {"ok": True}
# === END: Course viewer backend ===

class TBusinessRow(BaseModel):
    id: int
    project_name: str | None = None
    start_date: str | None = None     # ISO (YYYY-MM-DD)
    end_date: str | None = None       # ISO (YYYY-MM-DD)
    support_agency: str | None = None
    specialized_institute: str | None = None
    research_task_name: str | None = None
    beneficiary_target: float | None = None
    output_target: float | None = None
    career_linked_target: float | None = None
    curriculum_count: int = 0
    updated_at: str | None = None     # ISO

@app.post("/api/tabulator/business", response_class=JSONResponse)
def tab_business(
    request: Request,
    db: Session = Depends(get_session),
):
    form = request._form or {}
    form = dict(form)

    page = int(form.get("page", 1))
    size = int(form.get("size", 20)) or 20

    # 총 개수
    total: int = db.exec(select(func.count(models.BusinessInitiative.id))).one()
    last_page = max(1, (total + size - 1) // size)

    # 페이지 데이터 (조인/이거 저거 없이 단일 테이블만)
    stmt = (
        select(models.BusinessInitiative)
        .order_by(models.BusinessInitiative.updated_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows: list[models.BusinessInitiative] = db.exec(stmt).all()

    data = []
    for b in rows:
        data.append({
            "id": b.id,
            # ← 변수명 교정
            "project_name": b.project_name,                      # 사업명
            "support_agency": b.support_agency or "",            # 지원부처
            "specialized_institute": b.specialized_institute or "",  # 주관/전문기관
            "research_task_name": b.research_task_name or "",
            "period": f"{b.start_date or ''} ~ {b.end_date or ''}".strip(),
            "status": "active",  # 상태 필드가 모델에 없으니 임시/고정이라면 유지
            "updated_at": (b.updated_at.isoformat() if b.updated_at else ""),
        })

    return JSONResponse({"data": data, "last_page": last_page})


# 상세 팝업용 개요
# /api/business/{bid}/curricula
# @app.get("/api/business/{bid}/curricula")
# def business_curricula(
#     bid: int,
#     db: Session = Depends(get_session),
# ):
#     rows = db.exec(
#         select(
#             models.CurriculumProgram.id,
#             models.CurriculumProgram.program_name,
#             models.CurriculumProgram.college_scope,
#             models.CurriculumProgram.degree_scope,
#             models.CurriculumProgram.created_at,
#         )
#         .where(models.CurriculumProgram.business_initiative_id == bid)
#         .order_by(models.CurriculumProgram.program_name)
#     ).all()

#     data = []
#     for (pid, program_name, college_scope, degree_scope, created_at) in rows:
#         data.append({
#             "id": pid,
#             "program_name": program_name,
#             "college_scope": college_scope,
#             "degree_scope": degree_scope,
#             "created_at": created_at.isoformat() if created_at else "",
#         })
#     return data

# /api/business/{id}/curricula : 선택 행의 교육과정 상세 (모달용)
#     교과목 조회에서 개별 상세 API 패턴을 그대로 따름
@app.get("/api/business/{biz_id}/curricula")
def business_curricula(
        biz_id: int,
        request: Request,
        db: Session = Depends(get_session),
    ):
    if not require_admin(request):
        return []  # Tabulator 깨지지 않게 빈배열

    CP = models.CurriculumProgram
    PR = models.ProgramRequirement

    # 각 교육과정별 "가장 최신" ProgramRequirement 하나만 붙여서 college/degree scope를 뽑는다
    # (id가 최근 것이 최신이라는 가정. updated_at 기준이면 그걸로 바꿔도 됩니다)
    latest_req_subq = (
        select(
            PR.curriculum_id,
            func.max(PR.id).label("latest_pr_id"),
        )
        .group_by(PR.curriculum_id)
        .subquery()
    )
    PR_latest = aliased(PR)

    rows = db.exec(
        select(
            CP.id,
            CP.course_name,           # -> program_name 으로 내보냄
            PR_latest.college_scope,  # -> college_scope
            PR_latest.degree_scope,   # -> degree_scope
            CP.created_at,            # -> created_at
        )
        .join(latest_req_subq, latest_req_subq.c.curriculum_id == CP.id, isouter=True)
        .join(PR_latest, PR_latest.id == latest_req_subq.c.latest_pr_id, isouter=True)
        .where(CP.business_initiative_id == biz_id)
        .order_by(CP.updated_at.desc().nullslast(), CP.course_name.asc())
    ).all()

    # 프런트의 Tabulator 컬럼 키에 정확히 맞춰서 반환
    return [
        {
            "id": cid,
            "program_name": cname,
            "college_scope": col_scope or "",
            "degree_scope": deg_scope or "",
            "created_at": (created.isoformat() if created else ""),
        }
        for (cid, cname, col_scope, deg_scope, created) in rows
    ]

# -------------------------------------------------------------------
# 공통: ISO 포맷 헬퍼
# -------------------------------------------------------------------
def _iso(x: Any) -> str:
    if isinstance(x, (dt.datetime, dt.date)):
        try:
            return x.isoformat()
        except Exception:
            return str(x)
    return str(x) if x is not None else ""


# /api/business/{bid}/overview
@app.get("/api/business/{bid}/overview", response_class=JSONResponse)
def business_overview(
    bid: int,
    db: Session = Depends(get_session),
):
    b = db.get(models.BusinessInitiative, bid)
    if not b:
        return JSONResponse({"ok": False, "message": "not found"}, status_code=404)

    data = {
        "id": b.id,
        "project_name": b.project_name,
        "support_agency": b.support_agency,
        "specialized_institute": b.specialized_institute,
        "research_task_name": b.research_task_name,
        "start_date": b.start_date.isoformat() if b.start_date else None,
        "end_date": b.end_date.isoformat() if b.end_date else None,
        "beneficiary_target": b.beneficiary_target,
        "output_target": b.output_target,
        "career_linked_target": b.career_linked_target,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "updated_at": b.updated_at.isoformat() if b.updated_at else None,
    }
    return {"ok": True, "data": data}

@app.post("/api/tabulator/extracurricular", response_class=JSONResponse)
def tab_extracurricular(
    request: Request,
    db: Session = Depends(get_session),
):
    # FastAPI sync 핸들러에서 미리 파싱된 form 캐시 활용
    form = request._form or {}
    form = dict(form)

    page = int(form.get("page", 1))
    size = int(form.get("size", 20))
    if size <= 0:
        size = 20

    # 총 개수
    total_res = db.exec(select(func.count()).select_from(models.Program)).one()
    total = total_res[0] if isinstance(total_res, tuple) else int(total_res)
    last_page = max(1, (total + size - 1) // size)

    # 페이지 데이터 (관계 로딩 비활성화)
    stmt = (
        select(models.Program)
        .options(noload("*"))
        .order_by(models.Program.updated_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    rows: List[models.Program] = db.exec(stmt).all()

    data = []
    for p in rows:
        data.append({
            "id": p.id,
            "open_year": p.open_year,
            "open_month": p.open_month,
            "program_type": p.program_type,
            "program_name": p.program_name,
            "sub_program_name": p.sub_program_name or "",
            "organizer": p.organizer or "",
            "updated_at": _iso(getattr(p, "updated_at", None)),
        })

    return JSONResponse({"data": data, "last_page": last_page})

# -------------------------------------------------------------------
# 2) 비교과 프로그램 개요
#    GET /api/program/{id}/overview
# -------------------------------------------------------------------
@app.get("/api/program/{program_id}/overview")
def get_program_overview(program_id: int, db: Session = Depends(get_session)):
    prog = db.get(models.Program, program_id)
    if not prog:
        return {"ok": False, "message": "program not found"}

    data = {
        "id": prog.id,
        "open_year": prog.open_year,
        "open_month": prog.open_month,
        "program_type": prog.program_type,
        "program_name": prog.program_name,
        "sub_program_name": prog.sub_program_name,
        "organizer": prog.organizer,
        "event_material": prog.event_material,
        "created_at": prog.created_at.isoformat() if prog.created_at else None,
        "updated_at": prog.updated_at.isoformat() if prog.updated_at else None,
    }

    # ✅ 스키마에 맞춰 조인: CurriculumProgram.course_name / program_type 사용
    q = (
        select(
            models.CurriculumProgramMap.id,                     # map_id
            models.CurriculumProgram.id,                        # curriculum_id
            models.CurriculumProgram.course_name,               # curriculum_name
            models.CurriculumProgram.program_type,              # curriculum_program_type
            models.CurriculumProgramMap.recognized_credit_ratio # ratio
        )
        .join(
            models.CurriculumProgram,
            models.CurriculumProgram.id == models.CurriculumProgramMap.curriculum_id,
        )
        .where(models.CurriculumProgramMap.program_id == program_id)
        .order_by(models.CurriculumProgram.course_name.asc())
    )
    rows = db.exec(q).all()

    curricula = []
    for (map_id, cur_id, course_name, cur_prog_type, ratio) in rows:
        curricula.append({
            "map_id": map_id,
            "curriculum_id": cur_id,
            "curriculum_name": course_name,               # 프런트에서 그대로 사용
            "curriculum_type": cur_prog_type,             # (인증제/교과인증과정/교과과정)
            "recognized_credit_ratio": float(ratio) if ratio is not None else None,
        })

    data["curricula"] = curricula
    return {"ok": True, "data": data}
# -------------------------------------------------------------------
# 3) 비교과 프로그램 참석자 목록
#    GET /api/program/{id}/enrollments
#    - ProgramEnrollment ↔ Participant (필요 시 Student)
# -------------------------------------------------------------------
@app.get("/api/program/{program_id}/enrollments", response_class=JSONResponse)
def program_enrollments(
    program_id: int,
    db: Session = Depends(get_session),
):
    # Program 존재 확인 (404 방지)
    if not db.get(models.Program, program_id):
        return JSONResponse({"ok": False, "message": "Not found"}, status_code=404)

    # Participant를 조인해 사람이름/이메일을 붙여준다.
    stmt = (
        select(models.ProgramEnrollment, models.Participant)
        .where(models.ProgramEnrollment.program_id == program_id)
        .where(models.ProgramEnrollment.participant_id == models.Participant.id)
        .order_by(models.ProgramEnrollment.updated_at.desc())
    )
    rows: List[Tuple[models.ProgramEnrollment, models.Participant]] = db.exec(stmt).all()

    data = []
    for enr, part in rows:
        data.append({
            "participation_type": enr.participation_type,
            "affiliation_snapshot": enr.affiliation_snapshot,
            "degree_program_snapshot": enr.degree_program_snapshot or "",
            "student_no_snapshot": enr.student_no_snapshot or "",
            "student_id": enr.student_id,  # 내부 학생 귀속 ID 스냅샷
            "name": part.name,
            "email": part.email,
            "enroll_source": enr.enroll_source or "",
            "exception_case": bool(enr.exception_case),
            "updated_at": _iso(getattr(enr, "updated_at", None)),
        })
    return JSONResponse(data)

# -------------------------------------------------------------------
# 4) 비교과 프로그램 참석자 등록
#    POST /api/program/{id}/add_enrollment
#    - mode = "student" 또는 "external"
#    - recognized_credit(환산점수)는 현재 제외 (요청 사양)
# -------------------------------------------------------------------
@app.post("/api/program/{program_id}/add_enrollment", response_class=JSONResponse)
async def add_program_enrollment(
    program_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    # 프로그램 확인
    prog: models.Program | None = db.get(models.Program, program_id)
    if not prog:
        return JSONResponse({"ok": False, "message": "Program not found"}, status_code=404)

    form = await request.form()
    mode = (form.get("mode") or "").strip()

    # 공통 스냅샷
    participation_type = (form.get("participation_type") or "").strip()  # 운영진/교수/조교/연구원/학생/외부
    degree_program_snapshot = (form.get("degree_program_snapshot") or "").strip() or None
    student_no_snapshot = (form.get("student_no_snapshot") or "").strip() or None
    affiliation_snapshot = (form.get("affiliation_snapshot") or "").strip()

    if not participation_type:
        return JSONResponse({"ok": False, "message": "참석자 구분이 필요합니다."}, status_code=400)
    if not affiliation_snapshot:
        return JSONResponse({"ok": False, "message": "소속(스냅샷)이 필요합니다."}, status_code=400)

    # -----------------------------------------------------------------
    # 내부 학생 모드
    # -----------------------------------------------------------------
    if mode == "student":
        sid_raw = form.get("student_id")
        try:
            student_id = int(sid_raw) if sid_raw is not None else None
        except Exception:
            student_id = None

        if not student_id:
            return JSONResponse({"ok": False, "message": "학생 선택이 필요합니다."}, status_code=400)

        stu: models.Student | None = db.get(models.Student, student_id)
        if not stu:
            return JSONResponse({"ok": False, "message": "학생을 찾을 수 없습니다."}, status_code=404)

        # Participant(내부 학생) 찾거나 생성
        # - participant unique: (affiliation, name, email)
        #   내부 학생은 '소속=학생 소속(예: 단과대/학과 등)' + '이름' + '학교 이메일'을 보통 사용
        base_aff = affiliation_snapshot  # 스냅샷과 동일하게 간다
        base_name = getattr(stu, "name", None) or getattr(stu, "name_ko", None) or "(학생)"
        base_email = getattr(stu, "school_email", None) or getattr(stu, "email", None) or f"student{stu.id}@example.com"

        part_stmt = select(models.Participant).where(
            models.Participant.affiliation == base_aff,
            models.Participant.name == base_name,
            models.Participant.email == base_email,
        )
        part = db.exec(part_stmt).first()
        if not part:
            part = models.Participant(
                student_id=stu.id,
                affiliation=base_aff,
                name=base_name,
                email=base_email,
            )
            db.add(part)
            db.commit()
            db.refresh(part)

        # Enrollment 생성
        enr = models.ProgramEnrollment(
            program_id=prog.id,
            participant_id=part.id,
            student_id=stu.id,  # 내부 학생에게 귀속
            participation_type=participation_type,
            affiliation_snapshot=affiliation_snapshot,
            degree_program_snapshot=degree_program_snapshot,
            student_no_snapshot=student_no_snapshot or getattr(stu, "student_no", None),
            recognized_credit=None,     # 현재 환산점수 제외
            enroll_source="manual",
            exception_case=False,
        )
        try:
            db.add(enr)
            db.commit()
        except IntegrityError:
            db.rollback()
            # uq_program_participant 중복인 경우
            return JSONResponse({"ok": False, "message": "이미 등록된 참석자입니다."}, status_code=409)

        return JSONResponse({"ok": True})

    # -----------------------------------------------------------------
    # 외부 참석자 모드
    # -----------------------------------------------------------------
    elif mode == "external":
        ext_aff = (form.get("ext_affiliation") or "").strip()
        ext_name = (form.get("ext_name") or "").strip()
        ext_email = (form.get("ext_email") or "").strip()

        if not ext_aff or not ext_name or not ext_email:
            return JSONResponse({"ok": False, "message": "외부 참석자 소속/이름/이메일이 필요합니다."}, status_code=400)

        # Participant(외부) 찾거나 생성
        part_stmt = select(models.Participant).where(
            models.Participant.affiliation == ext_aff,
            models.Participant.name == ext_name,
            models.Participant.email == ext_email,
        )
        part = db.exec(part_stmt).first()
        if not part:
            part = models.Participant(
                student_id=None,
                affiliation=ext_aff,
                name=ext_name,
                email=ext_email,
            )
            db.add(part)
            db.commit()
            db.refresh(part)

        # Enrollment 생성 (외부는 student_id=None)
        enr = models.ProgramEnrollment(
            program_id=prog.id,
            participant_id=part.id,
            student_id=None,
            participation_type=participation_type,
            affiliation_snapshot=affiliation_snapshot,
            degree_program_snapshot=degree_program_snapshot,
            student_no_snapshot=student_no_snapshot or None,
            recognized_credit=None,     # 현재 환산점수 제외
            enroll_source="manual",
            exception_case=False,
        )
        try:
            db.add(enr)
            db.commit()
        except IntegrityError:
            db.rollback()
            return JSONResponse({"ok": False, "message": "이미 등록된 참석자입니다."}, status_code=409)

        return JSONResponse({"ok": True})

    # -----------------------------------------------------------------
    # 알 수 없는 모드
    # -----------------------------------------------------------------
    else:
        return JSONResponse({"ok": False, "message": "mode 는 student | external 이어야 합니다."}, status_code=400)
    
# === Pydantic schemas: Curriculum ===

class TCurRow(BaseModel):
    id: int
    program_type: Optional[str] = None
    course_name: Optional[str] = None
    degree_department: Optional[str] = None   # "학위 / 학과"
    open: Optional[str] = None                # "YYYY 학기"
    close: Optional[str] = None               # "YYYY 학기" (없을 수 있음)
    business_name: Optional[str] = None
    student_count: int = 0
    program_count: int = 0
    updated_at: Optional[str] = None

class TabPageCurricula(BaseModel):
    data: List[TCurRow]
    last_page: int

class CurOverview(BaseModel):
    id: int
    program_type: Optional[str] = None
    course_name: Optional[str] = None
    degree_type: Optional[str] = None
    department_type: Optional[str] = None
    open_year: Optional[int] = None
    open_semester: Optional[str] = None
    close_year: Optional[int] = None
    close_semester: Optional[str] = None
    business_initiative_id: Optional[int] = None
    business_name: Optional[str] = None
    student_count: int = 0
    program_count: int = 0
    updated_at: Optional[str] = None

class OkMessage(BaseModel):
    ok: bool = True
    message: Optional[str] = None

class CurOverviewResp(OkMessage):
    data: Optional[CurOverview] = None

class CurStudentRow(BaseModel):
    student_no: Optional[str] = None
    name: Optional[str] = None
    status: Optional[str] = None              # ongoing/completed/...
    joined: Optional[str] = None              # "YYYY 학기"
    completed: Optional[str] = None           # "YYYY 학기"
    requirement_code: Optional[str] = None    # 적용 요건 코드

class CurStudentListResp(OkMessage):
    data: List[CurStudentRow] = []

class CurProgramRow(BaseModel):
    program_type: Optional[str] = None
    program_name: Optional[str] = None
    open: Optional[str] = None                 # "YYYY/MM"
    recognized_credit_ratio: Optional[float] = None

class CurProgramListResp(OkMessage):
    data: List[CurProgramRow] = []


# ── 공통 유틸
def _to0(x): 
    try: return int(x) if x is not None else 0
    except: return 0
def _f0(x):
    try: return float(x) if x is not None else 0.0
    except: return 0.0

# ── 학생 목록(진도 집계 포함): /api/tabulator/curriculum/{cur_id}/students
class TCurStudentRow(BaseModel):
    student_id: int
    student_no: Optional[str]
    name: Optional[str]
    status: Optional[str]

    # 등록(연/학기) 분리
    joined_year: Optional[int] = None
    joined_term: Optional[str] = None

    # 종료(연/학기) 분리 ✅ 추가
    completed_year: Optional[int] = None
    completed_term: Optional[str] = None

    # 요건코드
    requirement_code: Optional[str] = None

    # 집계
    course_total_credit: float = 0.0
    extrac_converted_total: float = 0.0
    extrac_count: int = 0

    # 최소 카테고리별 횟수
    min_ai_med_talks: int = 0
    min_company_visit: int = 0
    min_hospital_visit: int = 0
    min_seminar: int = 0
    min_exchange_forum: int = 0
    min_expo: int = 0
    min_academic_conf: int = 0
    min_competition: int = 0
    min_etc: int = 0

    # 충족 여부
    required_core_done: bool = True
    pass_credit: bool = True
    pass_converted: bool = True
    pass_minimum: bool = True
    pass_all: bool = True  # ← 화면에서 “이수조건 충족”으로 표시


@app.post("/api/tabulator/curriculum", response_class=JSONResponse)
def tab_curriculum(
    request: Request,
    db: Session = Depends(get_session),
    page: int = Form(1),
    size: int = Form(20),
    sorters: Optional[str] = Form(None),
    filter: Optional[str] = Form(None),
):
    if not require_admin(request):
        return JSONResponse({"error":"not_authorized"}, status_code=401)

    CP   = models.CurriculumProgram
    SEn  = models.StudentCurriculumEnrollment
    CPMp = getattr(models, "CurriculumProgramMap", None)
    BI   = models.BusinessInitiative

    # 기본 쿼리(집계 포함)
    q = (
        select(
            CP.id,
            CP.program_type,
            CP.course_name,
            CP.degree_type, CP.department_type,
            CP.open_year, CP.open_semester,
            CP.close_year, CP.close_semester,
            CP.updated_at,
            BI.project_name.label("business_name"),
            func.count(func.distinct(SEn.student_id)).label("student_count"),
            (func.count(func.distinct(CPMp.program_id)) if CPMp is not None else func.literal(0)).label("program_count"),
        )
        .select_from(CP)
        .join(BI, BI.id == CP.business_initiative_id, isouter=True)
        .join(SEn, SEn.curriculum_program_id == CP.id, isouter=True)
    )

    if CPMp is not None:
        q = q.join(CPMp, CPMp.curriculum_id == CP.id, isouter=True)

    q = q.group_by(CP.id, BI.project_name)

    # 정렬 (기본: updated_at desc)
    default_order = [CP.updated_at.desc().nullslast()]
    try:
        s_list = json.loads(sorters) if sorters else []
    except Exception:
        s_list = []
    order = []
    for s in s_list:
        fld = (s.get("field") or "")
        dr  = (s.get("dir") or "asc").lower()
        desc = (dr == "desc")
        if fld == "program_type": order.append(CP.program_type.desc() if desc else CP.program_type.asc())
        elif fld == "course_name": order.append(CP.course_name.desc() if desc else CP.course_name.asc())
        elif fld == "degree_department": 
            # degree/department 복합 필드 → degree_type 우선
            order.append(CP.degree_type.desc() if desc else CP.degree_type.asc())
            order.append(CP.department_type.desc() if desc else CP.department_type.asc())
        elif fld == "open": 
            order.append(CP.open_year.desc() if desc else CP.open_year.asc())
            order.append(CP.open_semester.desc() if desc else CP.open_semester.asc())
        elif fld == "close":
            order.append(CP.close_year.desc() if desc else CP.close_year.asc())
            order.append(CP.close_semester.desc() if desc else CP.close_semester.asc())
        elif fld == "business_name":
            order.append(BI.project_name.desc() if desc else BI.project_name.asc())
        elif fld == "student_count":
            order.append(func.count(func.distinct(SEn.student_id)).desc() if desc else func.count(func.distinct(SEn.student_id)).asc())
        elif fld == "program_count" and CPMp is not None:
            order.append(func.count(func.distinct(CPMp.program_id)).desc() if desc else func.count(func.distinct(CPMp.program_id)).asc())
        elif fld == "updated_at":
            order.append(CP.updated_at.desc().nullslast() if desc else CP.updated_at.asc().nullsfirst())
    if not order:
        order = default_order
    q = q.order_by(*order)

    # 필터(간단 like/eq/숫자 비교 지원)
    def apply_filters(stmt):
        try:
            filters = json.loads(filter) if filter else []
        except Exception:
            filters = []
        for f in filters:
            fld = f.get("field"); typ=(f.get("type") or "like").lower(); val=f.get("value")
            if not fld: continue
            col = None
            if fld == "program_type": col = CP.program_type
            elif fld == "course_name": col = CP.course_name
            elif fld == "business_name": col = BI.project_name
            elif fld == "open":  # "YYYY 학기"로 들어오면 연도만 비교(부분일치)
                col = CP.open_year
                try:
                    yy = int(str(val)[:4]); 
                    stmt = stmt.where(col == yy)
                    continue
                except: continue
            elif fld == "close":
                col = CP.close_year
                try:
                    yy = int(str(val)[:4]); 
                    stmt = stmt.where(col == yy)
                    continue
                except: continue
            elif fld == "student_count":
                # 집계 필드는 사후 필터링이 편하지만, 여기선 rough 하게 처리 → 사후 필터 권장
                pass
            if col is None: 
                continue
            if typ in ("like","contains"):
                stmt = stmt.where(col.ilike(f"%{val}%"))
            elif typ in ("=","eq"):
                stmt = stmt.where(col == val)
            elif typ in ("!=","ne"):
                stmt = stmt.where(col != val)
        return stmt

    q = apply_filters(q)

    # total 계산
    total = db.exec(select(func.count(CP.id))).one()
    last_page = max(1, (total + size - 1) // size)

    # 페이지
    rows = db.exec(q.offset((page-1)*size).limit(size)).all()

    def _sem_str(y, s):
        y = (y or ""); s = (s or "")
        return f"{y} {s}".strip() if y or s else ""

    data = []
    for (cid, ptype, cname, deg, dept, oy, os, cy, cs, uat, biz, stu_cnt, prog_cnt) in rows:
        data.append(TCurRow(
            id=cid,
            program_type=ptype,
            course_name=cname,
            degree_department=f"{deg or '-'} / {dept or '-'}",
            open=_sem_str(oy, os),
            close=_sem_str(cy, cs),
            business_name=biz or "",
            student_count=int(stu_cnt or 0),
            program_count=int(prog_cnt or 0),
            updated_at=_iso_or_none(uat) or "",
        ))

    return JSONResponse(TabPageCurricula(data=data, last_page=last_page).model_dump())

@app.get("/api/tabulator/curriculum/{cur_id}/overview", response_class=JSONResponse)
def curriculum_overview(
    cur_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return JSONResponse({"ok": False, "message": "not_authorized"}, status_code=401)

    CP  = models.CurriculumProgram
    SEn = models.StudentCurriculumEnrollment
    CPM = getattr(models, "CurriculumProgramMap", None)
    BI  = models.BusinessInitiative

    cur = db.get(CP, cur_id)
    if not cur:
        return JSONResponse({"ok": False, "message": "not_found"}, status_code=404)

    stu_cnt = db.exec(
        select(func.count(func.distinct(SEn.student_id)))
        .where(SEn.curriculum_program_id == cur_id)
    ).one()
    stu_cnt = int(stu_cnt[0] if isinstance(stu_cnt, tuple) else stu_cnt)

    prog_cnt = 0
    if CPM is not None:
        prog_cnt = db.exec(
            select(func.count(func.distinct(CPM.program_id))).where(CPM.curriculum_id == cur_id)
        ).one()
        prog_cnt = int(prog_cnt[0] if isinstance(prog_cnt, tuple) else prog_cnt)

    bi_name = None
    if getattr(cur, "business_initiative_id", None):
        bi = db.get(BI, cur.business_initiative_id)
        bi_name = getattr(bi, "project_name", None)

    data = CurOverview(
        id=cur.id,
        program_type=cur.program_type,
        course_name=cur.course_name,
        degree_type=cur.degree_type,
        department_type=cur.department_type,
        open_year=cur.open_year,
        open_semester=cur.open_semester,
        close_year=cur.close_year,
        close_semester=cur.close_semester,
        business_initiative_id=getattr(cur, "business_initiative_id", None),
        business_name=bi_name or None,
        student_count=stu_cnt,
        program_count=prog_cnt,
        updated_at=_iso_or_none(getattr(cur, "updated_at", None)) or None,
    )
    return JSONResponse(CurOverviewResp(ok=True, data=data).model_dump())


@app.post("/api/tabulator/curriculum/{cur_id}/students", response_class=JSONResponse)
def tab_curriculum_students(
    cur_id: int,
    request: Request,
    db: Session = Depends(get_session),
    page: int = Form(1),
    size: int = Form(20),
    sorters: Optional[str] = Form(None),
    filter: Optional[str] = Form(None),
):
    if not require_admin(request):
        return JSONResponse({"error":"not_authorized"}, status_code=401)

    S    = models.Student
    SEn  = models.StudentCurriculumEnrollment
    PR   = models.ProgramRequirement
    SCE  = models.StudentCourseEnrollment
    C    = models.Course
    CCM  = models.CurriculumCourseMap
    CPM  = getattr(models, "CurriculumProgramMap", None)
    P    = getattr(models, "Program", None)
    PEN  = getattr(models, "ProgramEnrollment", None)

    # === 프로그램 타입 → 카테고리 키 정확매핑 ===
    EXACT_TYPE_TO_KEY = {
        "SNU AI.MED talks 시리즈": "min_ai_med_talks",
        "기업 견학":               "min_company_visit",
        "병원 견학":               "min_hospital_visit",
        "교육 및 세미나":           "min_seminar",
        "성과교류회":              "min_exchange_forum",
        "박람회":                 "min_expo",
        "학회":                   "min_academic_conf",
        "경진대회":                "min_competition",
        "기타":                   "min_etc",
    }
    def detect_category_key(program_type: str) -> str:
        if not program_type:
            return "min_etc"
        # 사전에 없는 문자열은 기타로 귀속 (새 유형이 들어와도 누락되지 않도록)
        return EXACT_TYPE_TO_KEY.get(program_type.strip(), "min_etc")

    # 대표 이수요건(가장 최신) – 비교 기준
    req = db.exec(
        select(PR).where(PR.curriculum_id == cur_id).order_by(PR.id.desc())
    ).first()
    req_need_credit   = _f0(getattr(req, "required_credit", 0))
    req_need_conv     = _f0(getattr(req, "total_converted_required", 0))
    # 비교과 "총 참여 횟수" 최소(있으면 진행률 표시용으로 사용)
    req_need_count    = _f0(getattr(req, "min_nca_count", 0))
    req_min = {
        "min_ai_med_talks":     _to0(getattr(req, "min_ai_med_talks", 0)),
        "min_company_visit":    _to0(getattr(req, "min_company_visit", 0)),
        "min_hospital_visit":   _to0(getattr(req, "min_hospital_visit", 0)),
        "min_seminar":          _to0(getattr(req, "min_seminar", 0)),
        "min_exchange_forum":   _to0(getattr(req, "min_exchange_forum", 0)),
        "min_expo":             _to0(getattr(req, "min_expo", 0)),
        "min_academic_conf":    _to0(getattr(req, "min_academic_conf", 0)),
        "min_competition":      _to0(getattr(req, "min_competition", 0)),
        "min_etc":              _to0(getattr(req, "min_etc", 0)),
    }
    CCM = models.CurriculumCourseMap
    required_course_set = {
        code for code, rflag in db.exec(
            select(CCM.course_code, CCM.required_flag)
            .where(CCM.curriculum_id == cur_id)
        ).all()
        if rflag == "필수"
    }
    # 해당 과정 등록 학생
    base_rows = db.exec(
        select(
            S.id, S.student_no, S.name,
            SEn.status, SEn.joined_year, SEn.joined_term,
            SEn.completed_year, SEn.completed_term,
            PR.requirement_code
        )
        .join(SEn, S.id == SEn.student_id)
        .join(PR, PR.id == SEn.requirement_id, isouter=True)
        .where(SEn.curriculum_program_id == cur_id)
        .order_by(S.name.asc())
    ).all()

    # 미리: curriculum 매핑된 program 비율 맵
    prog_ratio: Dict[int,float] = {}
    if CPM is not None:
        for pid, ratio in db.exec(
            select(CPM.program_id, CPM.recognized_credit_ratio)
            .where(CPM.curriculum_id == cur_id)
        ).all():
            prog_ratio[int(pid)] = _f0(ratio)

    data: List[TCurStudentRow] = []
    for (sid, sno, sname, st, jy, jt, cy, ct, rcode) in base_rows:
        # 교과 총학점 (이 과정에 매핑된 과목만 합산)
        credit_sum = db.exec(
            select(func.coalesce(func.sum(C.credit), 0.0))
            .select_from(SCE)
            .join(C, C.course_code == SCE.course_code)
            .join(CCM, and_(CCM.course_code == SCE.course_code,
                            CCM.curriculum_id == cur_id))
            .where(SCE.student_id == sid)
        ).one()
        credit_sum = _f0(credit_sum[0] if isinstance(credit_sum, tuple) else credit_sum)

        # 비교과 참여/환산 + 카테고리별 최소횟수 카운트(정확 매핑)
        ex_count = 0
        ex_conv = 0.0
        mins = {k: 0 for k in req_min.keys()}

        if P is not None and PEN is not None and prog_ratio:
            rows = db.exec(
                select(PEN.program_id, P.program_type)
                .join(P, P.id == PEN.program_id)
                .where(PEN.student_id == sid)
                .where(PEN.program_id.in_(prog_ratio.keys()))
            ).all()
            ex_count = len(rows)
            for (pid, ptype) in rows:
                ex_conv += prog_ratio.get(int(pid), 0.0)
                mins[detect_category_key(ptype)] += 1

        _res = db.exec(
            select(SCE.course_code).where(SCE.student_id == sid)
        ).all()

        if not _res:
            taken_codes = set()
        elif isinstance(_res[0], (tuple, list)):
            taken_codes = {row[0] for row in _res}
        else:
            # 이미 스칼라 리스트인 경우
            taken_codes = set(_res)
        
        required_core_done = required_course_set.issubset(taken_codes)



        # 충족 여부 (기존 로직 유지)
        pass_credit   = (credit_sum >= req_need_credit)
        pass_conv     = (ex_conv   >= req_need_conv)
        pass_minimum  = all(mins[k] >= req_min[k] for k in req_min) if req else True
        pass_all      = pass_credit and pass_conv and pass_minimum and required_core_done  # ✅

        data.append(TCurStudentRow(
            student_id=sid,
            student_no=sno,
            name=sname,
            status=st,

            # 등록/종료 분리 값 채움
            joined_year=(int(jy) if jy is not None else None),
            joined_term=(jt or None),
            completed_year=(int(cy) if cy is not None else None),
            completed_term=(ct or None),

            requirement_code=rcode or "",

            course_total_credit=round(credit_sum, 2),
            extrac_converted_total=round(ex_conv, 2),
            extrac_count=int(ex_count),
            **mins,

            required_core_done=required_core_done,
            pass_credit=pass_credit,
            pass_converted=pass_conv,
            pass_minimum=pass_minimum,
            pass_all=pass_all,   # ← 유지
        ))

    # ── 필터/정렬/페이지 (기존 유지) ─────────────────────────────────────────────
    import json as _json
    rows = data
    if filter:
        try: filters = _json.loads(filter)
        except: filters = []
        def fmatch(obj, f):
            fld = f.get("field"); typ=(f.get("type") or "like").lower(); val=f.get("value")
            v = getattr(obj, fld, None); s = "" if v is None else str(v)
            if typ in ("like","contains"): return str(val or "").lower() in s.lower()
            if typ in ("=","eq"):  return s == str(val)
            if typ in ("!=","ne"): return s != str(val)
            if typ in (">=",">","<=","<"):
                try: a=float(s); b=float(val)
                except: return False
                return (a>=b) if typ==">=" else (a>b) if typ==">" else (a<=b) if typ=="<=" else (a<b)
            return True
        for f in filters:
            rows = [r for r in rows if fmatch(r,f)]

    if sorters:
        try: sorters_list = _json.loads(sorters)
        except: sorters_list = []
        for srt in reversed(sorters_list):
            fld = srt.get("field"); dr=(srt.get("dir") or "asc").lower()
            rows.sort(key=lambda r: getattr(r, fld, None), reverse=(dr=="desc"))

    size = max(1, int(size)); page = max(1, int(page))
    total = len(rows); last_page = max(1, (total + size - 1)//size)
    start = (page-1)*size; end = start+size

    # === 진행률 표시용 최소 요구치(프론트 렌더러에서 사용) ===
    requirements_payload = {
        "credit": req_need_credit,                 # 교과 최소 학점
        "extrac_converted": req_need_conv,         # 비교과 환산 최소점수
        "extrac_count": req_need_count,            # 비교과 총 참여 최소횟수(없으면 0)
        "categories": req_min,                     # 세부유형별 최소횟수
    }

    return JSONResponse({
        "last_page": last_page,
        "requirements": requirements_payload,  # ← 추가: 프론트에서 "획득/최소" 계산용
        "data": [r.model_dump() for r in rows[start:end]],
    })


# ── 매핑(교과): /api/tabulator/curriculum/{cur_id}/mappings/courses
class TCurMapCourseRow(BaseModel):
    course_code: str
    course_name: Optional[str]
    required_flag: Optional[str]
    initial: Optional[str]
    final: Optional[str]
    credit: Optional[int]
    offering_semester: Optional[str]

@app.post("/api/tabulator/curriculum/{cur_id}/mappings/courses", response_class=JSONResponse)
def tab_curriculum_mapped_courses(
    cur_id: int,
    request: Request,
    db: Session = Depends(get_session),
    page: int = Form(1), size: int = Form(100),
    sorters: Optional[str] = Form(None), filter: Optional[str] = Form(None),
):
    if not require_admin(request):
        return JSONResponse({"error":"not_authorized"}, status_code=401)

    CCM = models.CurriculumCourseMap
    C   = models.Course

    rows = db.exec(
        select(
            CCM.course_code, CCM.required_flag,
            CCM.initial_year, CCM.initial_semester,
            CCM.final_year, CCM.final_semester,
            C.course_name_ko, C.credit, C.offering_semester
        )
        .join(C, C.course_code == CCM.course_code, isouter=True)
        .where(CCM.curriculum_id == cur_id)
        .order_by(C.course_name_ko.asc().nullslast(), CCM.course_code.asc())
    ).all()

    data = [TCurMapCourseRow(
        course_code=code,
        course_name=(cname or code),
        required_flag=req,
        initial=(f"{iy or ''} {is_ or ''}".strip() if iy else ""),
        final=(f"{fy or ''} {fs or ''}".strip() if fy else ""),
        credit=credit,
        offering_semester=offsem
    ) for (code, req, iy, is_, fy, fs, cname, credit, offsem) in rows]

    # 간단 페이지 처리
    size=max(1,int(size)); page=max(1,int(page))
    total=len(data); last_page=max(1,(total+size-1)//size)
    s=(page-1)*size; e=s+size
    return JSONResponse({"last_page": last_page, "data": [d.model_dump() for d in data[s:e]]})

# ── 매핑(비교과): /api/tabulator/curriculum/{cur_id}/mappings/extracurricular
class TCurMapExtraRow(BaseModel):
    program_id: int
    program_name: Optional[str]
    category: Optional[str]
    recognized_credit_ratio: Optional[float]

@app.post("/api/tabulator/curriculum/{cur_id}/mappings/extracurricular", response_class=JSONResponse)
def tab_curriculum_mapped_extrac(
    cur_id: int,
    request: Request,
    db: Session = Depends(get_session),
    page: int = Form(1), size: int = Form(100),
):
    if not require_admin(request):
        return JSONResponse({"error":"not_authorized"}, status_code=401)

    CPM = getattr(models, "CurriculumProgramMap", None)
    P   = getattr(models, "Program", None)
    if CPM is None or P is None:
        return JSONResponse({"last_page": 1, "data": []})

    rows = db.exec(
        select(CPM.program_id, P.program_name, P.program_type, CPM.recognized_credit_ratio)
        .join(P, P.id == CPM.program_id)
        .where(CPM.curriculum_id == cur_id)
        .order_by(P.program_name.asc())
    ).all()

    data = [TCurMapExtraRow(
        program_id=int(pid),
        program_name=pname,
        category=ptype,
        recognized_credit_ratio=(float(ratio) if ratio is not None else None)
    ) for (pid, pname, ptype, ratio) in rows]

    size=max(1,int(size)); page=max(1,int(page))
    total=len(data); last_page=max(1,(total+size-1)//size)
    s=(page-1)*size; e=s+size
    return JSONResponse({"last_page": last_page, "data": [d.model_dump() for d in data[s:e]]})

# ── 이수조건: /api/tabulator/curriculum/{cur_id}/requirements
class TCurReqRow(BaseModel):
    requirement_code: str
    required_credit: float
    college_scope: str | None = None
    degree_scope: str | None = None
    total_converted_required: float
    total_internship_required: float
    min_ai_med_talks: int
    min_company_visit: int
    min_hospital_visit: int
    min_seminar: int
    min_exchange_forum: int
    min_expo: int
    min_academic_conf: int
    min_competition: int
    min_etc: int

@app.post("/api/tabulator/curriculum/{cur_id}/requirements", response_class=JSONResponse)
def tab_curriculum_requirements(
    cur_id: int,
    request: Request,
    db: Session = Depends(get_session),
    page: int = Form(1), size: int = Form(100),
):
    if not require_admin(request):
        return JSONResponse({"error":"not_authorized"}, status_code=401)

    PR = models.ProgramRequirement
    rows = db.exec(
        select(PR).where(PR.curriculum_id == cur_id).order_by(PR.id.desc())
    ).all()

    data = [TCurReqRow(
        requirement_code = r.requirement_code,
        required_credit  = _f0(r.required_credit),
        college_scope            = getattr(r, "college_scope", None),
        degree_scope             = getattr(r, "degree_scope", None),
        total_converted_required = _f0(r.total_converted_required),
        total_internship_required= _f0(r.total_internship_required),
        min_ai_med_talks   = _to0(r.min_ai_med_talks),
        min_company_visit  = _to0(r.min_company_visit),
        min_hospital_visit = _to0(r.min_hospital_visit),
        min_seminar        = _to0(r.min_seminar),
        min_exchange_forum = _to0(r.min_exchange_forum),
        min_expo           = _to0(r.min_expo),
        min_academic_conf  = _to0(r.min_academic_conf),
        min_competition    = _to0(r.min_competition),
        min_etc            = _to0(r.min_etc),
    ) for r in rows]

    size=max(1,int(size)); page=max(1,int(page))
    total=len(data); last_page=max(1,(total+size-1)//size)
    s=(page-1)*size; e=s+size
    return JSONResponse({"last_page": last_page, "data": [d.model_dump() for d in data[s:e]]})

def _iso_or_none(x):
    try:
        return x.isoformat() if x else None
    except Exception:
        return None
    
# === Requirements: by curriculum program (학생-교육과정 매핑용) ===
# @app.get("/api/requirements/by_program", name="get_requirements_by_program")
# def get_requirements_by_program(
#     curriculum_program_id: Optional[int] = Query(None),
#     program_id: Optional[int] = Query(None),   # 과거 호환(있어도 되고, 없으면 지워도 됨)
#     db: Session = Depends(get_session),
# ):
#     # 파라미터 정규화
#     program_fk = curriculum_program_id if curriculum_program_id not in ("", None) else program_id
#     if program_fk in ("", None):
#         raise HTTPException(400, "curriculum_program_id (또는 program_id)이 필요합니다.")

#     PR = models.ProgramRequirement

#     # ✅ 핵심: ProgramRequirement.curriculum_id 로 매칭
#     rows = db.exec(
#         select(PR)
#         .where(PR.curriculum_id == program_fk)
#         .order_by(PR.requirement_code.asc())
#     ).all()

#     def to_item(r):
#         # 모델에 없는 필드는 None으로, 있으면 그대로
#         required_credit = getattr(r, "required_credit", None)
#         requirement_code = getattr(r, "requirement_code", None)
#         requirement_name = getattr(r, "requirement_name", None)  # 현재 모델엔 없음 → None

#         # 호환 별칭: 프론트가 code/credit_min/name 을 참조하더라도 값이 채워지도록
#         return {
#             "id": r.id,
#             "requirement_code": requirement_code,
#             "requirement_name": requirement_name,       # 없으면 아래 name에서 보정
#             "required_credit": required_credit,
#             # ---- 별칭 (이전/다른 화면 호환용) ----
#             "code": requirement_code,                   # code → requirement_code
#             "name": requirement_name or requirement_code,  # name 없으면 code로 fallback
#             "credit_min": required_credit,              # credit_min → required_credit
#         }

#     items = [to_item(r) for r in rows]
#     # 응답 계약을 넉넉히: 일부 화면이 data/items 중 하나만 본다면 둘 다 제공
#     return {"count": len(items), "items": items, "data": items}

# === Requirements: by curriculum program (학생-교육과정 매핑용) ===
@app.get("/api/requirements/by_program", name="get_requirements_by_program")
def get_requirements_by_program(
    curriculum_program_id: Optional[str] = Query(None),
    program_id: Optional[str] = Query(None),   # 과거 호환
    db: Session = Depends(get_session),
):
    # 문자열 → 안전 정수 변환
    def to_int_or_none(v: Optional[str]) -> Optional[int]:
        if v is None: return None
        s = str(v).strip()
        if s in ("", "null", "undefined"): return None
        try: return int(s)
        except: return None

    program_fk = to_int_or_none(curriculum_program_id) or to_int_or_none(program_id)
    if program_fk is None:
        # 422 대신 400으로 명확히
        raise HTTPException(400, "curriculum_program_id(또는 program_id)이 필요합니다.")

    PR = models.ProgramRequirement
    rows = db.exec(
        select(PR)
        .where(PR.curriculum_id == program_fk)
        .order_by(PR.requirement_code.asc())
    ).all()

    def to_item(r):
        required_credit = getattr(r, "required_credit", None)
        requirement_code = getattr(r, "requirement_code", None)
        requirement_name = getattr(r, "requirement_name", None)
        return {
            "id": r.id,
            "requirement_code": requirement_code,
            "requirement_name": requirement_name,
            "required_credit": required_credit,
            "code": requirement_code,
            "name": requirement_name or requirement_code,
            "credit_min": required_credit,
        }

    items = [to_item(r) for r in rows]
    return {"count": len(items), "items": items, "data": items}

# ─────────────────────────────────────────────────────────────
# 학생 조회: 상세 모달 데이터(개요 + 4개 탭)
# 프런트 의존 경로:
#   - GET  /api/students/{sid}/overview
#   - GET  /api/student/{sid}/leaves
#   - GET  /api/student/{sid}/curricula
#   - GET  /api/student/{sid}/courses
#   - GET  /api/student/{sid}/programs
# ─────────────────────────────────────────────────────────────

@app.get("/api/students/{student_id}/overview", response_class=JSONResponse)
def api_student_overview(
    student_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return JSONResponse({"ok": False, "message": "not_authorized"}, status_code=401)

    S   = models.Student
    SCE = models.StudentCourseEnrollment
    SEn = models.StudentCurriculumEnrollment
    CP  = models.CurriculumProgram

    s = db.get(S, student_id)
    if not s:
        return JSONResponse({"ok": False, "message": "not found"}, status_code=404)

    taken_row = db.exec(
        select(func.count(SCE.id)).where(SCE.student_id == student_id)
    ).one()
    taken_count = int(taken_row[0] if isinstance(taken_row, tuple) else taken_row or 0)

    prog_rows = db.exec(
        select(CP.program_type, CP.course_name, CP.open_year)
        .join(SEn, SEn.curriculum_program_id == CP.id)
        .where(SEn.student_id == student_id)
        .order_by(CP.course_name.asc())
    ).all()
    programs = []
    for ptype, cname, oy in prog_rows:
        label = f"{ptype}-{cname}({oy})" if oy else f"{ptype}-{cname}"
        programs.append({
            "label": label,
            "program_type": ptype,
            "course_name": cname,
            "open_year": oy,
        })

    data = {
        "id": s.id,
        "student_no": getattr(s, "student_no", None),
        "name": getattr(s, "name", None),
        "degree": getattr(s, "degree", None),
        "college": getattr(s, "college", None),
        "department": getattr(s, "department", None),
        "major": getattr(s, "major", None),
        "admission_year": getattr(s, "admission_year", None),
        "admission_term": getattr(s, "admission_term", None),
        "academic_status": getattr(s, "academic_status", None),
        # ▼ 모달 개요에 필요한 필드들 추가
        "advisor_name": getattr(s, "advisor_name", None),
        "supervisor_name": getattr(s, "supervisor_name", None),
        "email_snu": getattr(s, "email_snu", None),
        "email_other": getattr(s, "email_other", None),
        "updated_at": (getattr(s, "updated_at", None).isoformat()
                       if getattr(s, "updated_at", None) else None),
        "taken_count": taken_count,
        "programs": programs,
    }
    return JSONResponse({"ok": True, "data": data})

@app.get("/api/student/{student_id}/overview", response_class=JSONResponse)
def api_student_overview_alias(student_id: int, request: Request, db: Session = Depends(get_session)):
    return api_student_overview(student_id, request, db)

@app.get("/api/student/{student_id}/leaves", response_class=JSONResponse)
def api_student_leaves(
    student_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return JSONResponse([], status_code=200)

    SLH = models.StudentLeaveHistory
    rows = db.exec(
        select(SLH.leave_year, SLH.leave_semester,
               getattr(SLH, "created_at", None), getattr(SLH, "updated_at", None))
        .where(SLH.student_id == student_id)
        .order_by(SLH.leave_year.desc(), SLH.leave_semester.desc())
    ).all()

    data = []
    for y, sem, created, updated in rows:
        data.append({
            "type": "휴학",                # UI의 '구분'
            "start_year": y,
            "start_term": sem,
            "end_year": y,                # 단일 학기 휴학 스키마라면 동일값 매핑
            "end_term": sem,
            "status": "recorded",
            "created_at": created.isoformat() if created else "",
            "updated_at": updated.isoformat() if updated else "",
        })
    return JSONResponse(data)


@app.get("/api/student/{student_id}/curricula", response_class=JSONResponse)
def api_student_curricula(
    student_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return JSONResponse([], status_code=200)

    SEn = models.StudentCurriculumEnrollment
    CP  = models.CurriculumProgram
    PR  = models.ProgramRequirement
    SCE = models.StudentCourseEnrollment
    C   = models.Course
    CCM = models.CurriculumCourseMap
    CPM = getattr(models, "CurriculumProgramMap", None)
    P   = getattr(models, "Program", None)
    PEN = getattr(models, "ProgramEnrollment", None)

    # 프로그램유형 → 카테고리 키
    EXACT_TYPE_TO_KEY = {
        "SNU AI.MED talks 시리즈": "min_ai_med_talks",
        "기업 견학":               "min_company_visit",
        "병원 견학":               "min_hospital_visit",
        "교육 및 세미나":           "min_seminar",
        "성과교류회":              "min_exchange_forum",
        "박람회":                 "min_expo",
        "학회":                   "min_academic_conf",
        "경진대회":                "min_competition",
        "기타":                   "min_etc",
    }
    def detect_key(t: str) -> str:
        return EXACT_TYPE_TO_KEY.get((t or "").strip(), "min_etc")

    # 학생의 모든 수강코드 미리 set화 (필수교과 충족판정용)
    taken_codes = {r[0] for r in db.exec(
        select(SCE.course_code).where(SCE.student_id == student_id)
    ).all()}

    # 기본 행(학생-교육과정 연결)
    base = db.exec(
        select(
            SEn.id.label("enroll_id"),
            CP.id.label("curriculum_id"),
            CP.program_type,
            CP.course_name.label("curriculum_name"),
            SEn.status,
            SEn.joined_year, SEn.joined_term,
            SEn.completed_year, SEn.completed_term,
            PR.requirement_code,
        )
        .join(CP, CP.id == SEn.curriculum_program_id)
        .join(PR, PR.id == SEn.requirement_id, isouter=True)
        .where(SEn.student_id == student_id)
        .order_by(CP.course_name.asc())
    ).all()

    out = []
    for (enroll_id, cur_id, ptype, cname, st, jy, jt, cy, ct, rcode) in base:
        # 이 커리큘럼의 필수교과 set
        req_course_set = {
            code for code, rflag in db.exec(
                select(CCM.course_code, CCM.required_flag)
                .where(CCM.curriculum_id == cur_id)
            ).all()
            if (rflag or "").strip() == "필수"
        }
        required_core_done = req_course_set.issubset(taken_codes) if req_course_set else True

        # 교과 학점 합계 (학생이 듣고, 커리큘럼에 매핑된 과목만)
        credit_sum_row = db.exec(
            select(func.coalesce(func.sum(C.credit), 0.0))
            .select_from(SCE)
            .join(C, C.course_code == SCE.course_code)
            .join(CCM, and_(CCM.course_code == SCE.course_code,
                            CCM.curriculum_id == cur_id))
            .where(SCE.student_id == student_id)
        ).one()
        course_total_credit = float(credit_sum_row[0] if isinstance(credit_sum_row, tuple) else credit_sum_row or 0.0)

        # 비교과 환산/카운트/카테고리 집계 (커리큘럼에 매핑된 프로그램만 집계)
        extrac_converted_total = 0.0
        extrac_count = 0
        mins = {
            "min_ai_med_talks":0, "min_company_visit":0, "min_hospital_visit":0,
            "min_seminar":0, "min_exchange_forum":0, "min_expo":0,
            "min_academic_conf":0, "min_competition":0, "min_etc":0
        }
        if CPM is not None and P is not None and PEN is not None:
            # 커리큘럼에 연결된 program_id -> ratio 맵
            ratio_map = {
                int(pid): float(ratio) if ratio is not None else 0.0
                for pid, ratio in db.exec(
                    select(CPM.program_id, CPM.recognized_credit_ratio)
                    .where(CPM.curriculum_id == cur_id)
                ).all()
            }
            if ratio_map:
                rows = db.exec(
                    select(PEN.program_id, P.program_type)
                    .join(P, P.id == PEN.program_id)
                    .where(PEN.student_id == student_id)
                    .where(PEN.program_id.in_(ratio_map.keys()))
                ).all()
                extrac_count = len(rows)
                for pid, ptype_ in rows:
                    extrac_converted_total += ratio_map.get(int(pid), 0.0)
                    mins[detect_key(ptype_)] += 1

        out.append({
            "curriculum_id": cur_id,
            "program_type": ptype,
            "curriculum_name": cname,
            "status": st,
            "joined_year": int(jy) if jy is not None else None,
            "joined_term": jt or None,
            "completed_year": int(cy) if cy is not None else None,
            "completed_term": ct or None,
            "requirement_code": rcode or "",
            # got(학생 달성치)
            "course_total_credit": round(course_total_credit, 2),
            "extrac_converted_total": round(extrac_converted_total, 2),
            "extrac_count": int(extrac_count),
            **mins,  # 9개 카테고리 got
            "required_core_done": bool(required_core_done),
            # pass_* / pass_all 은 프론트가 need를 채운 뒤 계산하도록 유지
        })
    return JSONResponse(out)


@app.get("/api/student/{student_id}/courses", response_class=JSONResponse)
def api_student_courses(
    student_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return JSONResponse([], status_code=200)

    SCE = models.StudentCourseEnrollment
    C   = models.Course

    # year/semester 컬럼이 없을 수도 있어 isouter 조인 + 컬럼 존재 여부 체크
    cols = [
        SCE.course_code,
        C.course_name_ko,
        C.credit,
        C.offering_semester,
    ]
    # enrollment에 연/학기 필드가 있다면 함께 내준다.
    has_year = hasattr(SCE, "year")
    has_sem  = hasattr(SCE, "semester")
    if has_year:
        cols.append(SCE.year)
    if has_sem:
        cols.append(SCE.semester)

    rows = db.exec(
        select(*cols)
        .join(C, C.course_code == SCE.course_code, isouter=True)
        .where(SCE.student_id == student_id)
        .order_by(C.course_name_ko.asc().nullslast(), SCE.course_code.asc())
    ).all()

    data = []
    for row in rows:
        i = 0
        code = row[i]; i += 1
        cname = row[i]; i += 1
        credit = row[i]; i += 1
        offsem = row[i]; i += 1
        year = row[i] if has_year else None;  i += 1 if has_year else 0
        sem  = row[i] if has_sem  else None

        data.append({
            "course_code": code,
            "course_name": cname or code,
            "credit": credit,
            "offering_semester": offsem,
            "year": year,
            "semester": sem,
        })
    return JSONResponse(data)

@app.get("/api/student/{student_id}/programs", response_class=JSONResponse)
def api_student_programs(
    student_id: int,
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return JSONResponse([], status_code=200)

    P   = getattr(models, "Program", None)
    PEN = getattr(models, "ProgramEnrollment", None)
    if P is None or PEN is None:
        return JSONResponse([], status_code=200)

    rows = db.exec(
        select(
            P.program_name,
            P.program_type,
            P.sub_program_name,   # ✅ 세부명
            P.organizer,          # ✅ 주관/주최
            P.open_year,          # ✅ 연도
            P.open_month,         # ✅ 월
            PEN.recognized_credit,
            PEN.enroll_source,
            PEN.exception_case,
        )
        .join(P, P.id == PEN.program_id)
        .where(PEN.student_id == student_id)
        .order_by(P.open_year.desc().nullslast(),
                  P.open_month.desc().nullslast(),
                  P.program_name.asc())
    ).all()

    def _open(y, m):
        if not y: return ""
        return f"{int(y)}/{int(m):02d}" if m else str(y)

    data = []
    for pname, ptype, subname, org, oy, om, rc, src, ex in rows:
        data.append({
            "program_name": pname,
            "program_type": ptype,
            "sub_program_name": subname or "",   # ✅ 세부명
            "organizer": org or "",              # ✅ 주관/주최
            "open_year": int(oy) if oy is not None else None,   # ✅ 연도
            "open_month": int(om) if om is not None else None,  # ✅ 월
            "open": _open(oy, om),               # (문자열 표현은 유지)
            "recognized_credit": (float(rc) if rc is not None else None),
            "enroll_source": src or "",
            "exception_case": bool(ex),
        })
    return JSONResponse(data)

