# 릴스 파이프라인: 에이전트 실행 절차

사용자가 "○○ 원리로 릴스 만들어 줘"라고 하면 이 문서를 처음부터 끝까지 순서대로 따라서, 중간에 묻지 않고 완성 MP4까지 만든다.
판단이 필요한 일(자료 정리, 대본, 장면 설계)은 에이전트가 하고, 합치는 일(TTS, 렌더, 믹스)은 `reels/reel.py`가 한다.
대본과 장면의 품질 기준은 `reels/GUIDE.md`에 있다. 2~4단계를 하기 전에 반드시 읽는다.

## 0. 준비

```bash
pip install -q -r reels/requirements.txt
python3 -c "from playwright.sync_api import sync_playwright" && (python3 -m playwright install chromium >/dev/null 2>&1 || true)
ffmpeg -hide_banner -encoders | grep -q libx264 || echo "ffmpeg(libx264) 필요"
test -n "$OPENAI_API_KEY" || python3 reels/reel.py setup   # OpenAI 키가 없으면 오프라인 한국어 TTS 모델을 받는다
```

TTS는 `OPENAI_API_KEY`가 있으면 OpenAI(`gpt-4o-mini-tts`), 없으면 오프라인 모델, 둘 다 없으면 무음(레이아웃 확인용)으로 만든다.
키는 환경 변수로만 받는다. 저장소에 쓰지 않는다.

## 1. 자료 정리 → `reels/episodes/<slug>/brief.md`

`<slug>`는 영문 소문자와 하이픈으로 짓는다(예: `vocoding`, `pn-junction`).
brief.md에 다음을 적는다.

- 주제 한 줄, 시청자가 끝까지 보고 알게 될 것 한 문장
- 근거 자료: 사용자가 준 강의 자료·문서·링크와, 거기서 가져온 핵심 사실
- 틀리면 안 되는 사실과 수치(단위 포함), 흔한 오해
- 화면이나 소리로 보여 줄 수 있는 진짜 데모 후보 (실측 파형, 코덱 통과 음성, 실제 회로 동작 등)

## 2. 대본 → `script.md`

GUIDE.md의 대본 규칙으로 쓴다.

1. 훅 후보 3개를 쓰고 하나를 고른 이유를 한 줄로 적는다.
2. 단계 3~4개로 뼈대를 잡는다. 단계마다 비유나 예시를 하나 붙인다.
3. 장면표를 쓴다. 장면마다 나레이션, 화면 제목(짧게), 화면에서 보여 줄 것을 적는다.
4. "단순화한 부분" 목록을 적는다.
5. GUIDE.md의 "자체 점검"을 하나씩 확인하고, 걸리는 것이 있으면 대본을 고친다.

## 3. 에피소드 정의 → `episode.json`

```json
{
  "title": "영상 제목",
  "fps": 30,
  "voice": {"backend": "auto", "openai_voice": "coral", "instructions": "말투 지시(선택)"},
  "bgm": {"type": "pulse", "bpm": 96, "gain": 0.1},
  "scenes": [
    {
      "id": "hook",
      "html": "scenes/hook.html",
      "narration": "TTS가 읽을 문장",
      "caption": "화면 자막 (생략하면 narration). 쉼표와 마침표로 끊긴 덩어리가 22자를 넘지 않게",
      "clips": [{"file": "audio/A.wav", "at": "vo+0.5", "gain": 0.8}],
      "waves": ["audio/B.wav"],
      "sfx": [{"type": "pop", "at": "vo:0.4"}],
      "pad": [0.3, 0.4]
    }
  ]
}
```

- 장면 길이는 `pad[0]` + 나레이션 길이(+ 그 뒤 클립) + `pad[1]`로 자동으로 정해진다. `duration`을 주면 그 값을 쓴다.
- 시각 표기: 숫자(장면 시작부터 초), `"vo:0.4"`(나레이션의 40% 지점), `"vo+0.5"`(나레이션이 끝나고 0.5초 뒤).
- `clips`는 장면 안에서 재생할 오디오다. 재생하는 동안 배경음은 자동으로 줄어든다. `waves`는 재생하지 않고 파형만 그릴 오디오다.
- `sfx` 종류: `pop`, `whoosh`, `hit`, `tick`, `ding`. 장면이 바뀔 때는 `whoosh`가 자동으로 들어간다(`"transition": false`로 끈다).
- `bgm`: `{"type": "pulse"}`(합성 비트), `{"type": "file", "file": "audio/bgm.wav"}`, `{"type": "none"}`.
- 음성 데모 자산은 `audio/`에 둔다. 같은 음성의 코덱 비교는 `python3 reels/reel.py codec 원본.wav reels/episodes/<slug>/audio/`로 A(PCM 64k)·B(GSM 13k)·C(Codec2 700bps)를 만든다.

## 4. 장면 → `scenes/<id>.html`

장면은 HTML 파일 하나이고, 시간 t(초)의 화면을 그리는 함수 하나로 만든다. 예시는 `reels/episodes/vocoding/scenes/`에 있다.

```html
<!doctype html><meta charset="utf-8">
<link rel="stylesheet" href="../../../kit/kit.css">
<div id="stage"><div class="safe">
  <div id="title" class="h2">제목</div>
  <svg width="870" height="900" viewBox="0 0 870 900"><path id="w" fill="none" stroke="var(--a)" stroke-width="5"/></svg>
</div></div>
<script src="../../../kit/kit.js"></script>
<script>
Reel.scene((t, R) => {
  R.set("#title", { o: R.ramp(t, 0, 0.3), s: R.pop(t, 0) || 0.01 });
  R.$("#w").setAttribute("d", R.wavePath(R.clip("audio/A.wav"), 0, 870, 450, 300));
});
</script>
```

kit이 주는 것 (`reels/kit/kit.js`):

| 이름 | 하는 일 |
| --- | --- |
| `R.ramp(t, a, b)` | a~b초 사이에 0→1로 부드럽게 |
| `R.pop(t, t0, d)` | t0에 살짝 넘쳤다 돌아오는 등장 크기(0→1) |
| `R.at(frac)` | 나레이션의 frac 지점이 장면의 몇 초인지 (단어가 나오는 순간 맞추기) |
| `R.level(t)` | 그 순간 장면 소리의 세기(0~1) |
| `R.clip(file)` | 오디오 파형 샘플(4 kHz, -1~1). `clips`나 `waves`에 넣은 파일만 |
| `R.wavePath(s, x0, x1, mid, amp)` | 샘플 → SVG path |
| `R.set(el, {o, x, y, s, r})` | 투명도·이동·크기·회전 |
| `R.data.scene` | `duration`, `vo_start`, `vo_duration`, `captions` |

자막과 상단 진행 바는 kit이 자동으로 그린다. 장면에서 따로 만들지 않는다.

## 5. 검사와 미리보기

```bash
python3 reels/reel.py check   reels/episodes/<slug>
python3 reels/reel.py preview reels/episodes/<slug>    # → build/preview.png (장면마다 15%·50%·85% 시점)
```

preview.png를 직접 열어 본다. 글자가 겹치거나 잘리는지, 화면이 비는지, 장면마다 메시지가 하나인지 확인한다.
문제가 있으면 장면을 고치고 다시 preview한다. 미리보기는 두 번까지만 반복한다.

## 6. 완성

```bash
python3 reels/reel.py build reels/episodes/<slug>      # → out/<slug>.mp4
```

끝나면 사용자에게 다음을 보고한다: MP4 경로, 길이, 고른 훅, 단순화한 부분, 사용한 TTS 백엔드.
`build/`, `out/`, `.models/`는 커밋하지 않는다(.gitignore). 커밋하는 것은 brief.md, script.md, episode.json, scenes/, audio/뿐이다.

## 하지 말 것

- 대본에 확인하지 않은 수치나 사실을 쓰지 않는다. 모르면 brief.md에 "확인 필요"로 적고 그 내용은 빼고 만든다.
- 장면에서 실제 시간(CSS animation, setTimeout, Date.now())으로 움직이지 않는다.
- `reels/reel.py`나 `reels/kit/`을 한 에피소드에 맞추려고 고치지 않는다. 공통 기능이 정말 필요하면 별도 변경으로 하고 이유를 적는다.
