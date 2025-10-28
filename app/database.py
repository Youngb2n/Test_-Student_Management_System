import os
from sqlmodel import create_engine, Session
from dotenv import load_dotenv

# load env only once
load_dotenv()

# runtime pooler URL (transaction pooler @ 6543)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/postgres"
)

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

# set pool_pre_ping True to avoid stale prepared statements,
# autocommit off (default), expire_on_commit False so objects usable after commit
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=False,
)

def get_session():
    with Session(engine, expire_on_commit=False) as session:
        yield session
