#!/usr/bin/env python3
"""pytest 결과(junit.xml)와 커버리지(cov.json)를 차트 한 장짜리 HTML(report/index.html)로 만든다.
표준 라이브러리만 쓴다. Jenkins 파이프라인이 만든 이 파일을 쿠버네티스(nginx)가 서비스한다."""
import html
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime

CHART_SRC = os.environ.get("CHART_SRC", "https://cdn.jsdelivr.net/npm/chart.js@4.6.1/dist/chart.umd.min.js")

suite = ET.parse("junit.xml").getroot()
if suite.tag != "testsuite":
    suite = suite.find("testsuite")
total = int(suite.get("tests", 0))
failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
skipped = int(suite.get("skipped", 0))
passed = total - failed - skipped
seconds = float(suite.get("time", 0))

cov = json.load(open("cov.json", encoding="utf-8"))
cov_total = round(cov["totals"]["percent_covered"], 1)

cases = sorted(
    ((tc.get("name", "?"), float(tc.get("time", 0)) * 1000) for tc in suite.iter("testcase")),
    key=lambda x: x[1], reverse=True,
)[:8]
cases.reverse()  # 가로 막대에서 가장 긴 것이 위로 오게
slow_labels = [(n.replace("test_", "", 1)[:32] + "…") if len(n) > 38 else n.replace("test_", "", 1) for n, _ in cases]
slow_values = [round(ms, 1) for _, ms in cases]

build = os.environ.get("BUILD_NUMBER", "-")
try:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "-"
except OSError:
    commit = "-"
when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
ok = failed == 0

page = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jenkins → Kubernetes 배포 결과</title>
<style>
  :root {{ --bg:#0f172a; --card:#1e293b; --line:#334155; --text:#e2e8f0; --sub:#94a3b8; --ok:#34d399; --bad:#f87171; --skip:#fbbf24; --accent:#60a5fa; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font-family:'Segoe UI','Noto Sans KR','Malgun Gothic',sans-serif; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:36px 24px 48px; }}
  header {{ display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:12px; margin-bottom:24px; }}
  h1 {{ margin:0; font-size:28px; }}
  .sub {{ color:var(--sub); font-size:14px; margin-top:6px; }}
  .badge {{ padding:8px 18px; border-radius:999px; font-weight:700; font-size:15px; background:{'rgba(52,211,153,.15)' if ok else 'rgba(248,113,113,.15)'}; color:{'var(--ok)' if ok else 'var(--bad)'}; border:1px solid {'var(--ok)' if ok else 'var(--bad)'}; }}
  .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:20px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:20px 22px; }}
  .kpi .v {{ font-size:34px; font-weight:800; }}
  .kpi .l {{ color:var(--sub); font-size:13px; margin-top:4px; }}
  .charts {{ display:grid; grid-template-columns:1fr 1.4fr; gap:16px; }}
  .card h2 {{ margin:0 0 14px; font-size:16px; color:var(--sub); font-weight:600; }}
  .box {{ position:relative; height:280px; }}
  footer {{ margin-top:22px; color:var(--sub); font-size:13px; display:flex; gap:10px; flex-wrap:wrap; }}
  footer b {{ color:var(--text); }}
  @media (max-width:760px) {{ .kpis {{ grid-template-columns:repeat(2,1fr); }} .charts {{ grid-template-columns:1fr; }} }}
</style></head>
<body><div class="wrap">
<header>
  <div><h1>Jenkins → Kubernetes 배포 결과</h1>
  <div class="sub">빌드 #{html.escape(build)} · 커밋 {html.escape(commit)} · {when}</div></div>
  <div class="badge">{'모든 테스트 통과' if ok else f'테스트 {failed}건 실패'}</div>
</header>
<section class="kpis">
  <div class="card kpi"><div class="v">{total}</div><div class="l">전체 테스트</div></div>
  <div class="card kpi"><div class="v" style="color:var(--ok)">{passed}</div><div class="l">통과</div></div>
  <div class="card kpi"><div class="v" style="color:var(--accent)">{cov_total}%</div><div class="l">코드 커버리지</div></div>
  <div class="card kpi"><div class="v">{seconds:.1f}s</div><div class="l">테스트 소요 시간</div></div>
</section>
<section class="charts">
  <div class="card"><h2>테스트 결과</h2><div class="box"><canvas id="tests"></canvas></div></div>
  <div class="card"><h2>가장 오래 걸린 테스트 Top 8 (ms)</h2><div class="box"><canvas id="slow"></canvas></div></div>
</section>
<footer><span>이 페이지는 <b>Jenkins</b>가 만들어 <b>Kubernetes</b>(nginx 파드)가 서비스하고 있습니다.</span></footer>
</div>
<script src="{html.escape(CHART_SRC)}"></script>
<script>
  Chart.defaults.color = '#94a3b8';
  Chart.defaults.borderColor = '#334155';
  const center = {{ id: 'center', afterDraw(c) {{
    const a = c.chartArea, x = (a.left + a.right) / 2, y = (a.top + a.bottom) / 2, ctx = c.ctx;
    ctx.save(); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = '#e2e8f0'; ctx.font = '800 34px sans-serif'; ctx.fillText('{passed}/{total}', x, y - 8);
    ctx.fillStyle = '#94a3b8'; ctx.font = '13px sans-serif'; ctx.fillText('통과', x, y + 22); ctx.restore();
  }} }};
  new Chart(document.getElementById('tests'), {{
    type: 'doughnut',
    data: {{ labels: ['통과', '실패', '건너뜀'], datasets: [{{ data: [{passed}, {failed}, {skipped}],
      backgroundColor: ['#34d399', '#f87171', '#fbbf24'], borderWidth: 0 }}] }},
    options: {{ maintainAspectRatio: false, cutout: '70%', plugins: {{ legend: {{ position: 'bottom' }} }} }},
    plugins: [center]
  }});
  new Chart(document.getElementById('slow'), {{
    type: 'bar',
    data: {{ labels: {json.dumps(slow_labels, ensure_ascii=False)}, datasets: [{{ label: '소요 시간(ms)', data: {json.dumps(slow_values)},
      backgroundColor: '#60a5fa', borderRadius: 8 }}] }},
    options: {{ indexAxis: 'y', maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
  }});
</script></body></html>
"""

os.makedirs("report", exist_ok=True)
with open("report/index.html", "w", encoding="utf-8") as f:
    f.write(page)
print(f"report/index.html 생성: 테스트 {total}건 (통과 {passed}, 실패 {failed}, 건너뜀 {skipped}), 커버리지 {cov_total}%")
