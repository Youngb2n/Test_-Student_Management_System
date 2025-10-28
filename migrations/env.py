# migrations/env.py
import os, sys
from logging.config import fileConfig
from dotenv import load_dotenv
from alembic import context
from sqlalchemy import create_engine, pool

# ── Alembic 기본 설정 로드 ─────────────────────────────
config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

# ── .env 로드 ─────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# ── 앱 패스 추가 & 모델 import (Declarative Base) ─────
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from app.models import Base  # ← Declarative Base
target_metadata = Base.metadata

# ── DB URL 구성 ───────────────────────────────────────
DB_URL = os.getenv("DATABASE_URL_MIGRATIONS") or os.getenv("DATABASE_URL")
if not DB_URL:
    DB_URL = "sqlite:///./app/app.db"  # 로컬 폴백(선택)

CONNECT_ARGS = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {"prepare_threshold": 0}
ENGINE_KW = dict(poolclass=pool.NullPool, pool_pre_ping=True, connect_args=CONNECT_ARGS, future=True)

# ── Offline 모드 ──────────────────────────────────────
def run_migrations_offline():
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

# ── Online 모드 ───────────────────────────────────────
def run_migrations_online():
    connectable = create_engine(DB_URL, **ENGINE_KW)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()

# ── 진입점 ────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
