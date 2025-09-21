import os
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import select, Session
from .database import init_db, get_session
from .models import (
    User,
    StudentProfile,
    CurriculumTrack,
    Certification,
    ExtracurricularProgram,
)

BASE_DIR = Path(__file__).resolve().parent
static_dir = BASE_DIR / "static"
templates_dir = BASE_DIR / "templates"
static_dir.mkdir(parents=True, exist_ok=True)
templates_dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="학생정보시스템 - 로그인 페이지")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=60 * 60 * 8)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(
    request: Request,
    username: str = Form(None),      # 관리자 전용
    password: str = Form(None),      # 관리자 전용
    name: str = Form(None),          # 학생 전용
    student_no: str = Form(None),    # 학생 전용
    role: str = Form("student"),
    session: Session = Depends(get_session),
):
    if role == "student":
        profile = session.exec(
            select(StudentProfile).where(
                StudentProfile.name == name,
                StudentProfile.student_no == student_no
            )
        ).first()
        if not profile:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "이름 또는 학번이 올바르지 않습니다."},
                status_code=401,
            )
        request.session["student_id"] = profile.id
        return RedirectResponse("/student", status_code=303)

    else:  # 관리자 로그인
        user = session.exec(select(User).where(User.username == username)).first()
        if not user or not user.verify_password(password):
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "아이디 또는 비밀번호가 올바르지 않습니다."},
                status_code=401,
            )
        request.session["user_id"] = user.id
        return RedirectResponse("/admin", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# 유틸: 현재 로그인 사용자
def current_user(request: Request, session: Session) -> User | None:
    uid = request.session.get("user_id")
    return session.get(User, uid) if uid else None


# 학생 조회 페이지
@app.get("/student", response_class=HTMLResponse)
def student_dashboard(request: Request, session: Session = Depends(get_session)):
    sid = request.session.get("student_id")
    if not sid:
        return RedirectResponse("/", status_code=303)

    profile = session.get(StudentProfile, sid)
    if not profile:
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        "student.html",
        {"request": request, "profile": profile}
    )


# 관리자 인증 유틸
def require_admin(request: Request, session: Session) -> User:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=303, detail="redirect", headers={"Location": "/"})
    user = session.get(User, uid)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자만 접근할 수 있습니다.")
    return user


# 관리자 등록 페이지
@app.get("/admin", response_class=HTMLResponse)
def admin_register_page(request: Request, session: Session = Depends(get_session)):
    admin = require_admin(request, session)
    curr = session.exec(select(CurriculumTrack).order_by(CurriculumTrack.id.desc()).limit(8)).all()
    cert = session.exec(select(Certification).order_by(Certification.id.desc()).limit(8)).all()
    extra = session.exec(select(ExtracurricularProgram).order_by(ExtracurricularProgram.id.desc()).limit(8)).all()

    return templates.TemplateResponse(
        "admin_register.html",
        {
            "request": request,
            "admin": admin,
            "curr_list": curr,
            "cert_list": cert,
            "extra_list": extra,
            "msg": request.query_params.get("msg"),
        },
    )


# ===== 조회 라우트(분리) =====

@app.get("/admin/view", response_class=HTMLResponse)
def admin_view_root():
    return RedirectResponse("/admin/view/students", status_code=303)


# /admin/view/students
@app.get("/admin/view/students", response_class=HTMLResponse)
def view_students(
    request: Request,
    page: int = 1,
    size: int = 20,
    kw: str | None = None,
    session: Session = Depends(get_session),
):
    admin = require_admin(request, session)

    page = max(1, page)
    size = min(max(1, size), 100)
    offset = (page - 1) * size

    # ✅ 이제 StudentProfile만 조회
    profiles = session.exec(
        select(StudentProfile).order_by(StudentProfile.id.desc())
    ).all()

    # 키워드 필터 (이름/학번/대학/학과)
    def match_kw(p: StudentProfile):
        if not kw:
            return True
        blob = " ".join([
            p.name or "",
            p.student_no or "",
            p.college or "",
            p.department or "",
        ])
        return (kw in blob)

    rows_all = [p for p in profiles if match_kw(p)]
    total = len(rows_all)
    rows = rows_all[offset: offset + size]

    return templates.TemplateResponse(
        "admin_view_students.html",
        {
            "request": request,
            "admin": admin,
            "rows": rows,              # ✅ 이제 rows는 StudentProfile 리스트
            "total": total,
            "page": page,
            "size": size,
            "kw": kw or "",
            "active": "students",
        },
    )



@app.get("/admin/view/curriculum", response_class=HTMLResponse)
def view_curriculum(request: Request, session: Session = Depends(get_session)):
    admin = require_admin(request, session)
    items = session.exec(select(CurriculumTrack).order_by(CurriculumTrack.id.desc())).all()
    return templates.TemplateResponse(
        "admin_view_curriculum.html",
        {"request": request, "admin": admin, "items": items},
    )


@app.get("/admin/view/certifications", response_class=HTMLResponse)
def view_certifications(request: Request, session: Session = Depends(get_session)):
    admin = require_admin(request, session)
    items = session.exec(select(Certification).order_by(Certification.id.desc())).all()
    return templates.TemplateResponse(
        "admin_view_certifications.html",
        {"request": request, "admin": admin, "items": items},
    )


@app.get("/admin/view/extracurriculars", response_class=HTMLResponse)
def view_extracurriculars(request: Request, session: Session = Depends(get_session)):
    admin = require_admin(request, session)
    items = session.exec(select(ExtracurricularProgram).order_by(ExtracurricularProgram.id.desc())).all()
    return templates.TemplateResponse(
        "admin_view_extracurriculars.html",
        {"request": request, "admin": admin, "items": items},
    )


# ===== 등록 처리 라우트 =====

@app.post("/admin/students")
def admin_create_student(
    request: Request,
    name: str = Form(...),
    student_no: str = Form(...),
    college: str = Form(None),
    department: str = Form(None),
    # certification_track: str = Form(None),
    # extracurricular_programs: str = Form(None),
    # consortium_status: str = Form(None),
    session: Session = Depends(get_session),
):
    require_admin(request, session)

    # ✅ 학번 기준 upsert
    prof = session.exec(
        select(StudentProfile).where(StudentProfile.student_no == student_no)
    ).first()

    if not prof:
        prof = StudentProfile(student_no=student_no)

    prof.name = name
    prof.college = college
    prof.department = department
    # prof.certification_track = certification_track
    # prof.extracurricular_programs = extracurricular_programs
    # prof.consortium_curriculum_status = consortium_status

    session.add(prof)
    session.commit()

    return RedirectResponse("/admin?msg=학생+등록/수정+완료", status_code=303)


@app.post("/admin/curriculum")
def admin_create_curriculum(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    item = CurriculumTrack(name=name, description=description)
    session.add(item)
    session.commit()
    return RedirectResponse("/admin?msg=교과인증과정+등록완료", status_code=303)


@app.post("/admin/certification")
def admin_create_certification(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    item = Certification(name=name, description=description)
    session.add(item)
    session.commit()
    return RedirectResponse("/admin?msg=인증제+등록완료", status_code=303)


@app.post("/admin/extracurricular")
def admin_create_extracurricular(
    request: Request,
    name: str = Form(...),
    description: str = Form(None),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    item = ExtracurricularProgram(name=name, description=description)
    session.add(item)
    session.commit()
    return RedirectResponse("/admin?msg=비교과+프로그램+등록완료", status_code=303)
