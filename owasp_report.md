# OWASP Top 10 (2021) 정적 분석 보고서 — Fastapi-Todos

- 분석 방식: 소스·설정 파일을 읽기만 하는 정적 분석. 코드 수정, 서버 요청, 컨테이너 실행, 빌드는 하지 않았습니다.
- 분석한 파일: `fastapi-app/main.py`, `fastapi-app/templates/index.html`, `fastapi-app/Dockerfile`, `fastapi-app/.dockerignore`, `docker-compose.yml`, `fastapi-app/requirements.txt`, `fastapi-app/pyproject.toml`, `fastapi-app/sonar-project.properties`, `fastapi-app/todo.json`, `.git/config`
- 표기 규칙: 코드에서 직접 확인한 내용만 사실로 적었습니다. 확인하지 못한 내용은 **(추측)** 으로 표시했습니다.
- 참고: 저장소에 `.gitignore`, `Jenkinsfile`, `.github/`, `.env*` 파일이 **없는 것으로 확인**했습니다 (Glob 검색 결과). `sonar-project.properties`는 루트가 아니라 `fastapi-app/` 안에 있습니다.

## 요약표

| 항목 | 해당 여부 | 심각도 |
|---|---|---|
| A01 접근 제어 취약점 | 해당 | 높음 |
| A02 암호화 실패 | 일부 해당 | 중간 |
| A03 인젝션 | 일부 해당 | 낮음 |
| A04 안전하지 않은 설계 | 해당 | 중간 |
| A05 보안 설정 오류 | 해당 | 중간 |
| A06 취약하고 오래된 구성요소 | 일부 해당 | 중간 |
| A07 식별 및 인증 실패 | 일부 해당 | 중간 |
| A08 소프트웨어 및 데이터 무결성 실패 | 일부 해당 | 낮음 |
| A09 보안 로깅 및 모니터링 실패 | 해당 | 중간 |
| A10 SSRF | 해당 없음 | - |

---

## A01: Broken Access Control (접근 제어 취약점)

| 항목 | 내용 |
|---|---|
| 해당 여부 | **해당** |
| 심각도 | **높음** |

**근거**
- `main.py:51-88`의 모든 엔드포인트(`GET/POST /todos`, `PUT/DELETE /todos/{todo_id}`, `/version`, `/`)에 인증·인가 의존성(`Depends`, 보안 스킴)이 없습니다. 접속할 수 있는 사람은 누구나 모든 할 일을 읽고 쓰고 삭제할 수 있습니다.
  ```python
  @app.delete("/todos/{todo_id}", status_code=204, responses=NOT_FOUND)  # main.py:74
  def delete_todo(todo_id: int) -> None:
  ```
- `docker-compose.yml:7-8`에서 `"5051:8000"`으로 포트를 호스트의 모든 인터페이스에 공개합니다. 같은 네트워크의 누구나 접근할 수 있습니다.
- `main.py:11-13`의 파일 경로는 고정 상수이고 `todo_id`는 `int`로 검증됩니다. 그래서 경로 조작(path traversal)은 확인되지 않았습니다.
- 사용자 개념이 없어서 객체 단위 권한(IDOR) 문제는 따로 없습니다. 모든 데이터가 한 목록에 공유됩니다.
- CORS 설정이 없습니다(`main.py`에 `CORSMiddleware` 없음). 그리고 JSON 본문 요청은 사전 요청(preflight)이 필요해서, 다른 사이트에서 오는 쓰기 요청은 기본적으로 브라우저가 막습니다. 다만 이 방어는 우연히 주어지는 것이고 인증을 대신하지는 않습니다.

**수정안**
1. 최소한 `docker-compose.yml`의 포트를 `"127.0.0.1:5051:8000"`으로 바꿔서 로컬에서만 접근하게 합니다. 외부에 공개해야 한다면 리버스 프록시에서 인증을 붙입니다.
2. 앱 수준에서는 FastAPI `Depends`로 인증을 요구합니다(API Key 헤더나 OAuth2/JWT). 여러 사용자를 지원할 계획이면 `TodoItem`에 `owner` 필드를 추가하고 조회·수정·삭제 때 소유자를 검사합니다.

---

## A02: Cryptographic Failures (암호화 실패)

| 항목 | 내용 |
|---|---|
| 해당 여부 | **일부 해당** |
| 심각도 | **중간** |

**근거**
- TLS 설정이 없습니다. `Dockerfile:31`은 `uvicorn ... --host 0.0.0.0 --port 8000`을 평문 HTTP로 실행하고, `docker-compose.yml`에도 HTTPS 종단 설정이 없습니다. 그래서 네트워크를 지나는 데이터가 평문입니다.
- `sonar-project.properties:12`의 `sonar.host.url=http://localhost:9000`도 평문 HTTP입니다. 로컬 주소이므로 위험은 제한적입니다.
- `main.py:39-41`은 할 일 데이터를 `todo.json`에 평문으로 저장합니다. 샘플 `todo.json:3-4`에는 학번처럼 보이는 값과 이름이 들어 있습니다. 개인정보라면 평문 저장이 문제가 될 수 있습니다.
- 비밀번호, 키, 토큰이 하드코딩된 곳은 확인되지 않았습니다. `sonar-project.properties:13`의 주석은 토큰을 파일에 적지 않는다고 명시합니다(좋은 점).
- 앱 자체는 해시·암호화 알고리즘을 쓰지 않아서 약한 알고리즘 문제는 해당 없습니다.

**수정안**
1. 외부에 공개한다면 Nginx, Caddy, Traefik 같은 리버스 프록시에서 TLS를 종단하고 HSTS 헤더를 추가합니다.
2. 개인정보를 `todo.json`에 넣지 않도록 합니다. 샘플 데이터는 가짜 값으로 바꾸거나 저장소에서 제외합니다. 민감한 데이터를 저장해야 한다면 DB와 저장소 암호화를 씁니다.

---

## A03: Injection (인젝션)

| 항목 | 내용 |
|---|---|
| 해당 여부 | **일부 해당** (직접적인 인젝션 경로는 확인되지 않았고, 방어가 약한 지점만 있음) |
| 심각도 | **낮음** |

**근거**
- SQL, OS 명령, 템플릿 엔진, `eval`/`exec`는 코드에서 쓰이지 않습니다. 저장은 `json.dumps` / `json.loads`뿐입니다(`main.py:36, 40`). 그래서 SQL 인젝션, 명령 인젝션, SSTI는 확인되지 않았습니다.
- XSS는 방어되어 있습니다. `index.html:392-393, 398, 400`은 사용자 입력을 `textContent`로 넣고, `innerHTML`은 쓰지 않습니다.
  ```js
  body.append(el("span", { className: "title", textContent: todo.title }));  // index.html:392
  ```
- 방어가 약한 지점
  - `index.html:426`은 서버에서 받은 `todo.priority`를 CSS 선택자 문자열에 그대로 끼워 넣습니다: `` `input[name="e-priority"][value="${todo.priority}"]` ``. 서버가 `Literal`로 검증해서(`main.py:27`) 현재는 안전합니다. 다만 `todo.json` 파일이 직접 변조되고 서버가 그 값을 읽는 경로가 생기면 선택자가 깨집니다(오류 수준이고 코드 실행은 아님).
  - `main.py:26`의 `due_date`는 형식 검증이 없는 `str`입니다. 임의 문자열이 저장됩니다. 화면에서는 `textContent`로 출력되어 실행은 되지 않습니다.
  - CSP 헤더가 없습니다. 인라인 `<script>`와 `<style>`이 있어서(`index.html:7, 318`) CSP를 강하게 걸기도 어렵습니다. XSS가 하나 생기면 완화해 줄 2차 방어선이 없다는 뜻입니다.

**수정안**
1. `due_date`를 `datetime.date` 타입(또는 정규식 패턴)으로 바꿔서 서버에서 형식을 검증합니다.
2. `index.html:426`은 선택자를 만들지 말고, `document.getElementById(`e-${todo.priority}`)`처럼 허용된 값만 매핑하는 방식으로 바꿉니다.
3. 가능하면 스크립트를 외부 파일로 분리하고 `Content-Security-Policy` 헤더를 추가합니다.

---

## A04: Insecure Design (안전하지 않은 설계)

| 항목 | 내용 |
|---|---|
| 해당 여부 | **해당** |
| 심각도 | **중간** |

**근거**
- **동시성 문제(레이스 컨디션).** 모든 변경 함수가 파일 전체를 읽고(`main.py:35`), 메모리에서 바꾸고, 전체를 다시 씁니다(`main.py:41`). 잠금이 없습니다. 엔드포인트가 `def`(동기 함수)라서 FastAPI가 스레드풀에서 동시에 실행합니다. 동시 요청이 오면 마지막 쓰기가 앞선 쓰기를 덮어써서 데이터가 사라질 수 있습니다. 같은 `new_id`가 두 번 발급될 수도 있습니다(`main.py:59`).
  ```python
  new_id = max((t.id for t in todos), default=0) + 1   # main.py:59
  ```
- **비원자적 저장.** `TODO_FILE.write_text`는 파일을 바로 덮어씁니다(`main.py:41`). 쓰는 도중 프로세스가 종료되면 `todo.json`이 깨질 수 있습니다. 깨진 파일은 `json.loads`에서 예외가 나서(`main.py:36`) 모든 API가 500을 반환하게 됩니다.
- **입력 크기 제한 누락.** `title`에는 `max_length=100`이 있지만(`main.py:23`), `description`에는 길이 제한이 없고(`main.py:24`) 항목 개수 제한도 없습니다. 큰 값을 반복해서 보내면 `todo.json`이 계속 커집니다. 매 요청마다 전체 파일을 읽고 쓰므로 응답이 느려집니다(자원 소진). 요청 빈도 제한(rate limit)도 없습니다.
- 삭제 후 id가 재사용될 수 있습니다. 마지막 항목을 지우면 `max + 1`이 같은 id를 다시 발급합니다(`main.py:59`). 단순 설계이며 보안 영향은 작습니다.
- `PUT`은 없는 id에 404를 반환하므로(`main.py:69`) 업서트 문제는 없습니다.

**수정안**
1. 쓰기 구간을 `threading.Lock`으로 감쌉니다(단일 프로세스일 때). 임시 파일에 쓴 뒤 `os.replace`로 교체해서 원자적으로 저장합니다. 장기적으로는 SQLite나 DB로 옮기는 것이 안전합니다.
2. `description`에 `max_length`(예: 500)를 지정하고, 목록 최대 개수와 요청 본문 크기 제한을 둡니다. 리버스 프록시나 `slowapi` 같은 라이브러리로 요청 빈도를 제한합니다.

---

## A05: Security Misconfiguration (보안 설정 오류)

| 항목 | 내용 |
|---|---|
| 해당 여부 | **해당** |
| 심각도 | **중간** |

**근거**
- **API 문서 노출.** `main.py:18`의 `FastAPI(title=..., version=...)`는 `docs_url`, `redoc_url`, `openapi_url`을 끄지 않아서 FastAPI 기본값인 `/docs`, `/redoc`, `/openapi.json`이 열려 있습니다(FastAPI 기본 동작 기준이며, 이 코드에서 비활성화한 곳은 없습니다). 인증이 없는 상태에서 API 구조가 그대로 드러납니다.
- **보안 헤더 없음.** `main.py`에 CSP, `X-Content-Type-Options`, `X-Frame-Options`, HSTS 등을 추가하는 미들웨어가 없습니다.
- **SonarQube 노출과 설정.**
  - `docker-compose.yml:19-20`: `"9000:9000"`이 모든 인터페이스에 공개됩니다.
  - SonarQube 기본 관리자 계정은 `admin/admin`으로 알려져 있습니다. 이 저장소에서 변경한 흔적은 확인되지 않았습니다. 실제로 변경했는지는 **(추측: 확인 불가)** 입니다.
  - `docker-compose.yml:22`: `SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true`는 Elasticsearch 부트스트랩 점검을 끕니다. 개발용 설정이며 운영에는 부적합합니다.
- **오류 메시지 노출.** `index.html:339, 349`는 서버 응답 본문(`res.text()`)을 그대로 화면에 표시합니다(`textContent`라서 XSS는 아님). 서버의 상세 오류가 사용자에게 보입니다.
- **좋은 점.**
  - `docker-compose.yml:10-13`: `no-new-privileges:true`, `cap_drop: ALL`
  - `Dockerfile:11-12, 26`: 비root 사용자(`uid 10001`)로 실행
  - `docker-compose.yml:18`: SonarQube를 `read_only: true`로 실행
  - `fastapi-app` 서비스에는 `read_only`가 없습니다. 하지만 `todo.json`을 컨테이너 안에 써야 해서 볼륨 없이는 적용하기 어렵습니다.
- `main.py:15-16`은 시작 시 `todo.json`이 없으면 만듭니다. 컨테이너 안의 파일을 쓰기 때문에 컨테이너를 재생성하면 데이터가 사라집니다(보안보다는 가용성 문제입니다. `docker-compose.yml`에 앱용 볼륨이 없는 것으로 확인했습니다).

**수정안**
1. 운영에서는 `FastAPI(..., docs_url=None, redoc_url=None, openapi_url=None)`로 문서를 끄거나, 인증 뒤로 옮깁니다.
2. 보안 헤더 미들웨어를 추가하고, 포트는 `127.0.0.1`에만 바인딩합니다(`"127.0.0.1:9000:9000"`).
3. SonarQube는 최초 로그인 후 관리자 비밀번호를 바꾸고, 운영에서는 ES 점검 비활성화 환경변수를 제거합니다. 서버 설정(`vm.max_map_count`)으로 해결하는 편이 맞습니다.
4. 클라이언트 오류 표시는 서버 본문 대신 일반 메시지로 바꿉니다.

---

## A06: Vulnerable and Outdated Components (취약하고 오래된 구성요소)

| 항목 | 내용 |
|---|---|
| 해당 여부 | **일부 해당** |
| 심각도 | **중간** |

**근거**
- `requirements.txt:1-7`은 전부 `>=` 하한만 지정합니다. 상한과 잠금 파일(lock file)이 없어서 빌드할 때마다 설치되는 버전이 달라질 수 있습니다(재현 불가능).
  ```
  fastapi>=0.142.0
  uvicorn[standard]>=0.54.0
  ```
- 테스트용 패키지(`pytest`, `pytest-cov`, `pytest-html`, `httpx2`)가 런타임 의존성과 같은 파일에 있고, `Dockerfile:18-19`가 이 파일 전체를 설치합니다. 운영 이미지에 불필요한 패키지가 들어가서 공격 표면이 늘어납니다.
- `requirements.txt:7`의 `httpx2`는 일반적으로 알려진 `httpx`와 다른 이름입니다. 주석은 "httpx는 deprecated"라고 설명하지만, 이 패키지가 공식 후속 패키지인지는 이 파일만으로 확인할 수 없습니다. **(추측: 패키지 출처 미확인. 오타 도용(typosquatting) 가능성도 점검할 필요가 있음)**
- 이 파일에 적힌 버전들이 실제로 존재하는지, 알려진 취약점이 있는지는 PyPI/CVE 데이터베이스를 조회하지 않았기 때문에 **(추측: 미확인)** 입니다. `requirements.txt:2, 4`의 주석은 CVE 패치 버전을 의식한 것으로 보입니다(좋은 점).
- `Dockerfile:2`의 `python:3.13-slim`은 가변 태그입니다. 패치 버전과 이미지 다이제스트가 고정되지 않았습니다. `docker-compose.yml:16`의 SonarQube 이미지는 버전이 고정되어 있습니다(좋은 점).
- 의존성 취약점 점검 도구(`pip-audit`, Dependabot 등) 설정은 저장소에서 확인되지 않았습니다.

**수정안**
1. 운영용(`requirements.txt`)과 개발·테스트용(`requirements-dev.txt`)을 분리합니다. `pip-compile`이나 `uv lock`으로 잠금 파일을 만들고 해시까지 고정합니다(`pip install --require-hashes`).
2. `pip-audit`을 CI에 넣고 Dependabot/Renovate를 켭니다. `httpx2`의 출처를 PyPI에서 확인합니다.
3. 베이스 이미지를 `python:3.13.x-slim@sha256:...`처럼 고정합니다.

---

## A07: Identification and Authentication Failures (식별 및 인증 실패)

| 항목 | 내용 |
|---|---|
| 해당 여부 | **일부 해당** |
| 심각도 | **중간** |

**근거**
- 이 앱에는 로그인, 세션, 토큰 등 인증 기능이 아예 없습니다(`main.py` 전체). 그래서 약한 비밀번호 정책, 세션 고정, 무차별 대입 같은 인증 구현 결함은 해당 없고, "인증이 없다는 것" 자체가 A01과 겹치는 문제입니다.
- 간접 근거: 같은 `docker-compose.yml`에서 SonarQube(`:9000`)는 로그인이 필요한 서비스인데, 기본 계정 변경 여부가 확인되지 않습니다. **(추측: 기본 `admin/admin` 그대로일 가능성)**
- `sonar-project.properties:13`이 토큰을 파일에 적지 않는다고 명시한 점은 좋은 관행입니다.

**수정안**
1. 사용자별 데이터가 필요하면 검증된 라이브러리(`fastapi-users`, Authlib 등)나 외부 IdP로 인증을 구현합니다. 직접 만들지 않습니다.
2. SonarQube 관리자 비밀번호를 즉시 변경하고, 분석에는 개인 토큰이 아닌 프로젝트 분석 토큰을 씁니다.

---

## A08: Software and Data Integrity Failures (소프트웨어 및 데이터 무결성 실패)

| 항목 | 내용 |
|---|---|
| 해당 여부 | **일부 해당** |
| 심각도 | **낮음** |

**근거**
- 역직렬화는 `json.loads`만 씁니다(`main.py:36`). `pickle`, `yaml.load` 같은 위험한 역직렬화는 확인되지 않았습니다. 읽은 데이터는 Pydantic 모델로 다시 검증됩니다(`TodoItem(**t)`).
- `index.html`은 외부 CDN 스크립트나 스타일시트를 불러오지 않습니다(`<script src>`, `<link>` 없음). 그래서 서브리소스 무결성(SRI) 문제는 없습니다.
- 공급망 측면:
  - `Dockerfile:2`의 이미지 태그, `Dockerfile:19`의 `pip install`에 해시 고정이 없습니다(A06과 같은 문제).
  - 저장소에서 CI/CD 파이프라인 파일(`Jenkinsfile`, `.github/workflows`)을 찾지 못했습니다. `sonar-project.properties:11`의 주석은 Jenkins 연동을 언급하지만, 파이프라인 자체는 확인할 수 없어서 서명·검증 단계가 있는지는 **(추측: 확인 불가)** 입니다.
- `todo.json`은 파일 시스템에 쓰기 접근이 있으면 누구나 바꿀 수 있고 무결성 검증이 없습니다. 다만 앱 사용자에게 파일 접근 권한이 없다면 영향은 작습니다.

**수정안**
1. 이미지 다이제스트 고정과 `pip --require-hashes`를 적용합니다(A06 수정안과 같음).
2. CI 파이프라인이 있다면 코드 리뷰와 서명, 보호된 브랜치 규칙을 적용합니다.

---

## A09: Security Logging and Monitoring Failures (보안 로깅 및 모니터링 실패)

| 항목 | 내용 |
|---|---|
| 해당 여부 | **해당** |
| 심각도 | **중간** |

**근거**
- `main.py`에 `logging` 모듈 사용이 없습니다. 생성·수정·삭제(`main.py:56-78`)에 대한 감사 로그가 남지 않습니다. 누가, 언제, 무엇을 바꿨는지 알 수 없습니다.
- uvicorn의 기본 접근 로그(`Dockerfile:31`의 실행 명령으로 켜짐)만 남는 것으로 보입니다. 이 로그에는 요청 경로와 상태 코드만 있어서, 요청한 사용자가 누구인지(인증이 없으므로)와 변경 전후 값이 없습니다.
- 손상된 `todo.json` 같은 예외 상황(`main.py:36`)도 처리·기록되지 않습니다. 사용자에게는 500 오류만 보입니다.
- `docker-compose.yml`에 로그 수집·로테이션 설정(`logging:` 항목)이 없습니다. 모니터링이나 알림 설정도 저장소에서 확인되지 않았습니다.
- SonarQube(코드 품질 분석)는 있지만 런타임 보안 모니터링 도구는 아닙니다.

**수정안**
1. `logging`으로 변경 작업(생성/수정/삭제, 항목 id, 클라이언트 IP)을 기록하고, 로드 실패 같은 오류를 `logger.exception`으로 남깁니다. 로그에는 개인정보를 넣지 않습니다.
2. `docker-compose.yml`에 `logging: driver: json-file, options: {max-size, max-file}`로 로그 로테이션을 설정하고, 중앙 수집과 이상 징후 알림을 연결합니다.

---

## A10: Server-Side Request Forgery (SSRF)

| 항목 | 내용 |
|---|---|
| 해당 여부 | **해당 없음** |
| 심각도 | - |

**근거**
- 서버 코드(`main.py`)는 외부 URL을 받지 않고, 사용자 입력으로 다른 서버에 요청을 보내는 코드도 없습니다. `requests`, `httpx`, `urllib` 등을 임포트하지 않습니다(`main.py:1-7`). 서버가 하는 일은 고정 경로 파일 읽기와 쓰기(`main.py:11-13`)뿐입니다.
- `requirements.txt:7`의 `httpx2`는 테스트(TestClient)용이며 앱 코드에서는 쓰이지 않습니다.
- 클라이언트 `fetch`는 같은 출처의 상대 경로(`/todos`, `/version`)만 호출합니다(`index.html:336, 522`).

**주의할 점.** 나중에 "URL 미리보기", "웹훅", "원격 파일 가져오기" 같은 기능을 추가하면 SSRF가 해당될 수 있습니다. 그때는 허용 목록(allowlist) 방식으로 URL을 검증하고 내부 IP 대역 접근을 차단해야 합니다.

---

## 우선순위가 높은 개선 사항 3가지

1. **인증을 붙이거나 네트워크 노출을 줄이기 (A01, A07, A05).**
   현재 모든 API가 인증 없이 열려 있고 `5051`, `9000` 포트가 모든 인터페이스로 공개됩니다. 가장 빠른 조치는 `docker-compose.yml`의 포트를 `127.0.0.1:`로 제한하는 것이고, 외부 공개가 필요하면 API 키/OAuth 인증과 TLS를 추가합니다. SonarQube의 기본 관리자 비밀번호 변경도 함께 해야 합니다.

2. **데이터 저장의 동시성·입력 제한 보강 (A04).**
   `todo.json` 전체 읽기·쓰기에 잠금과 원자적 저장이 없어서 동시 요청 때 데이터 유실, id 중복, 파일 손상이 일어날 수 있습니다. `description` 길이 제한(`main.py:24`), 항목 수 제한, 요청 빈도 제한도 필요합니다. 장기적으로는 SQLite 같은 DB로 옮기는 것을 권장합니다.

3. **의존성·이미지 고정과 의존성 분리 (A06, A08).**
   `requirements.txt`가 `>=`만 쓰고 잠금 파일이 없으며, 테스트 패키지까지 운영 이미지에 설치됩니다. 런타임/개발 의존성을 분리하고 해시 고정 잠금 파일, 이미지 다이제스트 고정, `pip-audit` 점검을 도입합니다. `httpx2`의 출처도 확인해야 합니다.

---

## 한계

- 정적 분석만 수행했으며 실행 중인 서버, 컨테이너, 네트워크는 확인하지 않았습니다. 실제 포트 노출 여부, SonarQube 비밀번호 상태, 설치되는 패키지 버전은 **(추측)** 입니다.
- `fastapi-app/tests/`와 `integration_tests/`는 이번 범위(설정·애플리케이션 코드)에 맞춰 상세 분석에서 제외했습니다.
- `.git` 내부의 과거 커밋 이력(비밀값이 과거 커밋에 있었는지 등)은 분석하지 않았습니다. `.gitignore`가 없어서 `__pycache__/`나 `todo.json`이 커밋에 포함되어 있는지도 확인하지 않았습니다 **(추측: 미확인)**.
