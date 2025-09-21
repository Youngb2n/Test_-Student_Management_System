import os
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, HTTPException, Form, Depends
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
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=60*60*8)

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
    username: str = Form(...),
    password: str = Form(None),       # 관리자만 사용
    student_no: str = Form(None),     # 학생만 사용
    role: str = Form("student"),
    session: Session = Depends(get_session),
):
    user = session.exec(select(User).where(User.username == username)).first()

    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "계정을 찾을 수 없습니다."},
            status_code=401,
        )

    if role == "student":
        # 학생은 학번 확인
        profile = session.exec(
            select(StudentProfile).where(StudentProfile.user_id == user.id)
        ).first()
        if not profile or profile.student_no != student_no:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "학번이 올바르지 않습니다."},
                status_code=401,
            )
    else:
        # 관리자: 비밀번호 검증
        if not user.verify_password(password):
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "아이디 또는 비밀번호가 올바르지 않습니다."},
                status_code=401,
            )

    if role and user.role != role:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": f"'{role}' 역할로 로그인할 수 없습니다."},
            status_code=403,
        )

    request.session["user_id"] = user.id

    if user.role == "student":
        return RedirectResponse("/student", status_code=303)
    else:
        return RedirectResponse("/admin", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)

# 현재 사용자 가져오기 유틸
def current_user(request: Request, session: Session) -> User | None:
    uid = request.session.get("user_id")
    return session.get(User, uid) if uid else None

# 학생 조회 페이지
@app.get("/student", response_class=HTMLResponse)
def student_dashboard(request: Request, session: Session = Depends(get_session)):
    user = current_user(request, session)
    if not user:
        return RedirectResponse("/", status_code=303)
    if user.role != "student":
        raise HTTPException(status_code=403, detail="학생만 접근할 수 있습니다.")

    profile = session.exec(select(StudentProfile).where(StudentProfile.user_id == user.id)).first()
    return templates.TemplateResponse("student.html", {"request": request, "user": user, "profile": profile})

def require_admin(request: Request, session: Session) -> User:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=303, detail="redirect", headers={"Location": "/"})
    user = session.get(User, uid)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="관리자만 접근할 수 있습니다.")
    return user

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, session: Session = Depends(get_session)):
    admin = require_admin(request, session)
    # 간단히 최근 등록 목록 몇 개만 내려줌
    curr = session.exec(select(CurriculumTrack).order_by(CurriculumTrack.id.desc()).limit(10)).all()
    cert = session.exec(select(Certification).order_by(Certification.id.desc()).limit(10)).all()
    extra = session.exec(select(ExtracurricularProgram).order_by(ExtracurricularProgram.id.desc()).limit(10)).all()
    return templates.TemplateResponse("admin.html", {
        "request": request, "admin": admin,
        "curr_list": curr, "cert_list": cert, "extra_list": extra,
        "msg": request.query_params.get("msg")
    })

# ① 학생 등록/업데이트
@app.post("/admin/students")
def admin_create_student(
    request: Request,
    username: str = Form(...),
    name: str = Form(...),
    student_no: str = Form(...),
    college: str = Form(None),
    department: str = Form(None),
    certification_track: str = Form(None),
    extracurricular_programs: str = Form(None),
    consortium_status: str = Form(None),
    session: Session = Depends(get_session),
):
    require_admin(request, session)
    # User upsert (학생은 password 불필요: username+student_no로 로그인)
    user = session.exec(select(User).where(User.username == username)).first()
    if not user:
        user = User(username=username, role="student", password_hash="")  # 비번 미사용
        session.add(user)
        session.commit()
        session.refresh(user)

    # StudentProfile upsert
    prof = session.exec(select(StudentProfile).where(StudentProfile.user_id == user.id)).first()
    if not prof:
        prof = StudentProfile(user_id=user.id)
    prof.name = name
    prof.student_no = student_no
    prof.college = college
    prof.department = department
    prof.certification_track = certification_track
    prof.extracurricular_programs = extracurricular_programs
    prof.consortium_curriculum_status = consortium_status
    session.add(prof)
    session.commit()

    return RedirectResponse("/admin?msg=학생+등록/수정+완료", status_code=303)

# ② 교과인증과정 등록
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

# ③ 인증제 등록
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

# ④ 비교과 프로그램 등록
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