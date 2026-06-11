# KMLA 통합 시스템

민족사관고등학교(KMLA) 업무 및 수업 자동화 통합 대시보드

## 기능

- 🔐 로그인 시스템 (초기 계정: admin/admin1234)
- 🔑 비밀번호 변경
- 📊 업무 자동화 시스템
  - 자동 발송 시스템
- 📚 수업(한국사) 자동화 시스템 (준비 중)

## 로컬 실행

```bash
pip install -r requirements.txt
python app.py
```

http://localhost:5001 에서 접속

## 배포 (Render)

1. GitHub 저장소 생성 및 푸시
2. Render에서 New Web Service 선택
3. 저장소 연결
4. 환경 변수 설정:
   - `FLASK_SECRET_KEY`: 랜덤한 비밀 키

## 초기 계정

- 아이디: `admin`
- 비밀번호: `admin1234`

로그인 후 반드시 비밀번호를 변경하세요.
