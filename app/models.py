from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, UniqueConstraint
from passlib.hash import bcrypt
from sqlmodel import SQLModel, Field, Column, Integer, ForeignKey

class User(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("username", name="uq_user_username"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, description="로그인 아이디")
    password_hash: str
    role: str = Field(default="student")
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

    def set_password(self, raw: str):
        self.password_hash = bcrypt.hash(raw)

    def verify_password(self, raw: str) -> bool:
        try:
            return bcrypt.verify(raw, self.password_hash)
        except Exception:
            return False

class StudentProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # User와 1:1 매핑 (user.id 고유)
    user_id: int = Field(sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False))
    name: Optional[str] = Field(default=None, description="이름")
    student_no: Optional[str] = Field(default=None, description="학번")
    college: Optional[str] = Field(default=None, description="대학")
    department: Optional[str] = Field(default=None, description="학과")
    certification_track: Optional[str] = Field(default=None, description="인증제")
    extracurricular_programs: Optional[str] = Field(default=None, description="비교과 프로그램(쉼표로 구분)")
    consortium_curriculum_status: Optional[str] = Field(default=None, description="사업단 교육과정 이수현황")

class CurriculumTrack(SQLModel, table=True):   # 교과인증과정
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None

class Certification(SQLModel, table=True):     # 인증제
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None

class ExtracurricularProgram(SQLModel, table=True):  # 비교과 프로그램
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None