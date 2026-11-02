import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

import main
from main import app, save_todos, load_todos, TodoItem

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_and_teardown(tmp_path, monkeypatch):
    # 실제 todo.json 대신 테스트마다 새 임시 파일 사용 (본인 데이터 보호 + 테스트 간 격리)
    # TODO_FILE 은 본인 main.py의 파일 경로 변수명에 맞게 수정 (Path 객체 그대로 넘김, str()로 감싸지 않음)
    monkeypatch.setattr(main, "TODO_FILE", tmp_path / "todo.json")
    monkeypatch.delenv("TODO_API_KEY", raising=False)   # 테스트는 기본적으로 인증 없이 시작한다
    save_todos([])  # 테스트 전 초기화 (정리는 tmp_path 와 monkeypatch 가 자동으로 원상 복구)

def test_get_todos_empty():
    response = client.get("/todos")
    assert response.status_code == 200
    assert response.json() == []

def test_get_todos_with_items():
    todo = TodoItem(id=1, title="Test", description="Test description", completed=False)
    save_todos([todo])  # save_todos 는 TodoItem 객체 리스트를 받음
    response = client.get("/todos")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["title"] == "Test"

def test_create_todo():
    todo = {"title": "Test", "description": "Test description", "completed": False}  # id 는 보내지 않음
    response = client.post("/todos", json=todo)
    assert response.status_code == 201           # 생성 성공 = 201 Created
    assert response.json()["title"] == "Test"
    assert response.json()["id"] == 1            # id 는 서버가 부여
    assert len(load_todos()) == 1                # 파일에도 저장됐는지 확인

def test_create_todo_invalid():
    todo = {"description": "Test description"}   # 필수 필드 title 누락
    response = client.post("/todos", json=todo)
    assert response.status_code == 422

def test_update_todo():
    todo = TodoItem(id=1, title="Test", description="Test description", completed=False)
    save_todos([todo])
    updated_todo = {"title": "Updated", "description": "Updated description", "completed": True}
    response = client.put("/todos/1", json=updated_todo)
    assert response.status_code == 200
    assert response.json()["title"] == "Updated"

def test_update_todo_not_found():
    updated_todo = {"title": "Updated", "description": "Updated description", "completed": True}
    response = client.put("/todos/1", json=updated_todo)
    assert response.status_code == 404

def test_delete_todo():
    todo = TodoItem(id=1, title="Test", description="Test description", completed=False)
    save_todos([todo])
    response = client.delete("/todos/1")
    assert response.status_code == 204           # 삭제 성공 = 204 No Content (응답 본문 없음)
    assert load_todos() == []

def test_delete_todo_not_found():
    response = client.delete("/todos/1")
    assert response.status_code == 404


# ---------- v3.0.0: 우선순위 / 마감일 / 버전 ----------

def test_create_todo_default_priority():
    response = client.post("/todos", json={"title": "Test"})
    assert response.status_code == 201
    assert response.json()["priority"] == "normal"

@pytest.mark.parametrize("priority", ["high", "normal", "low"])
def test_create_todo_with_priority(priority):
    response = client.post("/todos", json={"title": "Test", "priority": priority})
    assert response.status_code == 201
    assert response.json()["priority"] == priority
    assert load_todos()[0].priority == priority

def test_create_todo_invalid_priority():
    response = client.post("/todos", json={"title": "Test", "priority": "urgent"})
    assert response.status_code == 422

def test_update_todo_priority():
    save_todos([TodoItem(id=1, title="Test", priority="low")])
    response = client.put("/todos/1", json={"title": "Test", "priority": "high"})
    assert response.status_code == 200
    assert response.json()["priority"] == "high"
    assert load_todos()[0].priority == "high"

def test_load_old_data_without_priority():
    # v3.0.0 이전에 저장된 todo.json(priority 없음)도 정상적으로 읽혀야 한다
    old = [{"id": 1, "title": "Old", "description": "", "completed": False}]
    main.TODO_FILE.write_text(json.dumps(old), encoding="utf-8")
    response = client.get("/todos")
    assert response.status_code == 200
    assert response.json()[0]["priority"] == "normal"
    assert response.json()[0]["due_date"] == ""

def test_create_todo_with_due_date():
    response = client.post("/todos", json={"title": "Test", "due_date": "2026-12-31"})
    assert response.status_code == 201
    assert response.json()["due_date"] == "2026-12-31"

def test_get_version():
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": main.VERSION}


# ---------- v5.0.0 [A04] 입력 제한 · 저장 안정성 ----------

def test_description_length_limit():
    assert client.post("/todos", json={"title": "t", "description": "a" * 500}).status_code == 201
    assert client.post("/todos", json={"title": "t", "description": "a" * 501}).status_code == 422

@pytest.mark.parametrize("bad_date", ["2026-13-45", "20261231", "2026-1-5", "abc", "2026-02-30"])
def test_invalid_due_date_rejected(bad_date):
    response = client.post("/todos", json={"title": "t", "due_date": bad_date})
    assert response.status_code == 422

def test_empty_due_date_allowed():
    assert client.post("/todos", json={"title": "t", "due_date": ""}).status_code == 201

def test_todo_count_limit(monkeypatch):
    monkeypatch.setattr(main, "MAX_TODOS", 2)
    assert client.post("/todos", json={"title": "1"}).status_code == 201
    assert client.post("/todos", json={"title": "2"}).status_code == 201
    response = client.post("/todos", json={"title": "3"})
    assert response.status_code == 409
    assert "최대 2개" in response.json()["detail"]
    assert len(load_todos()) == 2

def test_save_leaves_no_temp_file():
    client.post("/todos", json={"title": "t"})
    assert main.TODO_FILE.exists()
    assert not main.TODO_FILE.with_name("todo.json.tmp").exists()

def test_concurrent_creates_keep_unique_ids():
    # 동시에 20개를 추가해도 id 가 겹치거나 유실되지 않아야 한다 (잠금 검증)
    def create(n):
        return TestClient(app).post("/todos", json={"title": f"t{n}"}).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(create, range(20)))
    assert statuses == [201] * 20
    ids = [t.id for t in load_todos()]
    assert len(ids) == 20
    assert sorted(ids) == list(range(1, 21))

def test_corrupted_file_returns_500_and_logs(caplog):
    main.TODO_FILE.write_text("{ 깨진 json", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger="todo"):
        response = client.get("/todos")
    assert response.status_code == 500
    assert "읽을 수 없습니다" in response.json()["detail"]
    assert any("todo.json" in r.getMessage() for r in caplog.records)

def test_wrong_shape_file_returns_500():
    main.TODO_FILE.write_text(json.dumps([{"id": 1}]), encoding="utf-8")   # title 이 없는 항목
    assert client.get("/todos").status_code == 500


# ---------- v5.0.0 [A01/A07] API 키 인증 ----------

def test_open_when_no_key_configured():
    assert client.get("/todos").status_code == 200       # 키를 설정하지 않으면 기존처럼 열려 있다

def test_auth_required_when_key_configured(monkeypatch):
    monkeypatch.setenv("TODO_API_KEY", "s3cret")
    response = client.get("/todos")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "ApiKey"

def test_wrong_key_rejected(monkeypatch):
    monkeypatch.setenv("TODO_API_KEY", "s3cret")
    assert client.get("/todos", headers={"X-API-Key": "wrong"}).status_code == 401

def test_correct_key_accepted_for_all_methods(monkeypatch):
    monkeypatch.setenv("TODO_API_KEY", "s3cret")
    headers = {"X-API-Key": "s3cret"}
    created = client.post("/todos", json={"title": "t"}, headers=headers)
    assert created.status_code == 201
    todo_id = created.json()["id"]
    assert client.get("/todos", headers=headers).status_code == 200
    assert client.put(f"/todos/{todo_id}", json={"title": "u"}, headers=headers).status_code == 200
    assert client.delete(f"/todos/{todo_id}", headers=headers).status_code == 204

def test_write_methods_blocked_without_key(monkeypatch):
    monkeypatch.setenv("TODO_API_KEY", "s3cret")
    assert client.post("/todos", json={"title": "t"}).status_code == 401
    assert client.put("/todos/1", json={"title": "t"}).status_code == 401
    assert client.delete("/todos/1").status_code == 401
    assert load_todos() == []                            # 거부된 요청은 데이터를 바꾸지 못한다

def test_public_pages_stay_open_with_key(monkeypatch):
    monkeypatch.setenv("TODO_API_KEY", "s3cret")
    for path in ("/", "/version", "/health", "/static/app.js"):
        assert client.get(path).status_code == 200, path

def test_auth_failure_is_logged_without_key_value(monkeypatch, caplog):
    monkeypatch.setenv("TODO_API_KEY", "s3cret")
    with caplog.at_level(logging.WARNING, logger="todo"):
        client.get("/todos", headers={"X-API-Key": "guess123"})
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "auth failed" in text
    assert "guess123" not in text
    assert "s3cret" not in text


# ---------- v5.0.0 [A09] 감사 로그 ----------

def test_changes_are_logged_without_title(caplog):
    with caplog.at_level(logging.INFO, logger="todo"):
        todo_id = client.post("/todos", json={"title": "비밀 제목"}).json()["id"]
        client.put(f"/todos/{todo_id}", json={"title": "바뀐 제목"})
        client.delete(f"/todos/{todo_id}")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert f"create | id={todo_id}" in text
    assert f"update | id={todo_id}" in text
    assert f"delete | id={todo_id}" in text
    assert "비밀 제목" not in text   # 사용자 입력은 로그에 남기지 않는다
    assert "바뀐 제목" not in text


# ---------- v5.0.0 [A05] 보안 헤더 · 화면 · 문서 ----------

def test_security_headers_on_every_response():
    for path in ("/", "/todos", "/version", "/health"):
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff", path
        assert headers["x-frame-options"] == "DENY", path
        assert headers["referrer-policy"] == "no-referrer", path

def test_page_has_strict_csp():
    csp = client.get("/").headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert "frame-ancestors 'none'" in csp

def test_cache_headers():
    assert client.get("/todos").headers["cache-control"] == "no-store"
    assert client.get("/static/app.js").headers["cache-control"] == "no-cache"

def test_page_has_no_inline_script_or_style():
    # 엄격한 CSP 를 쓰려면 HTML 안에 인라인 스크립트/스타일/이벤트 속성이 없어야 한다
    html = main.INDEX_FILE.read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "인라인 <script>"
    assert "<style" not in html, "인라인 <style>"
    assert not re.search(r"\sstyle\s*=", html), "style 속성"
    assert not re.search(r"\son[a-z]+\s*=", html), "onclick 같은 이벤트 속성"

def test_static_assets_served():
    js = client.get("/static/app.js")
    css = client.get("/static/app.css")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
    assert css.status_code == 200
    assert "css" in css.headers["content-type"]

def test_api_docs_closed_by_default():
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": main.VERSION}

def test_openapi_documents_error_responses():
    spec = app.openapi()
    assert "404" in spec["paths"]["/todos/{todo_id}"]["put"]["responses"]
    assert "409" in spec["paths"]["/todos"]["post"]["responses"]
    assert "401" in spec["paths"]["/todos"]["get"]["responses"]
    for method in ("get", "post"):
        assert "500" in spec["paths"]["/todos"][method]["responses"]
    for method in ("put", "delete"):
        assert "500" in spec["paths"]["/todos/{todo_id}"][method]["responses"]


# ---------- v5.0.0 Prometheus 메트릭 ----------

def test_metrics_endpoint_exposes_request_counts():
    client.get("/todos")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text

def test_metrics_group_paths_by_route_template():
    # /todos/12345 같은 개별 주소가 지표 이름으로 쌓이면 안 된다 (지표 폭증 방지)
    client.delete("/todos/12345")
    text = client.get("/metrics").text
    assert 'handler="/todos/{todo_id}"' in text
    assert "/todos/12345" not in text

def test_metrics_do_not_contain_todo_data():
    client.post("/todos", json={"title": "지표에 나오면 안 되는 제목"})
    assert "지표에 나오면 안 되는 제목" not in client.get("/metrics").text

def test_metrics_stay_open_when_api_key_is_set(monkeypatch):
    # Prometheus 가 키 없이 수집할 수 있도록 의도적으로 열어 둔다 (/todos 데이터는 계속 보호됨)
    monkeypatch.setenv("TODO_API_KEY", "s3cret")
    assert client.get("/metrics").status_code == 200
    assert client.get("/todos").status_code == 401

def test_metrics_carry_security_headers():
    headers = client.get("/metrics").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"


# ---------- v6.0.0 관측: 업무 지표 ----------

def sample(name, labels=None):
    """기본 레지스트리에서 지표 값 하나를 읽는다 (/metrics 가 내보내는 값과 같은 값)."""
    return REGISTRY.get_sample_value(name, labels or {})


def test_business_metrics_are_exposed():
    text = client.get("/metrics").text
    for name in ("todo_store_readable", "todo_items", "todo_open_items", "todo_capacity_ratio", "todo_build_info"):
        assert name in text, name

def test_build_info_reports_version():
    assert sample("todo_build_info", {"version": main.VERSION}) == 1.0

def test_items_metric_counts_each_state():
    save_todos([
        TodoItem(id=1, title="a", completed=True),
        TodoItem(id=2, title="b", due_date="2000-01-01"),      # 기한이 지났고 미완료 → overdue
        TodoItem(id=3, title="c", due_date="2999-12-31"),      # 기한이 남음 → active
        TodoItem(id=4, title="d"),                             # 기한 없음 → active
    ])
    assert sample("todo_items", {"state": "completed"}) == 1.0
    assert sample("todo_items", {"state": "overdue"}) == 1.0
    assert sample("todo_items", {"state": "active"}) == 2.0

def test_completed_item_is_never_overdue():
    save_todos([TodoItem(id=1, title="a", completed=True, due_date="2000-01-01")])
    assert sample("todo_items", {"state": "completed"}) == 1.0
    assert sample("todo_items", {"state": "overdue"}) == 0.0

def test_open_items_by_priority_ignores_completed():
    save_todos([
        TodoItem(id=1, title="a", priority="high"),
        TodoItem(id=2, title="b", priority="high"),
        TodoItem(id=3, title="c", priority="normal"),
        TodoItem(id=4, title="d", priority="high", completed=True),
    ])
    assert sample("todo_open_items", {"priority": "high"}) == 2.0
    assert sample("todo_open_items", {"priority": "normal"}) == 1.0
    assert sample("todo_open_items", {"priority": "low"}) == 0.0

def test_capacity_ratio(monkeypatch):
    monkeypatch.setattr(main, "MAX_TODOS", 4)
    save_todos([TodoItem(id=1, title="a")])
    assert sample("todo_capacity_ratio") == 0.25

def test_store_is_readable_when_healthy():
    assert sample("todo_store_readable") == 1.0

def test_unreadable_store_is_reported_without_breaking_metrics():
    main.TODO_FILE.write_text("{ 깨진 json", encoding="utf-8")
    response = client.get("/metrics")
    assert response.status_code == 200                 # 수집은 계속 돼야 알림이 울린다
    assert sample("todo_store_readable") == 0.0
    assert sample("todo_items", {"state": "active"}) is None


# ---------- v6.0.0 관측: 작업 카운터 ----------

def test_operation_series_exist_before_any_request():
    for operation in ("create", "update", "delete"):
        assert sample("todo_operations_total", {"operation": operation}) is not None, operation

def test_successful_operations_are_counted():
    before = {op: sample("todo_operations_total", {"operation": op}) for op in ("create", "update", "delete")}
    todo_id = client.post("/todos", json={"title": "t"}).json()["id"]
    client.put(f"/todos/{todo_id}", json={"title": "u"})
    client.delete(f"/todos/{todo_id}")
    for operation, value in before.items():
        assert sample("todo_operations_total", {"operation": operation}) == value + 1, operation

def test_failed_operations_are_not_counted():
    before = sample("todo_operations_total", {"operation": "update"})
    assert client.put("/todos/999", json={"title": "x"}).status_code == 404
    assert sample("todo_operations_total", {"operation": "update"}) == before

def test_auth_failures_are_counted(monkeypatch):
    monkeypatch.setenv("TODO_API_KEY", "s3cret")
    before = sample("todo_auth_failures_total")
    client.get("/todos", headers={"X-API-Key": "wrong"})
    assert sample("todo_auth_failures_total") == before + 1

def test_limit_rejections_are_counted(monkeypatch):
    monkeypatch.setattr(main, "MAX_TODOS", 1)
    rejections = sample("todo_limit_rejections_total")
    creates = sample("todo_operations_total", {"operation": "create"})
    assert client.post("/todos", json={"title": "1"}).status_code == 201
    assert client.post("/todos", json={"title": "2"}).status_code == 409
    assert sample("todo_limit_rejections_total") == rejections + 1
    assert sample("todo_operations_total", {"operation": "create"}) == creates + 1
