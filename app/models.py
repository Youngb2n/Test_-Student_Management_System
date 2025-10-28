from __future__ import annotations
from sqlmodel import SQLModel
import datetime as dt
from sqlalchemy import (
    String,
    Integer,
    Date,
    DateTime,
    Float,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Index,
    CheckConstraint,
    text,
    Text,    
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)
from sqlalchemy.sql import func
from typing import Optional, List
from sqlalchemy.dialects.postgresql import JSONB


# ─────────────────────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# 학생(Student)
# ─────────────────────────────────────────────────────────────────────────────
class Student(Base):
    """
    학생 기본 정보 및 학적.
    - 휴학 여부/휴학년도/휴학학기 정합성 보장
    - 재직자 전형일 경우만 workplace/health_insurance_certificate 허용
    관계:
      - course_enrollments: 교과목 수강 (N:M 해소)
      - curriculum_enrollments: 교육과정(인증제 등) 소속 (N:M 해소)
      - program_attendances: 비교과 활동(ProgramEnrollment) 스냅샷
      - internship_attendances: 인턴십 활동(InternshipEnrollment) 스냅샷
    """

    __tablename__ = "student"
    __table_args__ = (
        UniqueConstraint("student_no", name="uq_student_student_no"),
        UniqueConstraint("researcher_id", name="uq_student_researcher_id"),
        Index("ix_student_name", "name"),
        # 입학년도 합리 범위
        CheckConstraint(
            "admission_year BETWEEN 1990 AND EXTRACT(YEAR FROM NOW())::int + 1",
            name="ck_admission_year_range",
        ),
        # 생년월일은 1900-01-01 이후 오늘 이전
        CheckConstraint(
            "birthdate >= DATE '1900-01-01' AND birthdate <= NOW()",
            name="ck_birthdate_range",
        ),
        # 재직자 전형 전용 필드 무결성
        CheckConstraint(
            "((admission_type = '재직자 전형' AND workplace IS NOT NULL) "
            "OR (admission_type <> '재직자 전형' AND workplace IS NULL AND health_insurance_certificate IS NULL))",
            name="ck_employed_track_fields_required",
        ),
    )

    # PK
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- 기본정보 ---
    student_no: Mapped[str] = mapped_column(String(20), nullable=False)  # 학번(문자열)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # 이름
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)  # 영문명
    birthdate: Mapped[dt.date] = mapped_column(Date, nullable=False)  # 생년월일 !!입력시 (연도월일 8자리)!!

    researcher_id: Mapped[str] = mapped_column(String(100), nullable=False)  # 국가연구자번호
    nationality: Mapped[str] = mapped_column(String(100), nullable=False)  # 국적 !입력시 대한민국 영문명이 default!! @@등록선택옵션(국적 영문명)@@
    foreigner_reg_no: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 외국인등록번호

    email_snu: Mapped[str | None] = mapped_column(String(200), nullable=False)  # 이메일(SNU) !!등록도메인고정(snu.ac.kr)!! 
    email_other: Mapped[str] = mapped_column(String(200), nullable=True)  # 이메일(기타) @@등록선택옵션(gmail.com/naver.com/hanmail.net/기타) 이외에도 일반적으로 많이 사용하는 도메인@@
    mobile_phone_num: Mapped[str] = mapped_column(String(30), nullable=False)  # 휴대폰 
    phone_num: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 일반 연락처

    # --- 재학/입학 관련 ---
    degree: Mapped[str] = mapped_column(String(50), nullable=False)  # 학위과정 @@등록선택옵션(학사/석사/박사/석박통합)@@
    college: Mapped[str] = mapped_column(String(100), nullable=False)  # 소속대학 !!입력 의과대학 default!! @@등록선택옵션(인문대학/사회과학대학/자연과학대학/간호대학/경영대학/공과대학/농업생명과학대학/미술대학/사범대학/생활과학대학/수의과대학/약학대학/음악대학/의과대학/자유전공학부/첨단융합학부/데이터사이언스대학원/융합과학기술대학원)@@
    collaborative_program: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 협동과정 !!입력 체크박스!! @@등록선택옵션(해당/미해당)@@
    department: Mapped[str] = mapped_column(String(100), nullable=False)  # 학과 !!입력시 (띄어쓰기, · 생략)!!
    major: Mapped[str] = mapped_column(String(100), nullable=False)  # 전공 !!입력시 (띄어쓰기, · 생략)!!
    admission_year: Mapped[int] = mapped_column(Integer, nullable=False)  # 입학년도 !!입력시 2000~2100년도에 대해 선택해서 받을 수 있게, 올해연도 default, 키보드로 입력가능!!
    admission_term: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 입학학기 ("1학기"/"2학기") @@등록선택옵션 (1학기/2학기)@@
    admission_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 입학전형 @@ 등록선택옵션선택 (일반(전일제)/일반(파트)/재직자 전형/외국인 전형/타학교 편입/타과 편입)@@

    # 재직자전형일 경우만
    workplace: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 근무지 !!재직자 전형일 경우만 입력할 수 있게 활성화!!
    health_insurance_certificate: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # 건강보험자격득실확인서 경로 !!재직자 전형일 경우만 입력할 수 있게 활성화, 버튼으로 파일 업로드하고 경로에 대해 저장, 현재단계에서는 버튼만 생성하고 기능구현 X!!

    academic_status: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # 학적상태 @@등록선택옵션 (재학/수료/졸업/기타)@@
    leave_of_absence: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # 휴학여부 @@등록선택옵션 (Leave/Enrolled)@@ !!휴학 선택여부가 Y일 경우 StudentLeaveHistory 테이블의 연도와 학기를 입력할 수 있도록 구성 + 누르면 추가 입력 받을 수 있도록 구성 - 한 학생이 여러번 휴학할 수 도 있으니!!

    advisor_name: Mapped[str] = mapped_column(String(50), nullable=False)  # 지도교수
    supervisor_name: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # 담당교수

    previous_degree: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # 입학 전 최종학위
    previous_major: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # 입학 전 최종학위 전공 @@등록선택옵션 (학사/석사/박사/석박사통합과정(석사)/석박사통합과정(박사))@@
    previous_degree_year: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 최종학위 취득연도 !!입력시 연도 선택 (2000~2100), 현 연도 default, 키보드로도 입력가능)!!
    previous_institution: Mapped[str] = mapped_column(
        String(150), nullable=False
    )  # 최종학위 대학명

    # --- 졸업 및 진로 현황 (졸업자에게만 의미) --- !!졸업에 대한 정보들은 등록 페이지가 아닌 조회 페이지에서 입력이 가능하도록 구성, academic_status가 졸업으로 변경 시 입력할 수 있도록!!
    graduation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 졸업연도 !!입력시 연도 선택 (2000~2100), 현 연도 default, 키보드로도 입력가능)!!
    graduation_month: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 졸업월 !!입력시 월 선택(2/8)!!
    degree_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # 학위번호 !!입력단에서 중복체크 후 중복 시 등록 불가능하도록!!
    graduation_certificate: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # 졸업증명서 경로 !!버튼을 통해 파일을 업로드하고 해당 경로에 대해 저장, 현재단계에서는 버튼만 생성하고 기능구현 X!!
    further_study: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # 진로 여부 @@등록선택옵션 (진학/취업(창업,미취업 포함)/확인불가)@@
    
    # !!진로 여부가 진학일 경우 입력 가능하도록 구성, 진학 나라 선택칸  & 진학 정보 입력란 & 전공연계여부 체크칸 한줄로 구성 (구조 예시 : [선택칸▼] [ 입력칸 ]전공 * 전공 연계 여부 □ 한)!!
    further_study_country: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # 진학 나라 !!@@등록선택옵션 (국내/국외)@@
    further_study_info: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # 진학 정보 
    further_study_type: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )  # 진학 전공 연계 여부

    # !!진로 여부가 취업(창업,미취업 포함)인 경우 취업관련 정보 입력 활성화, 미입력 시 등록 불가능하도록!!
    #
    employment_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # 취업 유형 선택 @@등록선택옵션 (대기업/중소중견기업/연구소/정부기관/학계/창업/기타취업/포닥/군입대/미취업)@@
    employment_study_type: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )  # 취업 전공 연계 여부 !!입력시 취업 유형 선택칸 우측 체크박스로 입력!!
    employment_uploaded: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # 취업 관련 업로드 경로 !!버튼을 통해 파일을 업로드하고 해당 경로에 대해 저장, 현재단계에서는 버튼만 생성하고 기능구현 X!!
    employment_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # 취업 기관명

    # --- 관계: 학생 ↔ 교과목 / 학생 ↔ 교육과정 / 학생 ↔ 비교과·인턴십 활동 ---
    course_enrollments: Mapped[list["StudentCourseEnrollment"]] = relationship(
        "StudentCourseEnrollment",
        back_populates="student",
        cascade="all, delete-orphan",
    )

    curriculum_enrollments: Mapped[list["StudentCurriculumEnrollment"]] = relationship(
        "StudentCurriculumEnrollment",
        back_populates="student",
        cascade="all, delete-orphan",
    )

    program_attendances: Mapped[list["ProgramEnrollment"]] = relationship(
        "ProgramEnrollment",
        back_populates="student",
        cascade="all, delete-orphan",
    )

    internship_attendances: Mapped[list["InternshipEnrollment"]] = relationship(
        "InternshipEnrollment",
        back_populates="student",
        cascade="all, delete-orphan",
    )

    # Participant 역참조 (학생이 외부참석자로도 찍힐 수 있기 때문에)
    participant_profiles: Mapped[list["Participant"]] = relationship(
        "Participant",
        back_populates="student",
        cascade="all, delete-orphan",
    )
    #학생 휴학 역참조
    leave_history: Mapped[list["StudentLeaveHistory"]] = relationship(
        "StudentLeaveHistory",
        cascade="all, delete-orphan",
        back_populates="student",
    )   

    # 타임스탬프
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 학생 휴학 관리
# ─────────────────────────────────────────────────────────────────────────────
class StudentLeaveHistory(Base):
    __tablename__ = "student_leave_history"
    __table_args__ = (
        CheckConstraint(
            "leave_semester IN ('1학기','2학기')",
            name="ck_leave_semester_values",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="CASCADE"),
        nullable=False,
        comment="휴학한 학생 ID",
    )

    leave_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="휴학 연도",
    ) # !!등록 페이지에서 휴학 선택 시 해당 정보 입력하도록 , 선택(2000~2100)!!

    leave_semester: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="휴학 학기 (1학기/2학기)",
    ) # !!등록 페이지에서 1학기/2학기 선택해서 입력할 수 있도로 구성!!

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    student: Mapped["Student"] = relationship(
        "Student",
        back_populates="leave_history",
    )

# ─────────────────────────────────────────────────────────────────────────────
# 교과목(Course)
# ─────────────────────────────────────────────────────────────────────────────
class Course(Base):
    """
    교과목 정의(교과목 자체 스펙).
    (비교과 출결/참석과는 무관)
    """

    __tablename__ = "course"
    __table_args__ = (
        Index("ix_course_name_ko", "course_name_ko"),
        Index("ix_course_name_en", "course_name_en"),
    )

    # PK
    course_code: Mapped[str] = mapped_column(
        String(50), primary_key=True, nullable=False
    )  # 교과목번호
    curriculumprogram_relation: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # 교육과정지정교과목 등록/제외 여부  !!교육과정지정교과목으로 되면 자동으로 "등록" default= "제외",입력단계에서 어떤 교육과정과 연결되는지 추가(CurriculumCourseMap)할 수 있고 CurriculumCourseMap정보 입력 가능 하도록 구성, + 버튼을 통해서 여러개 추가할 수 있도록 구성!!
    
    # --- 교과목 기본정보 ---
    course_name_ko: Mapped[str] = mapped_column(
        String(200), nullable=False
    )  # 교과목명(국문)
    course_name_en: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # 교과목명(영문)

    # --- 과정/학년/개설 정보 ---
    degree_level: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # 과정 @@등록선택옵션 (학사/대학원)@@
    grade_level: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 학년 @@등록선택옵션 (0~6)@@
    offering_semester: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 개설학기 @@등록선택옵션(1학기/2학기)@@
    offering_cycle: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # 개설주기 @@등록선택옵션 (1년/2년/기타)@@

    # --- 성적/학점 구조 ---
    grading_scheme: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # 성적부여방식 @@등록선택옵션 (A~F/S/U)@@

    # !!credit, lecture_hours, lab_hours는 선택 – 선택 – 선택 형식으로 입력받을 수 있도록!!
    credit: Mapped[int] = mapped_column(Integer, nullable=False)  # 학점 @@등록선택옵션 (0~6)@@
    lecture_hours: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 강의 시수 @@등록선택옵션 (0~6)@@
    lab_hours: Mapped[int] = mapped_column(Integer, nullable=False)  # 실습 시수 @@등록선택옵션 (0~6)@@

    # --- 소속/교원/정원 ---
    department_name: Mapped[str | None] = mapped_column(
        String(150), nullable=True
    )  # 개설 주체 학과 !!입력시 띄어쓰기나 특수문자 입력 시 오류 팝업창 생성, 등록 안되도록!!
    instructor_name: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # 담당 교수명
    capacity: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 수강정원
    enrollment: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 수강인원

    # 관계: 학생 수강 기록 (N:M 해소용)
    student_enrollments: Mapped[list["StudentCourseEnrollment"]] = relationship(
        "StudentCourseEnrollment",
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # 관계: 교육과정 지정 교과목 매핑(M:N via CurriculumCourseMap)
    curriculum_mappings: Mapped[list["CurriculumCourseMap"]] = relationship(
        "CurriculumCourseMap",
        back_populates="course",
        cascade="all, delete-orphan",
    )

    # 타임스탬프
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 사업단 주관 사업(BusinessInitiative)
# ─────────────────────────────────────────────────────────────────────────────
class BusinessInitiative(Base):
    """
    사업단 주관 사업.
    - 하나의 BusinessInitiative는 여러 CurriculumProgram(교육과정)을 가질 수 있다 (1:N).
    - 학생은 CurriculumProgram을 통해 간접적으로 귀속된다.
    """

    __tablename__ = "business_initiative"
    __table_args__ = (
        UniqueConstraint("project_name", "start_date", name="uq_business_project_start"),
        CheckConstraint("start_date <= end_date", name="ck_business_dates"),
        Index("ix_business_name", "project_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 기본 정보
    project_name: Mapped[str] = mapped_column(
        String(200), nullable=False
    )  # 사업명
    support_agency: Mapped[str | None] = mapped_column(
        String(150), nullable=True
    )  # 지원부처
    specialized_institute: Mapped[str | None] = mapped_column(
        String(150), nullable=True
    )  # 전문기관
    research_task_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # 연구과제명

    # 사업일정
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False) #최초 시작일자 !!날짜 선택(캘린더 형식)!!
    end_date: Mapped[dt.date] = mapped_column(Date, nullable=False)# 최종 종료일자 !!날짜 선택(캘린더 형식)!!

    # KPI/목표
    beneficiary_target: Mapped[int | None] = mapped_column(
        Float, nullable=True
    )  # 수혜 목표
    output_target: Mapped[int | None] = mapped_column(
        Float, nullable=True
    )  # 배출 목표
    career_linked_target: Mapped[int | None] = mapped_column(
        Float, nullable=True
    )  # 진로연계 취창업 목표

    # 관계: 교육과정들 (1:N)
    curriculum_programs: Mapped[list["CurriculumProgram"]] = relationship(
        "CurriculumProgram",
        back_populates="business_initiative",
    )

    # 타임스탬프
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 교육과정 / 인증제 (CurriculumProgram)
# ─────────────────────────────────────────────────────────────────────────────
class CurriculumProgram(Base):
    """
    교과(인증)과정 및 인증제 정의.
    - 하나의 CurriculumProgram은 여러 ProgramRequirement(이수조건 버전)를 가질 수 있음 (1:N).
    - 하나의 CurriculumProgram은 여러 학생(StudentCurriculumEnrollment)을 가질 수 있음 (N:M 해소).
    - CurriculumProgramMap / CurriculumInternshipMap / CurriculumCourseMap 으로
      비교과 / 인턴십 / 교과목 인정 연결.
    """

    __tablename__ = "curriculum_program"
    __table_args__ = (
        UniqueConstraint(
            "program_type", "course_name", "open_year", name="uq_curriculum_unique"
        ),
        Index("ix_curriculum_program_name", "program_type"),
        CheckConstraint(
            "open_year BETWEEN 2000 AND 2100", name="ck_open_year_range"
        ),
        CheckConstraint(
            "(close_year IS NULL) OR (close_year BETWEEN 2000 AND 2100)",
            name="ck_close_year_range",
        ),
        CheckConstraint(
            "open_semester IN ('1학기','2학기')", name="ck_open_semester_values"
        ),
        CheckConstraint(
            "(close_semester IS NULL) OR (close_semester IN ('1학기','2학기'))",
            name="ck_close_semester_values",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 소속 사업단(옵션) : 각 교육과정은 최대 1개의 사업에만 속함
    business_initiative_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_initiative.id", ondelete="SET NULL"),
        nullable=True,
        comment="이 교육과정을 주관하는 사업단 사업 ID",
    )

    # 과정 속성
    program_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # @@등록선택옵션 (인증제/교과인증과정/교과과정)@@
    course_name: Mapped[str] = mapped_column(
        String(200), nullable=False
    )  # 과정명
    degree_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # 학위 구분 @@등록선택옵션 (학부/대학원/통합)@@
    department_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # 학과 구분 @@등록선택옵션 (의과대학/공과대학/첨단융합학부/통합)@@

    # 운영 기간
    open_year: Mapped[int] = mapped_column(Integer, nullable=False)  # 개설연도 !!입력시 2000~2100년도에 대해 선택해서 받을 수 있게, 올해연도 default, 키보드로 입력가능!!
    open_semester: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 개설학기 @@등록선택옵션 (1학기/2학기)@@
    close_year: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 폐지연도 !!입력시 2000~2100년도에 대해 선택해서 받을 수 있게, 올해연도 default, 키보드로 입력가능!!
    close_semester: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # 폐지학기 @@등록선택옵션 (1학기/2학기)@@

    # 관계: 사업 ↔ 교육과정 (1:N)
    business_initiative: Mapped["BusinessInitiative"] = relationship(
        "BusinessInitiative",
        back_populates="curriculum_programs",
    )

    # 관계: 교육과정 ↔ 비교과프로그램 (M:N via CurriculumProgramMap)
    program_mappings: Mapped[list["CurriculumProgramMap"]] = relationship(
        "CurriculumProgramMap",
        back_populates="curriculum",
        cascade="all, delete-orphan",
    )

    # 관계: 교육과정 ↔ 인턴십 (M:N via CurriculumInternshipMap)
    internship_mappings: Mapped[list["CurriculumInternshipMap"]] = relationship(
        "CurriculumInternshipMap",
        back_populates="curriculum",
        cascade="all, delete-orphan",
    )

    # 관계: 교육과정 ↔ 교과목 (M:N via CurriculumCourseMap)
    course_mappings: Mapped[list["CurriculumCourseMap"]] = relationship(
        "CurriculumCourseMap",
        back_populates="curriculum",
        cascade="all, delete-orphan",
    )

    # 관계: 교육과정 ↔ 학생 (N:M 해소)
    student_enrollments: Mapped[list["StudentCurriculumEnrollment"]] = relationship(
        "StudentCurriculumEnrollment",
        back_populates="curriculum_program",
        cascade="all, delete-orphan",
    )

    # 관계: 교육과정 ↔ 이수조건 (1:N)
    requirements: Mapped[list["ProgramRequirement"]] = relationship(
        "ProgramRequirement",
        back_populates="curriculum",
        cascade="all, delete-orphan",
    )

    # 타임스탬프
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 교육과정 이수조건 (ProgramRequirement)
# ─────────────────────────────────────────────────────────────────────────────
class ProgramRequirement(Base):
    """
    교육과정별 이수조건(버전).
    - 하나의 ProgramRequirement는 정확히 하나의 CurriculumProgram에 속한다 (N:1).
    - requirement_code (예: 20250001MC)는 생성 후 변경 금지(어플리케이션에서 관리).
    - 비교과 요구량(환산 점수 합), 인턴십 요구량(환산 점수 합),
      비교과 유형별 최소참석 횟수까지 포함.
    """

    __tablename__ = "program_requirement"
    __table_args__ = (
        Index("ix_program_requirement_code", "requirement_code"),
        Index("ix_program_requirement_curriculum", "curriculum_id"),
        CheckConstraint(
            "college_scope IN ('의과대학','그 외')",
            name="ck_requirement_college_scope",
        ),
        CheckConstraint(
            "degree_scope IN ('학부','석사','박사','대학원생','통합')",
            name="ck_requirement_degree_scope",
        ),
        CheckConstraint(
            "required_credit >= 0.0",
            name="ck_requirement_required_credit_nonneg",
        ),
        CheckConstraint(
            "total_converted_required >= 0.0",
            name="ck_requirement_total_converted_required_nonneg",
        ),
        CheckConstraint(
            "total_internship_required >= 0.0",
            name="ck_requirement_total_internship_required_nonneg",
        ),
        CheckConstraint(
            "min_ai_med_talks >= 0 AND "
            "min_company_visit >= 0 AND "
            "min_hospital_visit >= 0 AND "
            "min_seminar >= 0 AND "
            "min_exchange_forum >= 0 AND "
            "min_expo >= 0 AND "
            "min_academic_conf >= 0 AND "
            "min_competition >= 0 AND "
            "min_etc >= 0",
            name="ck_requirement_min_attendance_nonneg",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    curriculum_id: Mapped[int] = mapped_column(
        ForeignKey("curriculum_program.id", ondelete="CASCADE"),
        nullable=False,
        comment="이 이수조건이 속한 교육과정 ID",
    )

    # 고유번호 (예: 20250001MC)
    requirement_code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        unique=True,
        comment="YYYY + seq(4자리) + college_code(M/E) + degree_code(B/M/D/C...). 생성 후 수정 금지",
    )

    college_scope: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="적용 기준(대학): '의과대학' / '그 외'",
    ) # 적용기준(대학) @@등록선택옵션 (의과대학/그 외)@@
    degree_scope: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="적용 기준(학위): '학부','석사','박사','대학원생','통합' 등",
    )# 적용기준(학위) @@등록선택옵션 (학부/석사/박사/대학원생)@@

    curriculum_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="교육과정명(사람이 보는 명칭; display용)",
    )
    
    # 교과 학점 요구량
    required_credit: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="해당 교육과정 이수에 필요한 교과 학점 요구량",
    )

    # 비교과 환산 점수 누적 최소 요구치
    total_converted_required: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="비교과(프로그램) 인정 환산 점수 합계 최소 요구치",
    )

    # 인턴십 환산 점수 누적 최소 요구치
    total_internship_required: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="인턴십(현장실습) 인정 환산 점수 합계 최소 요구치",
    )

    # 비교과 프로그램 유형별 최소 참석 횟수
    min_ai_med_talks: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # SNU AI.MED talks 시리즈
    min_company_visit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 기업 견학
    min_hospital_visit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 병원 견학
    min_seminar: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 교육 및 세미나
    min_exchange_forum: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 성과교류회
    min_expo: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 박람회
    min_academic_conf: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 학회
    min_competition: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 경진대회
    min_etc: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 기타

    # 역참조
    curriculum: Mapped["CurriculumProgram"] = relationship(
        "CurriculumProgram",
        back_populates="requirements",
    )

    applied_students: Mapped[list["StudentCurriculumEnrollment"]] = relationship(
        "StudentCurriculumEnrollment",
        back_populates="requirement",
        cascade="all, delete-orphan",
    )

    # 타임스탬프
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 학생 ↔ 교육과정 N:M 해소 (StudentCurriculumEnrollment)
# ─────────────────────────────────────────────────────────────────────────────
class StudentCurriculumEnrollment(Base):
    """
    학생이 어떤 CurriculumProgram(교육과정/인증제)에 소속·참여 중인지 기록.
    - 한 학생은 여러 CurriculumProgram에 속할 수 있음.
    - 한 CurriculumProgram에도 여러 학생이 속할 수 있음.
    - requirement_id는 '이 학생에게 실제 적용된 이수요건 버전(ProgramRequirement)' 스냅샷.
      → 나중에 요건이 바뀌어도 기존 학생 판정은 그대로 남아야 해서 FK로 고정.
    """

    __tablename__ = "student_curriculum_enrollment"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "curriculum_program_id",
            name="uq_student_curriculum_unique",
        ),
        CheckConstraint(
            "status IN ('ongoing','completed','withdrawn','suspended')",
            name="ck_student_curriculum_status_values",
        ),
        Index("ix_student_curriculum_student", "student_id"),
        Index("ix_student_curriculum_program", "curriculum_program_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="CASCADE"), nullable=False
    )

    curriculum_program_id: Mapped[int] = mapped_column(
        ForeignKey("curriculum_program.id", ondelete="CASCADE"), nullable=False
    )

    # 학생에게 실제로 적용 중인 이수 기준 버전
    requirement_id: Mapped[int | None] = mapped_column(
        ForeignKey("program_requirement.id", ondelete="SET NULL"),
        nullable=True,
        comment="학생에게 실제 적용된 ProgramRequirement 버전",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ongoing",
        comment="ongoing / completed / withdrawn / suspended",
    )

    joined_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    joined_term: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # "1학기"/"2학기"
    completed_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_term: Mapped[str | None] = mapped_column(String(10), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # 관계
    student: Mapped["Student"] = relationship(
        "Student",
        back_populates="curriculum_enrollments",
    )

    curriculum_program: Mapped["CurriculumProgram"] = relationship(
        "CurriculumProgram",
        back_populates="student_enrollments",
    )

    requirement: Mapped["ProgramRequirement"] = relationship(
        "ProgramRequirement",
        back_populates="applied_students",
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 비교과 프로그램(Program)
# ─────────────────────────────────────────────────────────────────────────────
class Program(Base):
    """
    비교과 프로그램(행사/세미나/특강 등).
    - 점수(환산값)는 교육과정별로 달라질 수 있기 때문에 Program 자체에는 점수 안 둔다.
    - 실제 점수는 CurriculumProgramMap.recognized_credit_ratio 에 정의됨.
    - 학생별 참석 기록에서는 그 순간의 환산점수를 ProgramEnrollment.recognized_credit 으로 스냅샷 저장.
    """

    __tablename__ = "program"
    __table_args__ = (
        UniqueConstraint(
            "program_name", "open_year", "open_month", name="uq_program_name_ym"
        ),
        Index("ix_program_type", "program_type"),
        Index("ix_program_name", "program_name"),
        CheckConstraint(
            "open_year BETWEEN 2000 AND 2100", name="ck_open_year_range"
        ),
        CheckConstraint(
            "open_month BETWEEN 1 AND 12", name="ck_open_month_range"
        ),
        CheckConstraint(
            "program_type IN ("
            "'SNU AI.MED talks 시리즈','기업 견학','병원 견학','교육 및 세미나',"
            "'성과교류회','박람회','학회','경진대회','기타'"
            ")",
            name="ck_program_type_values",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # !!비교과 프로그램 등록 페이지에서 어떤 교육과정에서 속해 있는지 추가 가능, CurriculumProgramMap의 입력정보도 같이 입력, + 버튼을 통해 추가 가능 (여러 교육과정에 속해 있을 수도 있음)!! 

    open_year: Mapped[int] = mapped_column(Integer, nullable=False)  # 개최 연도 !!입력시 2000~2100년도에 대해 선택해서 받을 수 있게, 올해연도 default, 키보드로 입력가능!!
    open_month: Mapped[int] = mapped_column(Integer, nullable=False)  # 개최 월 !!입력시 선택 (1~12)!!

    program_type: Mapped[str] = mapped_column(
        String(40), nullable=False
    )  # 유형 @@등록선택옵션 (SNU AI.MED talks 시리즈/기업 견학/병원 견학/교육 및 세미나/성과교류회/박람회/학회/경진대회/기타)@@
    program_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # 프로그램명
    sub_program_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # 세부 프로그램명

    organizer: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # 주관/주최
    event_material: Mapped[str | None] = mapped_column(
        String(300), nullable=True
    )  # 행사자료 경로 !!버튼을 통해 파일을 업로드하고 해당 경로에 대해 저장, 현재단계에서는 버튼만 생성하고 기능구현 X!!

    # 관계: 참석 기록
    enrollments: Mapped[list["ProgramEnrollment"]] = relationship(
        "ProgramEnrollment",
        back_populates="program",
        cascade="all, delete-orphan",
    )

    # 관계: 교육과정과의 매핑(M:N via CurriculumProgramMap)
    curriculum_mappings: Mapped[list["CurriculumProgramMap"]] = relationship(
        "CurriculumProgramMap",
        back_populates="program",
        cascade="all, delete-orphan",
    )

    # 타임스탬프
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 참석자(Participant)
# ─────────────────────────────────────────────────────────────────────────────
class Participant(Base):
    """
    비교과/인턴십 출석자(학생일 수도, 외부일 수도 있음).
    - affiliation + name + email 조합으로 사람을 식별(Unique).
    - student_id(FK)는 내부 student 레코드와 매칭될 경우만 채움 (외부인은 NULL).
    """

    __tablename__ = "participant"
    __table_args__ = (
        UniqueConstraint(
            "affiliation", "name", "email", name="uq_participant_identity"
        ),
        Index("ix_participant_name", "name"),
        Index("ix_participant_affiliation", "affiliation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 내부 Student 연결 (있으면 학생, 없으면 외부인)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("student.id", ondelete="SET NULL"),
        nullable=True,
        comment="student.id 레퍼런스. 내부 재학생/졸업생인 경우에만 세팅",
    )

    # 기본 인적사항
    affiliation: Mapped[str] = mapped_column(
        String(150), nullable=False
    )  # 소속(대학/기업/기관 등)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # 이름
    email: Mapped[str] = mapped_column(String(200), nullable=False)  # 이메일

    # 관계: 비교과/인턴십 참석 기록
    program_enrollments: Mapped[list["ProgramEnrollment"]] = relationship(
        "ProgramEnrollment",
        back_populates="participant",
        cascade="all, delete-orphan",
    )
    internship_enrollments: Mapped[list["InternshipEnrollment"]] = relationship(
        "InternshipEnrollment",
        back_populates="participant",
        cascade="all, delete-orphan",
    )

    # 역참조: 학생 ↔ Participant
    student: Mapped["Student"] = relationship(
        "Student",
        back_populates="participant_profiles",
    )

    # 타임스탬프
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 비교과 프로그램 참석 기록(ProgramEnrollment)
# !!비교과 프로그램 조회 페이지에서 해당 정보들 입력 가능하도록 구성, 엑셀파일로 추후 업로드 가능하도록 수정하도록 버튼만 구현 기능구현 X!!
# ─────────────────────────────────────────────────────────────────────────────
class ProgramEnrollment(Base):
    """
    비교과 Program 참여 스냅샷.
    - participant_id는 Participant(사람)를 가리킨다.
    - affiliation_snapshot / degree_program_snapshot / student_no_snapshot 등은
      당시 수집된 원본 텍스트 그대로 저장 (행정 증빙용)
    - recognized_credit 은 이 참석이 교육과정 요구치에서 몇 점으로 인정됐는지 저장.
      (CurriculumProgramMap.recognized_credit_ratio 기반 계산 결과)
    - student_id 는 '이 출석 기록을 실제로 어떤 학생에게 귀속시켰는지'를 스냅샷으로 저장.
    """

    __tablename__ = "program_enrollment"
    __table_args__ = (
        UniqueConstraint("program_id", "participant_id", name="uq_program_participant"),
        CheckConstraint(
            "recognized_credit >= 0 OR recognized_credit IS NULL",
            name="ck_recognized_credit_nonnegative",
        ),
        Index("ix_enroll_program", "program_id"),
        Index("ix_enroll_participant", "participant_id"),
        Index("ix_prog_enroll_student", "student_id"),
        CheckConstraint(
            "participation_type IN ('운영진','교수','조교','연구원','학생','외부')",
            name="ck_prog_participation_type",
        ),
        CheckConstraint(
            "degree_program_snapshot IN ('학사','석사','박사','석박통합','기타') "
            "OR degree_program_snapshot IS NULL",
            name="ck_prog_degree_program",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    program_id: Mapped[int] = mapped_column(
        ForeignKey("program.id", ondelete="CASCADE"), nullable=False
    )
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("participant.id", ondelete="CASCADE"), nullable=False
    )

    # 스냅샷: "이 점수를 누구 학생에게 귀속시킬 건가?"
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("student.id", ondelete="SET NULL"),
        nullable=True,
        comment="당시 이 참여를 인정받은 학생 ID. 외부인이면 NULL",
    )

    participation_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 운영진/교수/조교/연구원/학생/외부

    # 스냅샷(행사 당시 받는 값)
    affiliation_snapshot: Mapped[str] = mapped_column(
        String(150), nullable=False
    )  # 당시 소속
    degree_program_snapshot: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # 당시 학위과정
    student_no_snapshot: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )  # 당시 학번(해당자만)

    # 교육과정 인정 환산 점수 스냅샷
    recognized_credit: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    enroll_source: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        comment="데이터 입력 경로 (manual/excel_upload 등)",
    )

    exception_case: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="특이 케이스 여부(예외 인정 등)",
    )

    # 관계
    program: Mapped["Program"] = relationship(
        "Program",
        back_populates="enrollments",
    )
    participant: Mapped["Participant"] = relationship(
        "Participant",
        back_populates="program_enrollments",
    )
    student: Mapped["Student"] = relationship(
        "Student",
        back_populates="program_attendances",
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 인턴십(Internship)
# ─────────────────────────────────────────────────────────────────────────────
class Internship(Base):
    """
    인턴십 / 현장실습 프로그램 정의.
    - 하나의 Internship은 여러 참여자(InternshipEnrollment)를 가질 수 있음.
    - CurriculumInternshipMap 을 통해 교육과정(CurriculumProgram)과 연결되고
      그 연결에서 recognized_credit_ratio 로 환산 점수를 정할 수 있다.
    """

    __tablename__ = "internship"
    __table_args__ = (
        UniqueConstraint(
            "program_name", "start_date", name="uq_internship_name_start"
        ),
        Index("ix_internship_type", "internship_type"),
        CheckConstraint(
            "internship_type IN ('A','B','C','D','E')", name="ck_internship_type"
        ),
        CheckConstraint("start_date <= end_date", name="ck_internship_dates"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    internship_type: Mapped[str] = mapped_column(
        String(1), nullable=False
    )  # 인턴십 유형 @@등록선택옵션 (A/B/C/D/E)@@
    program_name: Mapped[str] = mapped_column(
        String(200), nullable=False
    )  # 프로그램명
    sub_program_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # 세부 프로그램명
    # !!인턴십 입력 페이지에서 등록된 교육과정 중 매핑할 수 있도록(CurriculumInternshipMap), CurriculumInternshipMap 정보 입력, + 버튼을 통해 교육과정 추가 등록가능!!
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)  # 시작일 !!입력시 캘린더에서 입력!!
    end_date: Mapped[dt.date] = mapped_column(Date, nullable=False)  # 종료일 !!입력시 캘린더에서 입력, 종료일 < 시작일 일 경우 오류 팝업 및 등록안되도록!!

    host_org_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # 시행기관구분 @@등록선택옵션 (대학/병원/기업/공공기관/기타)@@
    host_university_name: Mapped[str | None] = mapped_column(
        String(150), nullable=True
    )  # 시행기관(대학)명
    host_department_name: Mapped[str | None] = mapped_column(
        String(150), nullable=True
    )  # 시행기관(과/부서명)

    # 관계: 인턴십 참여자 기록
    enrollments: Mapped[list["InternshipEnrollment"]] = relationship(
        "InternshipEnrollment",
        back_populates="internship",
        cascade="all, delete-orphan",
    )

    # 관계: 교육과정 매핑(M:N via CurriculumInternshipMap)
    curriculum_mappings: Mapped[list["CurriculumInternshipMap"]] = relationship(
        "CurriculumInternshipMap",
        back_populates="internship",
        cascade="all, delete-orphan",
    )

    # 타임스탬프
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 인턴십 참여 기록(InternshipEnrollment)
# !!인턴십 조회 페이지에서 해당 정보들 입력 가능하도록 구성, 엑셀파일로 추후 업로드 가능하도록 수정하도록 버튼만 구현 기능구현 X!!
# ─────────────────────────────────────────────────────────────────────────────
class InternshipEnrollment(Base):
    """
    인턴십 참여 스냅샷.
    - participant_id로 Participant(사람)를 참조.
    - affiliation_snapshot / degree_program_snapshot / student_no_snapshot 등은
      당시 입력 원본 텍스트 그대로 저장.
    - student_id는 '이 인턴십 활동을 어떤 학생에게 귀속시켰는지'를 스냅샷.
    """

    __tablename__ = "internship_enrollment"
    __table_args__ = (
        UniqueConstraint(
            "internship_id", "participant_id", name="uq_internship_participant"
        ),
        Index("ix_intern_enroll_internship", "internship_id"),
        Index("ix_intern_enroll_participant", "participant_id"),
        Index("ix_intern_enroll_student", "student_id"),
        CheckConstraint(
            "participation_type IN ('운영진','교수','조교','연구원','학생','외부')",
            name="ck_intern_participation_type",
        ),
        CheckConstraint(
            "degree_program_snapshot IN ('학사','석사','박사','석박통합','기타') "
            "OR degree_program_snapshot IS NULL",
            name="ck_intern_degree_program",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    internship_id: Mapped[int] = mapped_column(
        ForeignKey("internship.id", ondelete="CASCADE"), nullable=False
    )
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("participant.id", ondelete="CASCADE"), nullable=False
    )

    # 스냅샷: 이 인턴십을 어떤 학생으로 인정할 것인지
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("student.id", ondelete="SET NULL"),
        nullable=True,
        comment="해당 인턴십 실적을 귀속시킬 학생. 외부인은 NULL",
    )

    participation_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 참여유형 @@등록선택옵션 (운영진/교수/조교/연구원/학생/외부)

    # 스냅샷(당시 입력값)
    # !! 참가자 테이블에서 관리하는거 같은데 참가자 이름도 입력받을 수 있도록 !!
    affiliation_snapshot: Mapped[str] = mapped_column(
        String(150), nullable=False
    )  # 소속(대학/기업명)
    student_no_snapshot: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )  # 학번(해당자만)
    degree_program_snapshot: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # 학위과정

    enroll_source: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        comment="데이터 입력 경로 (manual/excel_upload 등)",
    )

    # 관계
    internship: Mapped["Internship"] = relationship(
        "Internship",
        back_populates="enrollments",
    )
    participant: Mapped["Participant"] = relationship(
        "Participant",
        back_populates="internship_enrollments",
    )
    student: Mapped["Student"] = relationship(
        "Student",
        back_populates="internship_attendances",
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 교육과정 ↔ 비교과 프로그램 매핑 (CurriculumProgramMap)
# ─────────────────────────────────────────────────────────────────────────────
class CurriculumProgramMap(Base):
    """
    CurriculumProgram ↔ Program 매핑 테이블.
    - 어떤 비교과 프로그램이 어떤 교육과정에서 인정되는지, 그리고 그 1회 참석당 환산점수가 몇 점인지 관리.
    - recognized_credit_ratio: 이 교육과정에서 이 비교과 1건 참여가 몇 점(환산값)인지.
      이 값이 ProgramEnrollment.recognized_credit 계산의 기준이 된다.
    """

    __tablename__ = "curriculum_program_map"
    __table_args__ = (
        UniqueConstraint(
            "curriculum_id", "program_id", name="uq_curriculum_program"
        ),
        CheckConstraint(
            "recognized_credit_ratio >=0.0",
            name="ck_recognized_credit_ratio_range",
        ),
        Index("ix_curriculum_program_map_curriculum", "curriculum_id"),
        Index("ix_curriculum_program_map_program", "program_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    curriculum_id: Mapped[int] = mapped_column(
        ForeignKey("curriculum_program.id", ondelete="CASCADE"), nullable=False
    )
    program_id: Mapped[int] = mapped_column(
        ForeignKey("program.id", ondelete="CASCADE"), nullable=False
    )

    recognized_credit_ratio: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="이 교육과정에서 이 비교과 1회 참여 시 인정되는 환산값(점수)",
    )

    curriculum: Mapped["CurriculumProgram"] = relationship(
        "CurriculumProgram",
        back_populates="program_mappings",
    )
    program: Mapped["Program"] = relationship(
        "Program",
        back_populates="curriculum_mappings",
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 교육과정 ↔ 인턴십 매핑 (CurriculumInternshipMap)
# ─────────────────────────────────────────────────────────────────────────────
class CurriculumInternshipMap(Base):
    """
    CurriculumProgram ↔ Internship 매핑 테이블.
    - 어떤 인턴십이 어떤 교육과정에서 인정되는지 관리.
    - recognized_credit_ratio: 이 교육과정에서 인턴십 수행 1건(또는 단위기간)당
      인정되는 환산값(점수).
      학생 누적 인턴십 점수 합계는 ProgramRequirement.total_internship_required 와 비교.
    """

    __tablename__ = "curriculum_internship_map"
    __table_args__ = (
        UniqueConstraint(
            "curriculum_id", "internship_id", name="uq_curriculum_internship"
        ),
        Index("ix_curriculum_internship_curriculum", "curriculum_id"),
        Index("ix_curriculum_internship_internship", "internship_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    curriculum_id: Mapped[int] = mapped_column(
        ForeignKey("curriculum_program.id", ondelete="CASCADE"), nullable=False
    )
    internship_id: Mapped[int] = mapped_column(
        ForeignKey("internship.id", ondelete="CASCADE"), nullable=False
    )

    recognized_credit_ratio: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="이 교육과정에서 인턴십 수행 1건(또는 단위기간)당 인정되는 환산값(점수)",
    )

    note: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="세부 코멘트 / 트랙 설명 등",
    )

    curriculum: Mapped["CurriculumProgram"] = relationship(
        "CurriculumProgram",
        back_populates="internship_mappings",
    )
    internship: Mapped["Internship"] = relationship(
        "Internship",
        back_populates="curriculum_mappings",
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 교육과정 ↔ 교과목 매핑 (CurriculumCourseMap)
# !!교과목 입력 단계에서 해당정보도 같이 입력 받을 수 있도록 구성!!
# ─────────────────────────────────────────────────────────────────────────────
class CurriculumCourseMap(Base):
    """
    CurriculumProgram ↔ Course 매핑.
    - 이 교육과정에서 '인정되는 교과목' 목록을 관리.
    - 필수/선택 여부 등 정책을 컬럼으로 둘 수 있음.
    - 나중에 학생이 수강한 교과목 중 여기 매핑된 것만 모아서 학점 합산 → ProgramRequirement.required_credit 비교.
    """

    __tablename__ = "curriculum_course_map"
    __table_args__ = (
        UniqueConstraint("curriculum_id", "course_code", name="uq_curriculum_course"),
        Index("ix_curriculum_course_curriculum", "curriculum_id"),
        Index("ix_curriculum_course_course", "course_code"),
        CheckConstraint(
            "required_flag IN ('필수','선택')",
            name="ck_curriculum_course_required_flag",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    curriculum_id: Mapped[int] = mapped_column(
        ForeignKey("curriculum_program.id", ondelete="CASCADE"),
        nullable=False,
        comment="해당 교과목이 포함되는 교육과정",
    ) # 과정 및 프로그램 구분 !!선택할 수 있도록 구성 (등록된 교육과정명들/인턴십/기타/미해당)!!

    course_code: Mapped[str] = mapped_column(
        ForeignKey("course.course_code", ondelete="CASCADE"),
        nullable=False,
        comment="인정되는 교과목 코드",
    )

    required_flag: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="선택",
        comment="'필수' / '선택'",
    ) # 교육과정 필수/선택 @@등록선택옵션 (필수/선택)@@

        # --- 인정 기간 / 운영 기간 ---
    initial_year: Mapped[int] = mapped_column(Integer, nullable=False)  # 최초 인정연도 !!입력시 2000~2100년도에 대해 선택해서 받을 수 있게, 올해연도 default, 키보드로 입력가능!!
    initial_semester: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # 최초 인정학기 @@등록선택옵션 (1학기/2학기/여름/겨울)@@
    final_year: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 최종 인정연도 !!입력시 2000~2100년도에 대해 선택해서 받을 수 있게, 올해연도 default, 키보드로 입력가능!!
    final_semester: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # 최종 인정학기 @@등록선택옵션 (1학기/2학기/여름/겨울)@@

    curriculum: Mapped["CurriculumProgram"] = relationship(
        "CurriculumProgram",
        back_populates="course_mappings",
    )

    course: Mapped["Course"] = relationship(
        "Course",
        back_populates="curriculum_mappings",
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# 학생 ↔ 교과목 N:M (수강/이수 기록) StudentCourseEnrollment
# !!교과목 조회탭에서 학생명,학생학번을 조회하고 학생들을 추가할 수 있도록 구성!!
# ─────────────────────────────────────────────────────────────────────────────
class StudentCourseEnrollment(Base):
    """
    학생이 특정 학기/연도에 어떤 교과목을 수강/이수했는지 기록.
    동일 학생이 동일 과목을 동일 학기/연도에 중복등록 못하도록 UniqueConstraint.
    """

    __tablename__ = "student_course_enrollment"
    __table_args__ = (
        Index("ix_course_enroll_student", "student_id"),
        Index("ix_enroll_course", "course_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey("student.id", ondelete="CASCADE"), nullable=False
    )
    course_code: Mapped[str] = mapped_column(
        ForeignKey("course.course_code", ondelete="CASCADE"), nullable=False
    )

    # 관계
    student: Mapped["Student"] = relationship(
        "Student",
        back_populates="course_enrollments",
    )
    course: Mapped["Course"] = relationship(
        "Course",
        back_populates="student_enrollments",
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

# ─────────────────────────────────────────────────────────────────────────────
# 옵션 테이블
# ─────────────────────────────────────────────────────────────────────────────
class OptionItem(Base):
    __tablename__ = "optionitem"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_key: Mapped[str] = mapped_column(
        String(50), ForeignKey("optiongroup.key", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)

    # 타입별 값 (정확히 하나만 채움)
    value_text: Mapped[Optional[str]] = mapped_column(String(200))
    value_int:  Mapped[Optional[int]] = mapped_column(Integer)
    value_bool: Mapped[Optional[bool]] = mapped_column(Boolean)
    value_date: Mapped[Optional[dt.date]] = mapped_column(Date)
    value_json: Mapped[Optional[dict]] = mapped_column(JSONB)

    order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        # 그룹 검색/조인 편의
        Index("ix_optionitem_group_key", "group_key"),

        # 정확히 하나의 타입 컬럼만 채워지도록 강제
        CheckConstraint(
            "(value_text IS NOT NULL)::int + "
            "(value_int  IS NOT NULL)::int + "
            "(value_bool IS NOT NULL)::int + "
            "(value_date IS NOT NULL)::int + "
            "(value_json IS NOT NULL)::int = 1",
            name="ck_optionitem_exactly_one_value",
        ),

        # 부분 유니크 인덱스(타입별)
        Index(
            "uq_optionitem_group_value_text",
            "group_key", "value_text",
            unique=True,
            postgresql_where=text("value_text IS NOT NULL"),
        ),
        Index(
            "uq_optionitem_group_value_int",
            "group_key", "value_int",
            unique=True,
            postgresql_where=text("value_int IS NOT NULL"),
        ),
        Index(
            "uq_optionitem_group_value_bool",
            "group_key", "value_bool",
            unique=True,
            postgresql_where=text("value_bool IS NOT NULL"),
        ),
        Index(
            "uq_optionitem_group_value_date",
            "group_key", "value_date",
            unique=True,
            postgresql_where=text("value_date IS NOT NULL"),
        ),
        Index(
            "uq_optionitem_group_value_json",
            "group_key", "value_json",
            unique=True,
            postgresql_where=text("value_json IS NOT NULL"),
        ),
    )

    group: Mapped["OptionGroup"] = relationship(back_populates="items")


class OptionGroup(Base):
    """
    옵션 묶음 (예: degree, admission_year, admission_type …)
    - value_type: 이 그룹의 항목들이 가질 값 타입 정의 (string/int/bool/date/json)
    """
    __tablename__ = "optiongroup"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)  # 예: "degree", "admission_year"
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 이 그룹이 어떤 타입의 값을 쓸지 명시
    value_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'string'")
    )

    __table_args__ = (
        Index("ix_optiongroup_title", "title"),
        CheckConstraint(
            "value_type IN ('string','int','bool','date','json')",
            name="ck_optiongroup_value_type",
        ),
    )

    items: Mapped[List["OptionItem"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="OptionItem.order",
    )

# ─────────────────────────────────────────────────────────────────────────────
# 관리자 계정 관리 테이블
# ─────────────────────────────────────────────────────────────────────────────
class AdminAccount(Base):
    """
    관리자 계정 관리 테이블
    - 로그인용 아이디 / 해시된 비밀번호 / 이름만 관리
    - 관리자 테이블은 단순 인증 목적으로 사용
    """
    __tablename__ = "adminaccount"
    __table_args__ = ()

    # --- 기본정보 ---
    admin_id: Mapped[str] = mapped_column(String(20), primary_key=True, nullable=False)   # 아이디 (PK)
    admin_hash: Mapped[str] = mapped_column(String(255), nullable=False)                   # 비밀번호 해시
    user_name: Mapped[str] = mapped_column(String(100), nullable=False)                    # 관리자명

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
