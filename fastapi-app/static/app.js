"use strict";
// v5.0.0 — 화면 로직. v4 에서는 index.html 안에 있었으나, 엄격한 CSP(script-src 'self') 적용을 위해 분리했다.

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}) => Object.assign(document.createElement(tag), props);
const listEl = $("todo-list"), errorEl = $("error"), emptyEl = $("empty"), countEl = $("count");

const PRIORITY_LABEL = { high: "높음", normal: "보통", low: "낮음" };
const PRIORITY_ORDER = { high: 0, normal: 1, low: 2 };
const KEY_STORAGE = "todo-api-key";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let todos = [];            // 서버에서 받아온 전체 목록
let filter = "all";        // all | active | done
let keyword = "";          // 검색어
let editingId = null;      // 수정 창에서 편집 중인 항목 id

const today = () => new Date().toLocaleDateString("sv-SE");   // "YYYY-MM-DD"

// ---------- 접근 키 (서버가 TODO_API_KEY 를 설정했을 때만 필요) ----------
// 탭을 닫으면 사라지도록 sessionStorage 에만 둔다.
const getKey = () => { try { return sessionStorage.getItem(KEY_STORAGE); } catch { return null; } };
const setKey = (key) => { try { sessionStorage.setItem(KEY_STORAGE, key); } catch { /* 저장 불가면 이번 요청에만 쓰지 못한다 */ } };
const clearKey = () => { try { sessionStorage.removeItem(KEY_STORAGE); } catch { /* 무시 */ } };

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// 서버 오류 응답에서 사람이 읽을 수 있는 문장을 꺼낸다
async function readError(res) {
  try {
    const detail = (await res.json()).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((d) => d.msg).join(", ");
  } catch { /* JSON 이 아니면 아래 기본 문구 */ }
  return `서버 오류 (${res.status})`;
}

// 모든 요청을 한 곳에서 처리하고, 실패는 조용히 넘기지 않는다
async function api(url, method = "GET", body) {
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  const key = getKey();
  if (key) headers["X-API-Key"] = key;

  const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (!res.ok) throw new ApiError(res.status, await readError(res));
  return res.status === 204 ? null : res.json();
}

const keyDialog = $("key-dialog");

function askKey() {
  const hadKey = Boolean(getKey());
  if (hadKey) clearKey();                         // 저장해 둔 키가 거부됐으니 지운다
  $("key-message").textContent = hadKey
    ? "키가 맞지 않아요. 다시 입력해 주세요."
    : "이 서버는 접근 키가 필요해요. 관리자에게 받은 키를 입력해 주세요.";
  $("key-input").value = "";
  if (!keyDialog.open) keyDialog.showModal();
}

$("key-form").onsubmit = (event) => {
  event.preventDefault();
  setKey($("key-input").value);
  keyDialog.close();
  load();
};

// 작업을 실행하고, 실패하면 화면에 이유를 띄운다
async function run(what, job) {
  try {
    await job();
    errorEl.hidden = true;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {   // 키가 필요하거나 틀림
      askKey();
      return;
    }
    errorEl.textContent = `${what} 실패: ${e.message}`;
    errorEl.hidden = false;
  }
}

const load = () => run("목록 불러오기", async () => { todos = await api("/todos"); render(); });
const save = (id, todo) => run("수정", async () => { await api(`/todos/${id}`, "PUT", todo); await load(); });

// 필터 + 검색 적용 후: 미완료 먼저 → 우선순위 높은 순 → 마감일 빠른 순
function visibleTodos() {
  const noDate = "9999-99-99";
  return todos
    .filter((t) => filter === "all" || (filter === "done") === t.completed)
    .filter((t) => `${t.title} ${t.description}`.toLowerCase().includes(keyword))
    .sort((a, b) => (a.completed - b.completed)
      || (PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority])
      || (a.due_date || noDate).localeCompare(b.due_date || noDate));
}

function render() {
  const shown = visibleTodos();
  const done = todos.filter((t) => t.completed).length;
  const left = todos.length - done;
  const percent = todos.length ? Math.round((done / todos.length) * 100) : 0;

  countEl.textContent = `미완료 ${left} / 전체 ${todos.length}`;
  $("progress-text").textContent = `${percent}%`;
  $("bar-fill").style.width = `${percent}%`;                   // CSSOM 은 CSP 가 막지 않는다
  $("bar-fill").classList.toggle("is-empty", percent === 0);

  emptyEl.hidden = shown.length > 0;
  emptyEl.textContent = todos.length === 0
    ? "아직 할 일이 없어요. 위에서 첫 항목을 추가해 보세요."
    : "조건에 맞는 항목이 없어요. 검색어나 필터를 바꿔 보세요.";

  listEl.replaceChildren(...shown.map((todo) => {
    const check = el("input", { type: "checkbox", className: "check", checked: todo.completed });
    check.setAttribute("aria-label", `${todo.title} 완료 표시`);
    check.onchange = () => {
      if (check.checked) burst(check);                         // 완료하는 순간 색종이
      save(todo.id, { ...todo, completed: check.checked });
    };

    const body = el("div", { className: "body" });
    body.append(el("span", { className: "title", textContent: todo.title }));
    if (todo.description) body.append(el("span", { className: "desc", textContent: todo.description }));

    const meta = el("div", { className: "meta" });
    meta.append(todo.completed
      ? el("span", { className: "chip done", textContent: "완료" })
      : el("span", { className: `chip ${todo.priority}`, textContent: PRIORITY_LABEL[todo.priority] }));
    if (todo.due_date) {
      meta.append(el("span", { className: "chip", textContent: `마감 ${todo.due_date}` }));
      if (!todo.completed && todo.due_date < today()) {
        meta.append(el("span", { className: "chip overdue", textContent: "기한 지남" }));
      }
    }
    body.append(meta);

    const li = el("li", { className: `item ${todo.completed ? "is-done" : `p-${todo.priority}`}` });
    const actions = el("div", { className: "actions" });
    actions.append(
      el("button", { type: "button", className: "btn small", textContent: "수정", onclick: () => openEdit(todo) }),
      el("button", { type: "button", className: "btn small danger", textContent: "삭제", onclick: () => remove(todo.id, li) }),
    );
    li.append(check, body, actions);
    return li;
  }));
}

// ---------- 수정 창 ----------
const dialog = $("edit-dialog");

function openEdit(todo) {
  editingId = todo.id;
  $("e-title").value = todo.title;
  $("e-description").value = todo.description;
  $("e-due").value = todo.due_date;
  document.querySelector(`input[name="e-priority"][value="${todo.priority}"]`).checked = true;
  dialog.showModal();
  $("e-title").focus();
}

$("edit-form").onsubmit = (event) => {
  event.preventDefault();
  const todo = todos.find((t) => t.id === editingId);
  if (!todo) { dialog.close(); return; }
  save(editingId, {
    ...todo,
    title: $("e-title").value.trim(),
    description: $("e-description").value.trim(),
    due_date: $("e-due").value,
    priority: document.querySelector('input[name="e-priority"]:checked').value,
  });
  dialog.close();
};
$("e-cancel").onclick = () => dialog.close();
dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });   // 바깥 클릭으로 닫기

// ---------- 삭제 ----------
function remove(id, li) {
  if (!confirm("정말 삭제할까요?")) return;
  li.classList.add("leaving");
  setTimeout(() => run("삭제", async () => { await api(`/todos/${id}`, "DELETE"); await load(); }),
             reduceMotion ? 0 : 180);
}

// ---------- 추가 ----------
$("todo-form").onsubmit = (event) => {
  event.preventDefault();
  run("추가", async () => {
    await api("/todos", "POST", {
      title: $("title").value.trim(),
      description: $("description").value.trim(),
      due_date: $("due-date").value,
      priority: document.querySelector('input[name="priority"]:checked').value,
    });
    event.target.reset();
    await load();
  });
};

// ---------- 검색·필터 ----------
$("search").oninput = (event) => { keyword = event.target.value.trim().toLowerCase(); render(); };

document.querySelectorAll(".filter").forEach((btn) => {
  btn.onclick = () => {
    filter = btn.dataset.filter;
    document.querySelectorAll(".filter").forEach((b) => b.classList.toggle("active", b === btn));
    render();
  };
});

// ---------- 색종이 (완료를 누르는 순간에만 터진다) ----------
const canvas = $("confetti"), ctx = canvas.getContext("2d");
const COLORS = ["#ff5d6c", "#ffc933", "#2fd5a3", "#4cc3ff", "#6c4cff", "#ffffff"];
let particles = [], raf = null;

function resize() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }
window.addEventListener("resize", resize);
resize();

function burst(target) {
  if (reduceMotion) return;
  const r = target.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  for (let i = 0; i < 80; i++) {
    const angle = Math.random() * Math.PI * 2, speed = 4 + Math.random() * 8;
    particles.push({
      x, y, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed - 5,
      size: 6 + Math.random() * 7, rot: Math.random() * 6, vr: (Math.random() - .5) * .45,
      life: 60 + Math.random() * 35, color: COLORS[i % COLORS.length],
    });
  }
  if (!raf) raf = requestAnimationFrame(tick);
}

function tick() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  particles = particles.filter((p) => p.life > 0);
  for (const p of particles) {
    p.vy += .3; p.x += p.vx; p.y += p.vy; p.vx *= .985; p.rot += p.vr; p.life--;
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(p.rot);
    ctx.globalAlpha = Math.min(1, p.life / 25);
    ctx.fillStyle = p.color;
    ctx.fillRect(-p.size / 2, -p.size / 3, p.size, p.size * .6);
    ctx.restore();
  }
  if (particles.length) { raf = requestAnimationFrame(tick); }
  else { raf = null; ctx.clearRect(0, 0, canvas.width, canvas.height); }
}

fetch("/version").then((r) => r.json()).then((v) => { $("version").textContent = v.version; }).catch(() => {});

load();
