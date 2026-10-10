# Python 3.13 slim 베이스 이미지 (3.9는 2025-10 지원 종료, 최신 FastAPI는 Python 3.10 이상 필요)
FROM python:3.13-slim

# .pyc 생성 안 함 / 로그 즉시 출력 / pip 캐시·버전체크 끄기
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# root가 아닌 실행 전용 사용자 생성
RUN useradd --create-home --uid 10001 appuser \
 && mkdir /app && chown appuser:appuser /app

# 작업 디렉토리 설정
WORKDIR /app

# [A06] 운영 이미지에는 실행에 필요한 패키지만, 버전을 고정해서 설치한다 (테스트 도구 제외)
# 의존성 먼저 설치 (코드만 바뀌면 이 단계는 캐시 재사용 → 빌드가 빨라짐)
COPY requirements-prod.txt .
RUN pip install -r requirements-prod.txt

# 소스 복사: 실행에 필요한 파일만, root 소유(읽기 전용)로 둔다
# todo.json 은 /app 폴더가 appuser 소유라서 실행 중 appuser 가 직접 만든다
COPY main.py .
COPY templates ./templates
COPY static ./static

# 이후 명령은 appuser 권한으로 실행
USER appuser

EXPOSE 8000

# [A09] 컨테이너 상태 점검: /health 가 응답하지 않으면 unhealthy 로 표시된다 (slim 이미지에는 curl 이 없어 python 사용)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

# FastAPI 서버 실행
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
