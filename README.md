# SMS FastAPI + Supabase Login (DB-backed)

- Supabase(Postgres) 연결: `.env`의 `DATABASE_URL` 사용
- 로그인 처리: `/login` POST (bcrypt 검증) → 세션 쿠키
- 현재 화면: `/` (학생/관리자 탭 로그인)

## 실행
```bash
pip install -r requirements.txt
python -m app.seed_admin --username admin --password admin123 --role admin
uvicorn app.main:app --reload --port 8000
