// 릴스 장면 런타임. 장면은 시간 t(초)를 받아 그 순간의 화면을 그리는 함수 하나로 만든다.
//
//   <script src="../../../kit/kit.js"></script>
//   <script>Reel.scene((t, R) => { ... DOM/SVG/canvas를 t에 맞게 갱신 ... });</script>
//
// 렌더러(reels/reel.py)는 window.REEL에 장면 정보를 넣고 매 프레임 window.seek(t)를 부른 뒤 캡처한다.
// 그래서 CSS animation, setTimeout, Date.now() 같은 실제 시간에 기대는 움직임은 쓰지 않는다.
// 브라우저에서 파일을 직접 열면 REEL이 없으므로 예시 값으로 반복 재생한다 (미리보기용).
(function () {
  const D = window.REEL || { scene: { id: "preview", duration: 6, vo_start: 0.3, vo_duration: 5, captions: [] },
    env: [], clips: {}, fps: 30, global_start: 0, total: 6 };
  const R = (window.Reel = { data: D, scene: null });
  R.duration = D.scene.duration;
  R.clamp = (x, a = 0, b = 1) => Math.min(Math.max(x, a), b);
  R.lerp = (a, b, k) => a + (b - a) * k;
  R.ease = (k) => { k = R.clamp(k); return k * k * (3 - 2 * k); };
  R.ramp = (t, a, b) => R.ease((t - a) / (b - a));
  // 0→1로 살짝 넘쳤다 돌아오는 팝 (등장 애니메이션)
  R.pop = (t, t0, d = 0.3) => { const k = R.clamp((t - t0) / d); const c = 2.2; return t < t0 ? 0 : 1 + (c + 1) * (k - 1) ** 3 + c * (k - 1) ** 2; };
  // 나레이션 안에서의 위치(0~1)를 장면 시간으로 바꾼다. 단어가 나오는 순간에 맞춰 무언가를 띄울 때 쓴다.
  R.at = (frac) => D.scene.vo_start + frac * D.scene.vo_duration;
  // 장면 오디오(나레이션+클립)의 세기, 0~1. 파형·펄스를 소리에 맞춰 움직일 때 쓴다.
  R.level = (t) => { const i = Math.floor(t * D.fps); return D.env[i] || 0; };
  // 클립 파형 샘플(4 kHz, -1~1). R.clip("audio/A.wav") → Float32Array처럼 쓸 수 있는 배열
  R.clip = (name) => D.clips[name] || [];
  // 샘플 배열 → SVG path d
  R.wavePath = (s, x0, x1, mid, amp, n = 400) => {
    if (!s.length) return `M${x0},${mid} L${x1},${mid}`;
    let d = "";
    for (let i = 0; i < n; i++) {
      const v = s[Math.floor((i / (n - 1)) * (s.length - 1))];
      d += (i ? "L" : "M") + (x0 + ((x1 - x0) * i) / (n - 1)).toFixed(1) + "," + (mid - v * amp).toFixed(1);
    }
    return d;
  };
  R.$ = (sel) => document.querySelector(sel);
  R.$$ = (sel) => Array.from(document.querySelectorAll(sel));
  // 요소의 보이기/위치/크기를 한 번에 설정
  R.set = (el, { o, x = 0, y = 0, s = 1, r = 0 } = {}) => {
    if (typeof el === "string") el = R.$(el);
    if (!el) return;
    if (o !== undefined) el.style.opacity = o;
    el.style.transform = `translate(${x}px, ${y}px) scale(${s}) rotate(${r}deg)`;
  };

  let cap, bar;
  function chrome(t) {
    if (!cap) {
      cap = document.createElement("div"); cap.className = "reel-caption"; cap.appendChild(document.createElement("span"));
      bar = document.createElement("div"); bar.className = "reel-progress";
      document.body.append(cap, bar);
    }
    const c = D.scene.captions.find((c) => t >= c.t0 && t < c.t1);
    const txt = c ? c.text : "";
    if (cap.firstChild.textContent !== txt) cap.firstChild.textContent = txt;
    bar.style.width = (1080 * (D.global_start + t)) / D.total + "px";
  }

  R.scene = function (fn) {
    window.seek = (t) => { fn(t, R); chrome(t); };
    if (!window.REEL) {
      const t0 = performance.now();
      const loop = () => { window.seek(((performance.now() - t0) / 1000) % R.duration); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    }
  };
})();
