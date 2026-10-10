import hmac
import json
import logging
import os
import re
import threading
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
 
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
 
VERSION = "v5.0.0"
MAX_TODOS = 500                                  # [A04] 항목 수 상한: 무제한으로 쌓여 파일이 커지는 것을 막는다
DATE_FORMAT = re.compile(r"\d{4}-\d{2}-\d{2}")   # fromisoformat 은 "20261231" 같은 다른 형식도 받아서 먼저 거른다
 
BASE_DIR = Path(__file__).resolve().parent       # main.py 가 있는 폴더
TODO_FILE = BASE_DIR / "todo.json"
INDEX_FILE = BASE_DIR / "templates" / "index.html"
STATIC_DIR = BASE_DIR / "static"
 
# [A05] 화면(HTML)에 붙이는 콘텐츠 보안 정책: 같은 출처의 스크립트와 스타일만 실행한다.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
 
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("todo")
 
_lock = threading.Lock()                         # [A04] 읽기 → 수정 → 쓰기를 한 번에 하나만 실행한다
 
if not TODO_FILE.exists():                       # 없으면 빈 목록으로 만들어 둔다
    TODO_FILE.write_text("[]", encoding="utf-8")
 
# [A05] 운영에서는 API 문서(/docs)를 기본으로 닫아 둔다. 필요할 때만 ENABLE_DOCS=1 로 연다.
DOCS_ON = os.environ.get("ENABLE_DOCS") == "1"
app = FastAPI(
    title="To-Do List API",
    version=VERSION,
    docs_url="/docs" if DOCS_ON else None,
    redoc_url="/redoc" if DOCS_ON else None,
    openapi_url="/openapi.json" if DOCS_ON else None,
)
 
# 오류 응답을 API 문서에 명시한다 (HTTPException 이 던지는 상태 코드).
# 정적 분석 도구가 읽을 수 있도록 ** 병합 없이 경로별로 리터럴 딕셔너리를 따로 둔다.
RESPONSES_READ = {
    401: {"description": "API 키가 없거나 올바르지 않음"},
    500: {"description": "저장된 데이터를 읽을 수 없음"},
}
RESPONSES_CREATE = {
    401: {"description": "API 키가 없거나 올바르지 않음"},
    409: {"description": "할 일 개수 한도 초과"},
    500: {"description": "저장된 데이터를 읽을 수 없음"},
}
RESPONSES_CHANGE = {
    401: {"description": "API 키가 없거나 올바르지 않음"},
    404: {"description": "To-Do item not found"},
    500: {"description": "저장된 데이터를 읽을 수 없음"},
}
 
 
def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
 
 
def require_api_key(request: Request, x_api_key: Annotated[str | None, Header()] = None) -> None:
    """[A01/A07] 환경변수 TODO_API_KEY 가 설정돼 있으면 모든 /todos 요청에 X-API-Key 헤더를 요구한다.
    설정하지 않으면 예전처럼 열려 있다 (기존 배포가 깨지지 않도록)."""
    expected = os.environ.get("TODO_API_KEY", "")
    if not expected:
        return
    if x_api_key is None or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        logger.warning("auth failed | method=%s | ip=%s", request.method, client_ip(request))
        raise HTTPException(401, "유효한 API 키가 필요합니다", headers={"WWW-Authenticate": "ApiKey"})
 
 
AUTH = [Depends(require_api_key)]
 
 
class TodoIn(BaseModel):                         # 클라이언트가 보내는 데이터 (id 없음)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)      # [A04] 길이 제한
    completed: bool = False
    due_date: str = ""                           # 마감일 "YYYY-MM-DD", 없으면 빈 문자열
    priority: Literal["high", "normal", "low"] = "normal"
 
    @field_validator("due_date")
    @classmethod
    def check_due_date(cls, value: str) -> str:  # [A04] 형식이 틀린 날짜는 저장하지 않는다
        if value:
            if not DATE_FORMAT.fullmatch(value):
                raise ValueError("due_date 는 YYYY-MM-DD 형식이어야 합니다")
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("존재하지 않는 날짜입니다") from exc
        return value
 
 
class TodoItem(TodoIn):                          # 서버가 돌려주는 데이터 (id 있음)
    id: int
 
 
def load_todos() -> list[TodoItem]:
    try:
        raw = TODO_FILE.read_text(encoding="utf-8") if TODO_FILE.exists() else "[]"
        return [TodoItem(**t) for t in json.loads(raw)]
    except (ValueError, TypeError) as exc:       # JSON 손상, 형식 불일치 (둘 다 ValueError 계열)
        logger.exception("todo.json 을 읽지 못했습니다")      # [A09] 원인을 기록한다
        raise HTTPException(500, "저장된 데이터를 읽을 수 없습니다") from exc
 
 
def save_todos(todos: list[TodoItem]) -> None:
    data = json.dumps([t.model_dump() for t in todos], indent=2, ensure_ascii=False)
    tmp = TODO_FILE.with_name(TODO_FILE.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, TODO_FILE)                   # [A04] 임시 파일에 쓴 뒤 교체: 쓰다가 끊겨도 원본이 깨지지 않는다
 
 
def find_index(todos: list[TodoItem], todo_id: int) -> int:
    for i, todo in enumerate(todos):
        if todo.id == todo_id:
            return i
    raise HTTPException(404, "To-Do item not found")
 
 
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"      # [A05] 브라우저가 타입을 추측하지 못하게
    response.headers["X-Frame-Options"] = "DENY"                # 다른 사이트의 iframe 에 끼워 넣기 금지
    response.headers["Referrer-Policy"] = "no-referrer"
    path = request.url.path
    if path.startswith("/todos"):
        response.headers["Cache-Control"] = "no-store"          # 할 일 데이터는 캐시하지 않는다
    elif path.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache"          # 배포 후 항상 새 파일인지 확인한다
    return response
 
 
@app.get("/todos", dependencies=AUTH, responses=RESPONSES_READ)               # 목록 조회
def get_todos() -> list[TodoItem]:
    return load_todos()
 
 
@app.post("/todos", status_code=201, dependencies=AUTH,
          responses=RESPONSES_CREATE)                                         # 추가 — id 는 서버가 매긴다
def create_todo(payload: TodoIn, request: Request) -> TodoItem:
    with _lock:
        todos = load_todos()
        if len(todos) >= MAX_TODOS:
            raise HTTPException(409, f"할 일은 최대 {MAX_TODOS}개까지 만들 수 있습니다")
        new_id = max((t.id for t in todos), default=0) + 1
        todo = TodoItem(id=new_id, **payload.model_dump())
        save_todos([*todos, todo])
    logger.info("create | id=%s | ip=%s", todo.id, client_ip(request))     # [A09] 제목은 기록하지 않는다
    return todo
 
 
@app.put("/todos/{todo_id}", dependencies=AUTH,
         responses=RESPONSES_CHANGE)                                          # 수정
def update_todo(todo_id: int, payload: TodoIn, request: Request) -> TodoItem:
    with _lock:
        todos = load_todos()
        index = find_index(todos, todo_id)
        todo = TodoItem(id=todo_id, **payload.model_dump())
        todos[index] = todo
        save_todos(todos)
    logger.info("update | id=%s | ip=%s", todo_id, client_ip(request))
    return todo
 
 
@app.delete("/todos/{todo_id}", status_code=204, dependencies=AUTH,
            responses=RESPONSES_CHANGE)                                       # 삭제
def delete_todo(todo_id: int, request: Request) -> None:
    with _lock:
        todos = load_todos()
        del todos[find_index(todos, todo_id)]
        save_todos(todos)
    logger.info("delete | id=%s | ip=%s", todo_id, client_ip(request))
 
 
@app.get("/health", include_in_schema=False)     # Docker HEALTHCHECK 와 모니터링용 (인증 없음, 데이터 없음)
def health() -> dict:
    return {"status": "ok", "version": VERSION}
 
 
@app.get("/version", include_in_schema=False)    # 화면 하단 버전 표시용
def get_version() -> dict:
    return {"version": VERSION}
 
 
@app.get("/", include_in_schema=False)           # 화면 서빙
def read_root() -> FileResponse:
    return FileResponse(INDEX_FILE, media_type="text/html",
                        headers={"Content-Security-Policy": CSP, "Cache-Control": "no-cache"})
 
 
app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")
 