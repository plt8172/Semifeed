// 릴스 무대 런타임. 에피소드 하나는 무대 하나이고, 무대는 시간 t(초)를 받아 그 순간의 화면을 그리는 함수 하나다.
//
//   <script src="../../kit/kit.js"></script>
//   <script>Reel.stage((t, R) => { ... t에 맞게 화면을 다시 그린다 ... });</script>
//
// 렌더러(reels/reel.py)는 window.REEL에 시간표를 넣고 매 프레임 window.seek(t)를 부른 뒤 캡처한다.
// 그래서 CSS animation, transition, setTimeout, Date.now() 같은 실제 시간에 기대는 움직임은 쓰지 않는다.
// 자막(말하는 단어 강조)과 상단 진행 바는 여기서 자동으로 그린다.
(function () {
  const D = window.REEL;
  if (!D) { document.body.textContent = "reel.py로 열어 주세요 (preview / frames / build)"; return; }
  const R = (window.Reel = { data: D, total: D.total, fps: D.fps });
  const lines = Object.fromEntries(D.lines.map((l) => [l.id, l]));

  // ----- 수학 -----
  R.clamp = (x, a = 0, b = 1) => Math.min(Math.max(x, a), b);
  R.lerp = (a, b, k) => a + (b - a) * k;
  R.ease = (k) => { k = R.clamp(k); return k * k * (3 - 2 * k); };
  // a~b초 사이에 0→1로 부드럽게
  R.ramp = (t, a, b) => R.ease((t - a) / (b - a));
  // a에서 나타나 b에서 사라지는 투명도 (앞뒤 f초 동안)
  R.vis = (t, a, b, f = 0.35) => R.ramp(t, a, a + f) * (1 - R.ramp(t, b - f, b));
  // 0→1로 살짝 넘쳤다 돌아오는 등장 크기
  R.pop = (t, t0, d = 0.3) => { const k = R.clamp((t - t0) / d), c = 2.2; return t < t0 ? 0 : 1 + (c + 1) * (k - 1) ** 3 + c * (k - 1) ** 2; };

  // ----- 시간표 -----
  R.line = (id) => { if (!lines[id]) throw new Error("없는 줄 id: " + id); return lines[id]; };
  // 줄의 나레이션 k 지점(0=시작, 1=끝)의 시각
  R.at = (id, k = 0) => { const l = R.line(id); return l.t0 + k * (l.t1 - l.t0); };
  // 줄이 끝나는(다음 줄이 시작하는) 시각
  R.end = (id) => R.line(id).end;
  // 줄에서 그 글자가 든 단어(또는 n번째 단어)를 말하기 시작하는 시각
  R.word = (id, w) => {
    const l = R.line(id);
    const hit = typeof w === "number" ? l.words[w] : l.words.find((x) => x.w.includes(w));
    if (!hit) throw new Error(`줄 ${id}에 단어 없음: ${w}`);
    return hit.t0;
  };
  // 줄의 n번째 클립 {t0, t1}
  R.clipTime = (id, n = 0) => { const c = R.line(id).clips[n]; if (!c) throw new Error(`줄 ${id}에 클립 ${n} 없음`); return c; };

  // ----- 소리 데이터 -----
  // 그 순간 전경 소리(나레이션·클립·효과음)의 세기 0~1
  R.level = (t) => D.env[Math.floor(t * D.fps)] || 0;
  // 오디오 파형 샘플 (clip_sr Hz, -1~1). episode.json의 clips나 waves에 넣은 파일만
  R.clip = (name) => { if (!D.clips[name]) throw new Error("clips/waves에 없는 파일: " + name); return D.clips[name]; };
  R.clipSr = D.clip_sr;
  // 샘플 배열의 pos(소수 가능) 위치 값. 샘플 사이는 부드럽게 잇는다
  R.sample = (s, pos) => {
    const i = Math.floor(pos), k = pos - i, g = (j) => s[Math.min(Math.max(j, 0), s.length - 1)] || 0;
    const a = g(i - 1), b = g(i), c = g(i + 1), d = g(i + 2);
    return b + 0.5 * k * (c - a + k * (2 * a - 5 * b + 4 * c - d + k * (3 * (b - c) + d - a)));
  };

  // ----- 그리기 (SVG 문자열) -----
  // 함수 f(k) (k: 0~1) → SVG path d. x0~x1 사이에 n개 점
  R.plot = (f, x0, x1, mid, amp, n = 300, k0 = 0, k1 = 1) => {
    let d = "";
    const a = Math.round(k0 * (n - 1)), b = Math.round(k1 * (n - 1));
    for (let i = a; i <= b; i++) {
      const k = i / (n - 1);
      d += (i === a ? "M" : "L") + (x0 + (x1 - x0) * k).toFixed(1) + "," + (mid - f(k) * amp).toFixed(1);
    }
    return d || `M${x0},${mid}`;
  };
  // 아래 도우미는 SVG 조각(문자열)을 돌려준다. 무대는 매 프레임 조각을 이어 붙여 svg.innerHTML에 넣는다.
  R.C = { bg: "#07080c", fg: "#f2f3f5", mu: "#8a8f9c", dim: "#2b2e39", a: "#ffb83d", b: "#5aa9ff" };   // kit.css의 색과 같다
  R.GLOW_A = "rgba(255,184,61,0.6)"; R.GLOW_B = "rgba(90,169,255,0.6)";
  // 투명도 o인 묶음. o가 0이면 빈 문자열
  R.g = (o, inner, extra = "") => (o <= 0.004 || !inner ? "" : `<g opacity="${o.toFixed(3)}" ${extra}>${inner}</g>`);
  R.path = (d, col = R.C.fg, w = 4, extra = "") => `<path d="${d}" fill="none" stroke="${col}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" ${extra}/>`;
  R.seg = (x1, y1, x2, y2, col = R.C.fg, w = 4, extra = "") => `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${col}" stroke-width="${w}" stroke-linecap="round" ${extra}/>`;
  // o: {w: 굵기, a: start|middle|end, f: 색, ls: 자간, x: 그 밖의 속성}
  R.text = (x, y, s, size, o = {}) => `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" font-size="${size}" font-weight="${o.w || 700}" text-anchor="${o.a || "middle"}" fill="${o.f || R.C.fg}" ${o.ls ? `letter-spacing="${o.ls}"` : ""} ${o.x || ""}>${s}</text>`;
  R.span = (s, f, size, w) => `<tspan fill="${f}" ${size ? `font-size="${size}"` : ""} ${w ? `font-weight="${w}"` : ""}>${s}</tspan>`;
  // 은은한 빛. path·seg·circle의 extra에 넣는다
  R.glow = (col, r = 14) => `style="filter:drop-shadow(0 0 ${r}px ${col})"`;
  R.TNUM = 'style="font-variant-numeric:tabular-nums"';    // 숫자가 바뀌어도 폭이 흔들리지 않게
  R.num = (x) => Math.round(x).toLocaleString("en-US");
  R.$ = (sel) => document.querySelector(sel);

  // 머리말(작은 챕터 표시 + 제목)을 시각에 맞춰 바꾼다. items: [{t, chap, title}] (title이 없으면 숨김)
  let head;
  R.header = (t, items) => {
    if (!head) {
      head = document.createElement("div"); head.className = "reel-head";
      head.innerHTML = '<div class="chap"></div><div class="title"></div>';
      document.body.appendChild(head);
    }
    let cur = null, next = null;
    for (const it of items) { if (t >= it.t) cur = it; else { next = it; break; } }
    const o = cur && cur.title ? R.ramp(t, cur.t, cur.t + 0.3) * (next ? 1 - R.ramp(t, next.t - 0.25, next.t) : 1) : 0;
    head.style.opacity = o;
    head.style.transform = `translateY(${(1 - (cur ? R.ramp(t, cur.t, cur.t + 0.3) : 0)) * 14}px)`;
    if (cur && head.dataset.k !== String(cur.t)) {
      head.dataset.k = cur.t;
      head.children[0].textContent = cur.chap || "";
      head.children[1].textContent = cur.title || "";
    }
  };

  // ----- 자막과 진행 바 -----
  let cap, bar;
  function chrome(t) {
    if (!cap) {
      cap = document.createElement("div"); cap.className = "reel-caption";
      bar = document.createElement("div"); bar.className = "reel-progress";
      document.body.append(cap, bar);
    }
    const c = D.captions.find((c) => t >= c.t0 && t < c.t1);
    const key = c ? String(c.t0) : "";
    if (cap.dataset.k !== key) {
      cap.dataset.k = key;
      cap.innerHTML = c ? c.words.map((w) => `<span>${w.w.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</span>`).join(" ") : "";
    }
    if (c) {
      const now = c.words.filter((w) => t >= w.t0 - 0.04).length - 1;
      Array.from(cap.children).forEach((el, i) => { el.className = i < now ? "said" : i === now ? "now" : ""; });
    }
    bar.style.width = (1080 * t) / D.total + "px";
  }

  R.stage = function (fn) {
    window.seek = (t) => { fn(t, R); chrome(t); };
  };
})();
