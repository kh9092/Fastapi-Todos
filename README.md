# To-Do List (FastAPI) 

## 버전 기록

| 버전 | 날짜 | 내용 |
|---|---|---|
| [v1.1.0](https://github.com/kh9092/Fastapi-Todos/releases/tag/v1.1.0) | 2026-09-17 | 마감일, 검색, 필터 |
| [v2.0.0](https://github.com/kh9092/Fastapi-Todos/releases/tag/v2.0.0) | 2026-09-17 | 과제 제출 버전 |
| [v3.0.0](https://github.com/kh9092/Fastapi-Todos/releases/tag/v3.0.0) | 2026-09-30 | 우선순위 색 표시, 단위 테스트 17개 |
| [v4.0.0](https://github.com/kh9092/Fastapi-Todos/releases/tag/v4.0.0) | 2026-10-05 | 화면 리디자인, 달성률 바, 수정 창 |
| [v5.0.0](https://github.com/kh9092/Fastapi-Todos/releases/tag/v5.0.0) | 2026-10-10 | OWASP Top 10(2021) 점검 반영: API 키 인증, 입력 제한, 보안 헤더·CSP, 의존성 버전 고정, 감사 로그 |
| [v6.0.0](https://github.com/kh9092/Fastapi-Todos/releases/tag/v6.0.0) | 2026-11-02 | 관측 가능성: 앱 고유 지표, 알림 규칙 7개, Grafana 대시보드를 코드로 관리 |
| [v7.0.0](https://github.com/kh9092/Fastapi-Todos/releases/tag/v7.0.0) | 2026-11-10 | 부하 테스트로 찾은 병목을 읽기 캐시로 개선하고 다시 측정 |

## 구조

```
개발자 → GitHub → Jenkins → pytest · SonarQube(Quality Gate) → Docker 이미지 빌드 → Docker Hub → 서버 배포
                                                            (앞 단계가 실패하면 뒤 단계는 실행되지 않음)

앱(/metrics) ← Prometheus(15초마다 수집) → 알림 규칙 → Grafana 대시보드
JMeter(가상 사용자) → 앱 → InfluxDB(5초마다 전송) → Grafana
```

| 폴더·파일 | 내용 |
|---|---|
| `fastapi-app/` | 앱 코드, 단위·통합 테스트, Dockerfile |
| `docker-compose.yml` | 앱, SonarQube, Prometheus, Grafana, node-exporter, cAdvisor, InfluxDB (JMeter는 `loadtest` 프로파일) |
| `prometheus/` | 수집 설정, 알림 규칙 7개와 규칙 단위 테스트 |
| `grafana/` | 대시보드 JSON (서버가 시작될 때 자동으로 읽힘) |
| `jmeter/` | 부하 테스트 계획과 실행 이미지 |
| `owasp_report.md` | OWASP Top 10(2021) 기준 점검 보고서 |

## 기술 선택과 이유

- **저장 방식**: JSON 파일에 임시 파일로 쓴 뒤 교체(원자적 저장)하고, 쓰기는 락으로 한 번에 하나씩 실행합니다. 쓰다가 끊겨도 원본이 깨지지 않게 하려는 선택입니다.
- **읽기 캐시(v7)**: 부하 테스트에서 항목 수에 비례해 목록 조회가 느려지는 것을 확인했습니다. 파일이 바뀌지 않았으면 메모리의 결과를 쓰고, 저장할 때 캐시를 바로 갱신하며, 앱 밖에서 파일이 바뀌면(경로, 수정 시각, 크기, inode 비교) 자동으로 다시 읽습니다.
- **인증**: 환경 변수 `TODO_API_KEY`가 설정됐을 때만 켜지고, 기본은 기존처럼 열려 있습니다.
- **정적 분석 기준**: SonarQube Quality Gate(새 코드의 이슈 0건, 커버리지 80% 이상)를 통과해야 배포됩니다.

## 검증

| 항목 | 결과 |
|---|---|
| 단위 테스트 | 75개 통과, `main.py` 커버리지 100% |
| 통합 테스트 | 8개 (실제 서버에 요청) |
| 알림 규칙 | `promtool` 단위 테스트 9개 시나리오, 규칙을 일부러 망가뜨려 테스트가 잡아내는지 확인 |
| 캐시 일관성 | 쓰기 6개·읽기 8개 스레드를 6초간 무작위로 실행해 낡은 데이터, 중복 id, 필드 이상 0건 확인 |
| 읽기 캐시 성능 | 항목 500개, 동시 20명 기준 초당 약 312건 → 약 423건, 중앙값 응답 59ms → 28ms |

> 성능 수치는 앱과 부하 생성기가 **같은 컴퓨터**에서 잰 상대 비교입니다. JMeter 테스트(10명, 3개 요청 반복)는 요청 사이에 대기 시간이 있는 가벼운 부하 테스트라서 최대 처리량을 의미하지 않습니다.

## 문제를 해결한 기록

- **SonarQube Quality Gate 시간 초과**: 분석은 성공했는데 결과가 오지 않았습니다. 서버 처리와 웹훅 등록을 로그로 하나씩 제외하고, 컨테이너에서 서버로의 접속이 방화벽(학교 대역만 허용)에 막힌 것을 찾아 컨테이너 대역을 허용해 해결했습니다.
- **컨테이너가 시작하자마자 종료**: 코드에 추가한 라이브러리가 운영 이미지의 의존성 파일에 없었습니다. 운영용과 테스트용 두 파일을 모두 고쳤습니다.
- **그래프가 0.09와 0.11 사이를 규칙적으로 오가던 현상**: 수집 주기(15초)와 헬스체크 주기(30초)가 합쳐진 값과 `rate()` 계산 방식 때문임을 계산하고 재현해 확인했습니다.

## 실행

```bash
git clone https://github.com/kh9092/Fastapi-Todos.git
cd Fastapi-Todos
docker compose up -d fastapi-app        # 앱만: http://localhost:5001
docker compose up -d                    # 전체 스택 (SonarQube, Prometheus, Grafana 등)
```

부하 테스트: `docker compose --profile loadtest run --rm jmeter` (실행 전 `jmeter/report`와 `jmeter/results.jtl`을 지웁니다)


## 화면

<!-- 아래 이미지를 docs/images/ 에 넣고 주석을 해제하세요 -->
<!-- ![앱 화면](docs/images/app.png) -->
<!-- ![Grafana 대시보드](docs/images/grafana-dashboard.png) -->
<!-- ![JMeter 리포트](docs/images/jmeter-report.png) -->
