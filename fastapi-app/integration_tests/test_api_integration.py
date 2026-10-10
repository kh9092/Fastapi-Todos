"""통합 테스트: 배포된 서버(BASE_URL)에 실제 HTTP 요청을 보내 API 흐름을 검증한다.

실행 예:
    BASE_URL=http://163.239.77.77:5053 python -m pytest integration_tests -v

BASE_URL 을 지정하지 않으면 로컬(http://localhost:8000)을 대상으로 한다.
서버에 접근 키(TODO_API_KEY)를 설정했다면 API_KEY 환경변수에 같은 값을 넣어 실행한다:
    API_KEY=키 BASE_URL=http://163.239.77.77:5053 python -m pytest integration_tests -v
requests 같은 추가 패키지 없이 파이썬 표준 라이브러리(urllib)만 사용한다.
"""
import json
import os
import time
import urllib.error
import urllib.request
import uuid

import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")


def call(method, path, body=None):
    """서버에 요청을 보내고 (상태코드, 응답 JSON) 을 돌려준다. 4xx/5xx 도 예외 없이 돌려준다."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    req = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            raw = res.read()
            return res.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, (json.loads(raw) if raw else None)
        except ValueError:
            return e.code, raw.decode("utf-8", errors="replace")


@pytest.fixture(scope="session", autouse=True)
def wait_for_server():
    """배포 직후에는 컨테이너가 아직 뜨는 중일 수 있으니, 최대 60초까지 응답을 기다린다."""
    deadline = time.time() + 60
    last_error = None
    while time.time() < deadline:
        try:
            status, _ = call("GET", "/todos")
            if status == 200:
                return
            if status == 401:               # 기다려도 해결되지 않으니 바로 이유를 알려준다
                pytest.fail("서버가 접근 키를 요구합니다. API_KEY 환경변수에 서버의 TODO_API_KEY 와 같은 값을 넣어 실행하세요.")
        except Exception as e:          # 연결 거부, 타임아웃 등
            last_error = e
        time.sleep(2)
    pytest.fail(f"서버가 응답하지 않습니다: {BASE_URL} ({last_error})")


@pytest.fixture
def created():
    """테스트 중 만든 항목의 id 를 모아 두었다가, 실패하더라도 끝나면 지워서 서버 데이터를 깨끗하게 유지한다."""
    ids = []
    yield ids
    for todo_id in ids:
        call("DELETE", f"/todos/{todo_id}")      # 이미 지워졌으면 404 가 나도 무시


def test_crud_flow(created):
    """추가(201) → 조회(200) → 수정(200) → 삭제(204) 흐름"""
    title = f"it-{uuid.uuid4().hex[:8]}"         # 다른 사람 데이터와 구분되는 고유 제목

    # 1. 추가 → 201
    status, body = call("POST", "/todos", {"title": title, "description": "integration test"})
    assert status == 201
    assert body["title"] == title
    todo_id = body["id"]
    created.append(todo_id)

    # 2. 조회 → 200, 방금 만든 항목이 목록에 있어야 한다
    status, body = call("GET", "/todos")
    assert status == 200
    assert any(t["id"] == todo_id and t["title"] == title for t in body)

    # 3. 수정 → 200, 바뀐 값이 응답과 이후 조회에 반영돼야 한다
    status, body = call("PUT", f"/todos/{todo_id}",
                        {"title": title + "-edited", "description": "updated", "completed": True})
    assert status == 200
    assert body["title"] == title + "-edited"
    assert body["completed"] is True

    status, body = call("GET", "/todos")
    assert any(t["id"] == todo_id and t["title"] == title + "-edited" for t in body)

    # 4. 삭제 → 204, 이후 목록에서 사라져야 한다
    status, _ = call("DELETE", f"/todos/{todo_id}")
    assert status == 204

    status, body = call("GET", "/todos")
    assert status == 200
    assert all(t["id"] != todo_id for t in body)


def test_create_without_title_returns_422():
    """필수 필드 title 없이 추가하면 422"""
    status, _ = call("POST", "/todos", {"description": "title is missing"})
    assert status == 422


def test_delete_nonexistent_returns_404():
    """없는 id 를 삭제하면 404"""
    status, _ = call("DELETE", "/todos/999999999")
    assert status == 404


# ---------- v5.0.0: 배포 환경의 보안 설정 확인 ----------

def get_headers(path):
    """응답 헤더만 확인한다 (키 없이 접근 가능한 경로에서만 사용)."""
    with urllib.request.urlopen(BASE_URL + path, timeout=10) as res:
        return res.status, {k.lower(): v for k, v in res.headers.items()}


def test_health_endpoint():
    """/health 는 인증 없이 응답하고, 데이터는 담지 않는다"""
    status, _ = get_headers("/health")
    assert status == 200


def test_security_headers_present():
    """배포된 서버가 보안 헤더를 붙이는지 확인한다"""
    status, headers = get_headers("/")
    assert status == 200
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "script-src 'self'" in headers["content-security-policy"]


def test_api_docs_not_exposed():
    """운영에서는 /docs 가 열려 있지 않아야 한다 (404)"""
    with pytest.raises(urllib.error.HTTPError) as err:
        get_headers("/docs")
    assert err.value.code == 404
