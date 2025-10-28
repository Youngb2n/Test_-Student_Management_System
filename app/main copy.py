from datetime import datetime, date, timezone
from typing import List, Optional
import bcrypt
from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from starlette.templating import Jinja2Templates
from app.database import get_session
from app import models


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

# ---------- helpers ----------

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

            # 어떤 value_* 필드를 써야 할지 결정
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
    'YYYY-MM-DD' 입력받아서 date로 변환.
    1900~2100년 사이만 허용.
    잘못된 값이면 None.
    """
    try:
        y_s, m_s, d_s = raw.split("-")
        y, m, d = int(y_s), int(m_s), int(d_s)
        if y < 1900 or y > 2100:
            return None
        return date(y, m, d)
    except Exception:
        return None


# ---------- routes ----------

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
    # ── admin login
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

        # bcrypt check
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
        resp = RedirectResponse(url="/admin", status_code=302)
        return resp

    # ── student login (단순 이름+학번 매칭)
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
        resp = RedirectResponse(url="/student", status_code=302)
        return resp

    # role 이상한 경우
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


@app.get("/admin/register/student", response_class=HTMLResponse)
def admin_register_student(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    option_map = build_option_map(db)
    current_year = datetime.now().year

    return templates.TemplateResponse(
        "admin_register_student.html",
        {
            "request": request,
            "active": "register",
            "option_map": option_map,
            "current_year": current_year,
        },
    )

# ─────────────────────────────────────────────
# 사업단 주관사업 등록 페이지
# ─────────────────────────────────────────────
@app.get("/admin/register/business", response_class=HTMLResponse)
def admin_register_business_initiative(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    current_year = datetime.now().year

    return templates.TemplateResponse(
        "admin_register_business_initiative.html",
        {
            "request": request,
            "active": "register",            # 사이드바 '등록' 섹션 열림 유지
            "current_year": current_year,
        },
    )


# ─────────────────────────────────────────────
# 교육과정 등록 페이지
#   - option_map: seed_options 기반 select 값들
#   - initiatives: BusinessInitiative 목록 (소속 사업단 선택)
#   - 교육과정 이수조건 등록
# ─────────────────────────────────────────────
@app.get("/admin/register/curriculum", response_class=HTMLResponse)
def admin_register_curriculum_program(
    request: Request,
    db: Session = Depends(get_session),
):
    # ───── 관리자 인증 확인 ─────
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    # ───── Select 옵션 빌드 (seed_options.py 기반) ─────
    option_map = build_option_map(db)  # 예: degree, college, semester_simple 등
    current_year = datetime.now().year

    # ───── 사업단 주관사업 목록 (BusinessInitiative DB에서 로드) ─────
    initiatives = db.exec(
        select(models.BusinessInitiative)
        .order_by(models.BusinessInitiative.project_name.asc())
    ).all()

    return templates.TemplateResponse(
        "admin_register_curriculum_program.html",
        {
            "request": request,
            "active": "register",       # 사이드바 활성화
            "option_map": option_map,   # select 값 세트
            "initiatives": initiatives, # 사업단 목록 (드롭다운에 표시)
            "current_year": current_year,  # 커스텀드롭다운용 기본연도
        },
    )


# ─────────────────────────────────────────────
# 교과목 등록 페이지
#   - option_map: 학기 옵션 등에서 재사용 가능
#   - curricula: CurriculumProgram 리스트 (교육과정 매핑 select)
# ─────────────────────────────────────────────
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
        select(models.CurriculumProgram).order_by(models.CurriculumProgram.course_name.asc())
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


# ─────────────────────────────────────────────
# 비교과 프로그램 등록 페이지
#   - curricula: CurriculumProgram 리스트
#     (매핑/환산점수 입력할 때 교육과정 셀렉트용)
# ─────────────────────────────────────────────
@app.get("/admin/register/extracurricular", response_class=HTMLResponse)
def admin_register_extracurricular_program(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    current_year = datetime.now().year

    curricula = db.exec(
        select(models.CurriculumProgram).order_by(models.CurriculumProgram.program_type.asc())
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

# ─────────────────────────────────────────────
# 학생 등록 (POST)
# ─────────────────────────────────────────────
@app.post("/admin/register/student")
async def admin_register_student_post(
    request: Request,
    db: Session = Depends(get_session),

    # ----- 기본 정보 -----
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

    # ----- 이메일 -----
    email_snu_local: str = Form(...),
    email_other_local: str = Form(...),
    email_other_domain: str = Form(...),     # select 값 (혹은 "__OTHER__")
    email_other_custom: str = Form(""),      # 직접입력 도메인

    # ----- 재학 정보 -----
    degree: str = Form(...),
    college: str = Form(...),
    collaborative_program: str = Form(""),
    department: str = Form(...),
    major: str = Form(...),
    admission_type: str = Form(...),
    admission_year: int = Form(...),
    admission_term: str = Form(...),
    academic_status: str = Form(...),
    leave_of_absence: str = Form("N"),

    advisor_name: str = Form(...),
    supervisor_name: str = Form(""),

    # 재직자 전형 관련
    workplace: str = Form(""),
    health_insurance_certificate: str = Form(""),

    # ----- 입학 전 최종학력 (모두 nullable=False in DB) -----
    previous_degree: str = Form(...),
    previous_major: str = Form(...),
    previous_degree_year: int = Form(...),
    previous_institution: str = Form(...),

    # ----- 휴학 이력 여러개 -----
    leave_year: List[int] = Form([]),
    leave_semester: List[str] = Form([]),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    # 1. 생년월일 검증 (프론트에서도 막았지만 서버에서도 한 번 더 막자)
    birthdate_parsed = parse_birthdate_safe(birthdate)
    if birthdate_parsed is None:
        return JSONResponse(
            {"error": "잘못된 생년월일 형식입니다. (1900~2100년만 허용, YYYY-MM-DD)"},
            status_code=400,
        )

    # 2. 이메일 조립
    email_snu_full = f"{email_snu_local}@snu.ac.kr".strip()
    if email_other_domain == "__OTHER__":
        domain_final = email_other_custom.strip()
    else:
        domain_final = email_other_domain.strip()
    email_other_full = f"{email_other_local}@{domain_final}".strip()

    # 3. 국적 최종값
    nat_final = nationality_custom.strip() if nationality == "__OTHER__" else nationality

    # 4. 재직자 전형 관련 필드 정리
    is_employed_type = ("재직" in admission_type)
    workplace_final = workplace.strip() if (is_employed_type and workplace.strip()) else None
    health_cert_final = (
        health_insurance_certificate.strip()
        if (is_employed_type and health_insurance_certificate.strip())
        else None
    )

    # 5. Student INSERT (commit 전에 flush 해서 stu.id 확보 → LeaveHistory FK로 씀)
    stu = models.Student(
        student_no=student_no,
        name=name,
        name_en=name_en,
        birthdate=birthdate_parsed,
        researcher_id=researcher_id,

        nationality=nat_final,
        foreigner_reg_no=foreigner_reg_no or None,

        mobile_phone_num=mobile_phone_num,
        phone_num=phone_num or None,

        email_snu=email_snu_full,
        email_other=email_other_full,

        degree=degree,
        college=college,
        collaborative_program=collaborative_program or None,
        department=department,
        major=major,

        admission_type=admission_type,
        admission_year=admission_year,
        admission_term=admission_term,

        academic_status=academic_status,
        leave_of_absence=leave_of_absence,

        advisor_name=advisor_name,
        supervisor_name=supervisor_name or None,

        workplace=workplace_final,
        health_insurance_certificate=health_cert_final,

        # 입학 전 최종학력 (NOT NULL)
        previous_degree=previous_degree,
        previous_major=previous_major,
        previous_degree_year=previous_degree_year,
        previous_institution=previous_institution,

        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    db.add(stu)
    db.flush()  # 여기서 stu.id 확보됨 (아직 commit 전)

    # 6. 휴학 이력 INSERT (여러 건 지원)
    # leave_of_absence 값이 휴학 계열일 때만 insert
    if leave_of_absence and leave_of_absence.upper() =="Y":
        for y, sem in zip(leave_year, leave_semester):
            if not y or not sem:
                continue
            leave_row = models.StudentLeaveHistory(
                student_id=stu.id,
                leave_year=int(y),
                leave_semester=sem,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(leave_row)

    # 7. 최종 commit (Student + LeaveHistory 같이 저장)
    db.commit()

    # 8. 성공 후 다시 등록 페이지(빈 폼)로 리다이렉트
    return RedirectResponse(
        url="/admin/register/student?success=1",
        status_code=302,
    )


# ─────────────────────────────────────────────
# 사업단 주관사업 등록 (POST)
# ─────────────────────────────────────────────
@app.post("/admin/register/business")
async def admin_register_business_post(
    request: Request,
    db: Session = Depends(get_session),

    # --- 기본 정보 ---
    project_name: str = Form(...),
    support_agency: str = Form(""),
    specialized_institute: str = Form(""),
    research_task_name: str = Form(""),

    # --- 일정 ---
    start_date: str = Form(...),
    end_date: str = Form(...),

    # --- KPI ---
    beneficiary_target: Optional[float] = Form(None),
    output_target: Optional[float] = Form(None),
    career_linked_target: Optional[float] = Form(None),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    # 날짜 검증
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

    # INSERT
    biz = models.BusinessInitiative(
        project_name=project_name.strip(),
        support_agency=support_agency.strip() or None,
        specialized_institute=specialized_institute.strip() or None,
        research_task_name=research_task_name.strip() or None,

        start_date=start_date_parsed,
        end_date=end_date_parsed,

        beneficiary_target=beneficiary_target,
        output_target=output_target,
        career_linked_target=career_linked_target,

        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    db.add(biz)
    db.commit()

    # 완료 후 등록 페이지로 리다이렉트
    return RedirectResponse(
        url="/admin/register/business?success=1",
        status_code=302,
    )


def _college_code_from_scope(scope: str) -> str:
    """
    ProgramRequirement.requirement_code 생성용.
    의대 계열이면 'M', 아니면 'E' 등으로 매핑.
    """
    scope = (scope or "").strip()
    if scope.startswith("의과대"):  # "의과대학", "의과대학(의학과)" 등
        return "M"
    # 나머지(그 외 등)
    return "E"


def _degree_code_from_scope(scope: str) -> str:
    """
    학위 구분을 코드화.
    학부=B, 석사=M, 박사=D, 대학원생=C, 통합=C (일단 C로 처리)
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
    # fallback
    return "C"


def _next_requirement_seq_for_year(db: Session, year_prefix: str) -> int:
    """
    year_prefix: '2025' 처럼 4자리 연도 문자열.
    DB에 이미 있는 requirement_code 중 해당 연도로 시작하는 것들 찾아,
    맨 뒤 4자리 seq 중 최댓값 + 1을 반환.
    없으면 1부터 시작.
    """
    # requirement_code 형식 가정: YYYY + seq(4) + codes(2)
    # 예: 20250001MC
    # substr 5~8이 seq. DB마다 substr 다르지만 sqlmodel+like 로 간단히 처리:
    existing = db.exec(
        select(models.ProgramRequirement.requirement_code)
        .where(models.ProgramRequirement.requirement_code.like(f"{year_prefix}%"))
    ).all()

    max_seq = 0
    for code in existing:
        if not code or len(code) < 10:
            continue
        # code[4:8] 가 seq('0001' 등)이라고 가정
        seq_part = code[4:8]
        try:
            num = int(seq_part)
            if num > max_seq:
                max_seq = num
        except ValueError:
            pass

    return max_seq + 1


def _generate_requirement_code(db: Session,
                               college_scope: str,
                               degree_scope: str,
                               year: int) -> str:
    """
    예: 2025 + 0001 + M + C  -> '20250001MC'
    year: int (예: 2025) 보통 현재 연도 사용
    """
    year_str = str(year)
    seq_int = _next_requirement_seq_for_year(db, year_str)
    seq_str = f"{seq_int:04d}"

    college_code = _college_code_from_scope(college_scope)
    degree_code  = _degree_code_from_scope(degree_scope)

    return f"{year_str}{seq_str}{college_code}{degree_code}"


# ─────────────────────────────────────────────
# 교육과정 등록 (POST)
#   - CurriculumProgram + ProgramRequirement[*]
#   - requirement_code는 자동 생성 (프론트에서 안 받음)
# ─────────────────────────────────────────────
@app.post("/admin/register/curriculum")
async def admin_register_curriculum_post(
    request: Request,
    db: Session = Depends(get_session),

    # ----- CurriculumProgram 기본 정보 -----
    program_type: str = Form(...),          # 프로그램 유형 (인증제/교과인증과정/교과과정)
    course_name: str = Form(...),           # 과정명
    degree_type: str = Form(...),           # 학위 구분 (학부/대학원/통합 등)
    department_type: str = Form(...),       # 학과 구분 (의과대학/공과대학/.../통합)

    open_year: Optional[int] = Form(None),  # 개설연도 (없으면 None 허용)
    open_semester: str = Form(""),          # 개설학기
    close_year: Optional[int] = Form(None), # 폐지연도 (없으면 None)
    close_semester: str = Form(""),         # 폐지학기

    business_initiative_id: Optional[int] = Form(None),  # 소속 사업단 (nullable)

    # ----- ProgramRequirement 다건 입력 -----
    # 각 requirement-card에서 동일 name으로 반복해서 submit됨
    college_scope: List[str] = Form([]),         # 적용 대학
    degree_scope: List[str] = Form([]),          # 적용 학위
    required_credit: List[float] = Form([]),     # 교과 학점 요구량
    total_converted_required: List[float] = Form([]),    # 비교과 환산점수 요구치
    total_internship_required: List[float] = Form([]),   # 인턴십 환산점수 요구치

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
    # 0. 관리자 확인
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    now_utc = datetime.utcnow()
    this_year = datetime.now().year  # requirement_code 앞 4자리용

    # 1. CurriculumProgram INSERT
    curriculum_row = models.CurriculumProgram(
        # FK: nullable True
        business_initiative_id=business_initiative_id if business_initiative_id else None,

        program_type=program_type.strip(),
        course_name=course_name.strip(),
        degree_type=degree_type.strip(),
        department_type=department_type.strip(),

        open_year=open_year if open_year else None,
        open_semester=open_semester or "",
        close_year=close_year if close_year else None,
        close_semester=close_semester or "",

        created_at=now_utc,
        updated_at=now_utc,
    )

    db.add(curriculum_row)
    db.flush()  # curriculum_row.id 확보

    # 2. ProgramRequirement 여러 건 생성
    #    여기서 requirement_code 자동 생성
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

        # requirement_code 규칙에 맞게 생성
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

    # 3. commit
    db.commit()

    # 4. 성공 후 등록 페이지로 redirect (?success=1 붙여서 alert 띄우는 기존 패턴 유지)
    return RedirectResponse(
        url="/admin/register/curriculum?success=1",
        status_code=302,
    )


# ─────────────────────────────────────────────
# 교과목 등록 (POST)
#   - Course + CurriculumCourseMap[*]
# ─────────────────────────────────────────────
@app.post("/admin/register/course")
async def admin_register_course_post(
    request: Request,
    db: Session = Depends(get_session),

    # -------------------------
    # 1) Course 기본 정보
    # -------------------------
    course_code: str = Form(...),
    course_name_ko: str = Form(...),
    course_name_en: Optional[str] = Form(None),

    degree_level: str = Form(...),       # "학사","대학원" 등
    grade_level: int = Form(...),        # 0~6
    offering_semester: str = Form(...),  # "1학기","2학기"
    offering_cycle: str = Form(...),     # "1년","2년","기타"

    grading_scheme: str = Form(...),     # "A~F","S/U" 등
    credit: int = Form(...),
    lecture_hours: int = Form(...),
    lab_hours: int = Form(...),

    department_name: str = Form(...),
    instructor_name: str = Form(...),
    capacity: Optional[int] = Form(None),
    enrollment: Optional[int] = Form(None),

    # -------------------------
    # 2) 교육과정 매핑 카드들 (여러 개)
    # -------------------------
    curriculum_id: List[Optional[str]] = Form([]),
    required_flag: List[str] = Form([]),

    initial_year: List[int] = Form([]),
    initial_semester: List[str] = Form([]),

    final_year: Optional[List[Optional[int]]] = Form(None),
    final_semester: Optional[List[Optional[str]]] = Form(None),
):
    """
    교과목(Course) 1건 + CurriculumCourseMap 여러건.

    규칙 요약:
    - course_code 이미 있으면 DB insert 안 하고 바로 redirect(error=duplicate_code)
    - 최종 인정 연도/학기: 연도 비어있으면 둘 다 None 으로 저장
    - curriculum_id 가 '미해당' (빈문자열 등) 이면 그 매핑 row는 아예 insert 안함
    """

    # ── 관리자 인증
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    # ── 1) course_code 중복 여부 확인
    exists = db.exec(
        select(models.Course).where(models.Course.course_code == course_code)
    ).first()
    if exists:
        # 이미 있는 코드라면 insert 안 하고 에러 쿼리 달아서 다시 form으로
        redirect_url = (
            "/admin/register/course"
            "?error=duplicate_code"
            f"&code={course_code}"
        )
        return RedirectResponse(url=redirect_url, status_code=303)

    # ── 2) Course row 생성
    now = datetime.now(timezone.utc)

    new_course = models.Course(
        course_code=course_code.strip(),
        course_name_ko=course_name_ko.strip(),
        course_name_en=course_name_en.strip() if course_name_en else None,

        degree_level=degree_level.strip(),
        grade_level=int(grade_level),
        offering_semester=offering_semester.strip(),
        offering_cycle=offering_cycle.strip(),

        grading_scheme=grading_scheme.strip(),
        credit=int(credit),
        lecture_hours=int(lecture_hours),
        lab_hours=int(lab_hours),

        department_name=department_name.strip(),
        instructor_name=instructor_name.strip(),
        capacity=capacity if capacity is not None else None,
        enrollment=enrollment if enrollment is not None else None,

        created_at=now,
        updated_at=now,
    )
    db.add(new_course)
    db.flush()  # course_code(PK) 확보

    # ── 3) CurriculumCourseMap rows
    def safe_get(lst, idx, default=None):
        if lst is None:
            return default
        if idx >= len(lst):
            return default
        return lst[idx]

    row_count = max(
        len(curriculum_id),
        len(required_flag),
        len(initial_year),
        len(initial_semester),
    )

    for i in range(row_count):
        raw_cur_id = curriculum_id[i] if i < len(curriculum_id) else None

        # curriculum_id 파싱
        #   - "" 또는 None → "미해당" 취급 → 이 row는 skip
        #   - 숫자로 변환 가능하면 int로 사용
        #   - 숫자 변환 불가능(예: "INTERN","ETC") → skip
        if raw_cur_id is None or raw_cur_id == "":
            # 미해당 → 이 매핑은 DB에 저장하지 않음
            continue
        try:
            cur_id_db = int(raw_cur_id)
        except (TypeError, ValueError):
            # 숫자 아님 → 이것도 미해당 취급 → skip
            continue

        # 필수 여부
        req_flag_val = (
            required_flag[i].strip()
            if i < len(required_flag) and required_flag[i]
            else "선택"
        )

        # 최초 인정
        init_year_val = (
            int(initial_year[i]) if i < len(initial_year) else None
        )
        init_sem_val = (
            initial_semester[i].strip()
            if i < len(initial_semester) and initial_semester[i]
            else ""
        )

        # 최종 인정 (optional)
        fin_year_val = safe_get(final_year, i, None)
        fin_sem_val = safe_get(final_semester, i, None)

        # 연도 입력 안 한 경우 → 둘 다 None
        if fin_year_val in (None, "", "null"):
            fin_year_val = None
            fin_sem_val = None
        else:
            try:
                fin_year_val = int(fin_year_val)
            except (TypeError, ValueError):
                fin_year_val = None
                fin_sem_val = None
            if fin_sem_val == "":
                fin_sem_val = None

        new_map = models.CurriculumCourseMap(
            curriculum_id=cur_id_db,                     # FK (유효한 int만)
            course_code=new_course.course_code,          # FK
            required_flag=req_flag_val,

            initial_year=init_year_val,
            initial_semester=init_sem_val,

            final_year=fin_year_val,
            final_semester=fin_sem_val,
        )
        db.add(new_map)

    # ── 4) commit
    db.commit()

    # ── 5) 성공 redirect (alert용 쿼리)
    redirect_url = (
        "/admin/register/course"
        "?success=1"
        f"&course_name={course_name_ko}"
    )
    return RedirectResponse(url=redirect_url, status_code=303)


@app.post("/admin/register/extracurricular")
async def admin_register_extracurricular_post(
    request: Request,
    db: Session = Depends(get_session),

    # ───────── 프로그램 본문 정보 ─────────
    program_name: str = Form(...),
    program_type: str = Form(...),

    open_year: int = Form(...),   # 커스텀 드롭다운에서 hidden input으로 year 넣어줌
    open_month: int = Form(...),  # 커스텀 드롭다운에서 hidden input으로 month 넣어줌

    description: Optional[str] = Form(None),

    # ───────── 교육과정 매핑 (반복행) ─────────
    curriculum_id: List[str] = Form([]),
    recognized_credit_ratio: List[str] = Form([]),
):
    """
    ExtracurricularProgram 1건 + 매핑 여러건을 함께 저장.

    규칙:
    - curriculum_id가 "" (미해당) 이면 그 row는 insert 안 함.
    - curriculum_id를 int로 변환 못 하면 그 row도 skip.
    - recognized_credit_ratio 비어 있으면 None 으로 저장.
    """

    # 관리자 체크
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    now = datetime.now(timezone.utc)

    # 1) ExtracurricularProgram INSERT
    prog = models.ExtracurricularProgram(
        program_name=program_name.strip(),
        program_type=program_type.strip(),
        open_year=int(open_year),
        open_month=int(open_month),
        description=description.strip() if description else None,
        created_at=now,
        updated_at=now,
    )
    db.add(prog)
    db.flush()  # prog.id 확보

    # 2) 매핑 행들 저장
    # curriculum_id / recognized_credit_ratio 는 같은 index로 묶인다고 가정
    row_count = max(len(curriculum_id), len(recognized_credit_ratio))

    for i in range(row_count):
        raw_cur = curriculum_id[i] if i < len(curriculum_id) else ""
        raw_ratio = recognized_credit_ratio[i] if i < len(recognized_credit_ratio) else ""

        # 2-1. 교육과정이 "(미해당)"이면 skip
        if raw_cur is None or raw_cur.strip() == "":
            continue

        # 2-2. curriculum_id 는 실제 CurriculumProgram.id (정수)여야 함
        try:
            cur_id_int = int(raw_cur)
        except (TypeError, ValueError):
            # 숫자 아님 (이상한 값 들어왔거나 미래에 "기타" 같은 특수타입 넣으려 한 경우)
            # 이 매핑은 그냥 안 넣는다.
            continue

        # 2-3. 환산 점수/가중치 파싱
        if raw_ratio is None or raw_ratio.strip() == "":
            ratio_val = None
        else:
            try:
                ratio_val = float(raw_ratio)
            except ValueError:
                # 숫자 변환 실패하면 None 처리 (또는 continue 해도 되는데 None으로 둘게)
                ratio_val = None

        progmap = models.ExtracurricularProgramMap(
            program_id=prog.id,
            curriculum_id=cur_id_int,
            recognized_credit_ratio=ratio_val,
            created_at=now,
            updated_at=now,
        )
        db.add(progmap)

    # 3) commit
    db.commit()

    # 4) 성공 후 다시 등록 페이지로
    # → /admin/register/extracurricular?success=1&program_name=...
    redirect_url = (
        "/admin/register/extracurricular"
        "?success=1"
        f"&program_name={program_name}"
    )
    return RedirectResponse(url=redirect_url, status_code=303)



@app.get("/admin/view/students", response_class=HTMLResponse)
def admin_view_students(request: Request, db: Session = Depends(get_session)):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    students = db.exec(
        select(models.Student).order_by(models.Student.updated_at.desc())
    ).all()

    return templates.TemplateResponse(
        "admin_view_students.html",
        {
            "request": request,
            "active": "view",
            "students": students,
        },
    )


# ─────────────────────────────────────────────
# 학생 조회 (이미 잘 작동하니까 그대로 두면 됨)
# GET /admin/view/students 렌더: admin_view_students.html
# ─────────────────────────────────────────────
@app.get("/admin/view/students", response_class=HTMLResponse)
def admin_view_students(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    students = db.exec(
        select(models.Student).order_by(models.Student.updated_at.desc())
    ).all()

    return templates.TemplateResponse(
        "admin_view_students.html",
        {
            "request": request,
            "active": "view",
            "students": students,
        },
    )

# ─────────────────────────────────────────────
# 주관사업 조회
# GET /admin/view/business -> admin_view_business.html
# ─────────────────────────────────────────────
@app.get("/admin/view/business", response_class=HTMLResponse)
def admin_view_business(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    initiatives = db.exec(
        select(models.BusinessInitiative)
        .order_by(models.BusinessInitiative.updated_at.desc())
    ).all()

    return templates.TemplateResponse(
        "admin_view_business.html",
        {
            "request": request,
            "active": "view",
            "initiatives": initiatives,
        },
    )


# ─────────────────────────────────────────────
# 교육과정 조회
# GET /admin/view/curriculum -> admin_view_curriculum.html
#   curricula: CurriculumProgram
#   req_map : { curriculum_id: [ProgramRequirement, ...] }
# ─────────────────────────────────────────────
@app.get("/admin/view/curriculum", response_class=HTMLResponse)
def admin_view_curriculum(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    curricula = db.exec(
        select(models.CurriculumProgram)
        .order_by(models.CurriculumProgram.updated_at.desc())
    ).all()

    # 각 교육과정별 requirement 모아서 dict로
    req_map: dict[int, list[models.ProgramRequirement]] = {}
    if curricula:
        cur_ids = [c.id for c in curricula]
        all_reqs = db.exec(
            select(models.ProgramRequirement)
            .where(models.ProgramRequirement.curriculum_id.in_(cur_ids))
            .order_by(models.ProgramRequirement.id.asc())
        ).all()
        for r in all_reqs:
            req_map.setdefault(r.curriculum_id, []).append(r)

    return templates.TemplateResponse(
        "admin_view_curriculum.html",
        {
            "request": request,
            "active": "view",
            "curricula": curricula,
            "req_map": req_map,
        },
    )


# ─────────────────────────────────────────────
# 교과목 조회
# GET /admin/view/course -> admin_view_course.html
#   courses: Course
#   mapping_map: { course_code: [CurriculumCourseMap,...] }
#   curriculum_name_by_id: { curriculum_id: 과정명 }
# ─────────────────────────────────────────────
@app.get("/admin/view/course", response_class=HTMLResponse)
def admin_view_course(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    courses = db.exec(
        select(models.Course).order_by(models.Course.updated_at.desc())
    ).all()

    # 해당 교과목들의 매핑 모두 조회
    course_codes = [c.course_code for c in courses]
    mapping_map: dict[str, list[models.CurriculumCourseMap]] = {}
    if course_codes:
        all_maps = db.exec(
            select(models.CurriculumCourseMap)
            .where(models.CurriculumCourseMap.course_code.in_(course_codes))
            .order_by(models.CurriculumCourseMap.initial_year.asc())
        ).all()
        for m in all_maps:
            mapping_map.setdefault(m.course_code, []).append(m)

    # 교육과정 이름 lookup 테이블
    curricula_all = db.exec(select(models.CurriculumProgram)).all()
    curriculum_name_by_id = {
        cur.id: cur.course_name for cur in curricula_all
    }

    return templates.TemplateResponse(
        "admin_view_course.html",
        {
            "request": request,
            "active": "view",
            "courses": courses,
            "mapping_map": mapping_map,
            "curriculum_name_by_id": curriculum_name_by_id,
        },
    )


# ─────────────────────────────────────────────
# 비교과 프로그램 조회
# GET /admin/view/extracurricular -> admin_view_extracurricular.html
#
#   programs: ExtracurricularProgram
#   prog_map: { program_id: [ExtracurricularCurriculumMap,...] }
#   curriculum_name_by_id: { curriculum_id: 과정명 }
#
# !!! 여기서 models.ExtracurricularCurriculumMap 이름은
#     네 실제 모델 이름(비교과↔교육과정 매핑 테이블)로 맞춰야 함.
# ─────────────────────────────────────────────
@app.get("/admin/view/extracurricular", response_class=HTMLResponse)
def admin_view_extracurricular(
    request: Request,
    db: Session = Depends(get_session),
):
    if not require_admin(request):
        return RedirectResponse(url="/login", status_code=302)

    programs = db.exec(
        select(models.ExtracurricularProgram)
        .order_by(models.ExtracurricularProgram.updated_at.desc())
    ).all()

    prog_map: dict[int, list] = {}

    if programs:
        prog_ids = [p.id for p in programs]

        # ←← 여기를 네 모델명에 맞게 바꿔.
        # 예: models.ExtracurricularCurriculumMap 라는 모델이 있고
        #     필드가 program_id, curriculum_id, recognized_credit_ratio 라고 가정할게.
        all_maps = db.exec(
            select(models.ExtracurricularCurriculumMap)
            .where(models.ExtracurricularCurriculumMap.program_id.in_(prog_ids))
            .order_by(models.ExtracurricularCurriculumMap.id.asc())
        ).all()

        for m in all_maps:
            prog_map.setdefault(m.program_id, []).append(m)

    # 교육과정 이름 lookup
    curricula_all = db.exec(select(models.CurriculumProgram)).all()
    curriculum_name_by_id = {
        cur.id: cur.course_name for cur in curricula_all
    }

    return templates.TemplateResponse(
        "admin_view_extracurricular.html",
        {
            "request": request,
            "active": "view",
            "programs": programs,
            "prog_map": prog_map,
            "curriculum_name_by_id": curriculum_name_by_id,
        },
    )
