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
    name: str
    student_no: str
    college: Optional[str] = None
    department: Optional[str] = None
    # certification_track: str | None = None
    # extracurricular_programs: str | None = None
    # consortium_curriculum_status: str | None = None

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