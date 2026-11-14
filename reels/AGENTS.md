# 릴스 파이프라인: 에이전트 실행 절차

사용자가 "○○ 원리로 릴스 만들어 줘"처럼 주제를 한두 줄로 주면, 이 문서를 처음부터 끝까지 순서대로 따라서 중간에 묻지 않고 완성 MP4까지 만든다.
판단이 필요한 일(자료 정리, 대본, 무대 설계, 검수)은 에이전트가 하고, 합치는 일(TTS, 시간표, 렌더, 믹스)은 `reels/reel.py`가 한다.
품질 기준은 `reels/GUIDE.md`에 있다. 1단계를 시작하기 전에 반드시 끝까지 읽는다.
완성된 예시는 `reels/episodes/vocoding/`이다. 새 에피소드는 이 폴더의 구성과 수준을 따른다.

## 0. 준비

```bash
pip install -q -r reels/requirements.txt
python3 -m playwright install chromium >/dev/null 2>&1 || true   # 실패해도 된다. /opt/pw-browsers/chromium이 있으면 그것을 쓴다
ffmpeg -hide_banner -encoders | grep -q libx264 || echo "ffmpeg(libx264) 필요"
python3 reels/reel.py setup                                      # 내장 TTS 모델 (Supertonic 3, 약 130MB. 키가 필요 없다)
python3 reels/reel.py setup asr                                  # 받아쓰기 모델 (listen에 필요, 약 640MB)
```

TTS는 `"backend": "auto"`일 때 쓸 수 있는 것 중 앞의 것을 고른다.

1. 구글 Cloud TTS (`"google"`): 환경 변수 `GOOGLE_TTS_API_KEY`가 있을 때. 기본 목소리는 Chirp 3: HD(`ko-KR-Chirp3-HD-*`)이고 한 달 100만 자까지 무료다(한 편에 500자 남짓). 사용자가 2026-11-14에 "Supertonic은 너무 어색하다"고 해서 기본으로 올렸다. 목소리 목록은 `python3 reels/reel.py voices`.
2. OpenAI (`"openai"`, `gpt-4o-mini-tts`): `OPENAI_API_KEY`가 있을 때. 유료다.
3. 내장 모델 (`"local"`): 수퍼톤의 Supertonic 3(모델 라이선스 OpenRAIL-M)를 내려받아 직접 돌린다. 키도 비용도 없지만 어색하게 들린다는 평을 받았다.
4. 모델도 키도 없으면 무음(레이아웃 확인용)으로 만든다.
보고할 때 어떤 TTS를 썼는지 반드시 적는다. 키는 환경 변수로만 받고 저장소에 쓰지 않는다.

## 1. 자료 정리 → `reels/episodes/<slug>/brief.md`

`<slug>`는 영문 소문자와 하이픈으로 짓는다(예: `vocoding`, `pn-junction`).

- 주제 한 줄, 시청자가 끝까지 보고 알게 될 것 한 문장
- 고른 형식(GUIDE.md의 세 가지 중 하나)과 이유
- 근거 자료: 사용자가 준 자료와 거기서 가져온 핵심 사실
- 틀리면 안 되는 수치(단위 포함)와 흔한 오해
- 진짜 데이터로 보여 줄 수 있는 것: 계산해서 그릴 수 있는 식, 실제 신호, 들려줄 수 있는 소리

## 2. 대본 → `script.md`

GUIDE.md의 대본 규칙으로 쓴다. 가장 자주 받은 지적이 "대사가 AI 같다"이므로, GUIDE.md의 "말투"를 특히 지킨다.

1. 훅 후보 3개를 쓰고, 하나를 고른 이유를 한 줄씩 적는다.
2. 나레이션 전체를 줄로 나누지 않고, 친구에게 말로 설명하듯 처음부터 끝까지 한 번에 쓴다. 그다음 숨 쉬는 곳에서 줄을 나눈다.
3. 장 표를 쓴다. 장마다 나레이션과, 그때 화면에서 **무엇이 어떻게 변하는지**를 적는다. 앞 장의 그림이 다음 장의 무엇이 되는지가 드러나야 한다.
4. "단순화한 부분" 목록을 적는다.
5. GUIDE.md의 "대본 점검"을 하나씩 확인하고, 걸리면 고친다. 소리 내어 읽었을 때 어색한 문장이 남아 있으면 안 된다.

## 3. 에피소드 정의 → `episode.json`

에피소드는 나레이션 줄 목록과 무대 하나다. 줄 하나는 한 번에 말하는 한 문장(또는 구)이다.

```json
{
  "title": "영상 제목",
  "fps": 30,
  "voice": {"backend": "auto", "google_voice": "ko-KR-Chirp3-HD-Aoede", "sid": 2, "speed": 1.12},
  "bgm": {"type": "pad", "gain": 0.03},
  "stage": "stage.html",
  "waves": ["audio/extra.wav"],
  "lines": [
    {"id": "h1", "say": "TTS가 읽을 문장.", "caption": "", "after": 0.25},
    {"id": "p2", "say": "이 떨림을 일초에 팔천번 재야 해요.", "caption": "이 떨림을 1초에 8,000번 재야 해요.",
     "sfx": [{"type": "pop", "at": "w:8,000", "gain": 0.18}]},
    {"id": "m2", "say": "성대 소리만 들으면 이래요.", "clips": [{"file": "audio/buzz.wav", "gain": 0.5, "gap": 0.2}]}
  ]
}
```

- `voice`: 구글은 `google_voice`(목소리 이름)와 `google_speed`(말 빠르기, 기본 1.0), 내장 모델은 `sid`(목소리 번호 0~9. 0~5는 높은 목소리, 6~9는 낮은 목소리)와 `speed`(2번 목소리는 1.12)를 쓴다. 어느 쪽이든 1초에 6~6.5음절이 되게 맞춘다. 키는 백엔드마다 따로 두므로 한 `voice`에 함께 적어도 된다. 사용자가 목소리를 정해 주지 않으면 예시의 값을 쓴다.
- `plan`은 받아쓰기 모델이 있으면 줄마다 받아 적어 대본과 얼마나 맞는지 보여 준다. 내장 모델은 읽을 때마다 소리가 조금씩 다르다. `reel.py`가 줄마다 받아 적어 보고(받아쓰기 모델이 있을 때) 대본과 0.95 이상 맞을 때까지 최대 네 번 다시 읽혀 가장 가까운 것을 쓴다. `plan`의 출력에서 일치가 0.85보다 낮은 줄은 `say`의 표기를 바꿔 본다(숫자를 한글로, 외래어를 소리 나는 대로).
- `say`: TTS가 읽는 글. 숫자는 한글로 풀어 쓴다("팔천번"). `caption`: 화면 자막. 생략하면 `say`와 같고, `""`이면 그 줄은 자막을 띄우지 않는다(화면의 큰 글자가 같은 말을 할 때).
- `say`와 `caption`의 단어 수(띄어쓰기 기준)를 맞추면 단어 강조 시각이 정확해진다. 자막은 문장부호(, . ? !)에서 끊기고, 14자가 넘는 구는 자동으로 나뉜다.
- 줄의 길이는 나레이션 길이 + 클립 + `after`(줄 뒤 쉼, 기본 0.3초)로 자동으로 정해진다. `dur`을 주면 최소 길이가 된다.
- `clips`: 나레이션이 끝난 뒤 순서대로 재생할 소리. `gap`은 앞 소리와의 간격(기본 0.25초). 재생하는 동안 배경음은 줄어든다.
  `at`을 주면 나레이션 도중 그 시각에 시작한다(`sfx`의 `at`과 같은 형식, 예: `"w:놓고"`). "음악을 틀어 놓고 ~하는 순간,"처럼 말 밑에 소리가 깔려야 할 때 쓴다.
- `waves`: 재생하지 않고 화면에 그리기만 할 소리. 무대에서 `R.clip(file)`로 읽는다(`clips`의 파일도 읽을 수 있다).
- `sfx`: 종류는 `pop`, `whoosh`, `hit`, `tick`, `ding`. `at`은 줄 시작부터의 초, `"end"`, `"end+0.3"`, `"w:단어"`(그 글자가 든 자막 단어가 나오는 순간), `"clip:0"`. 효과음은 화면의 사건과 맞을 때만 넣는다.
- `bgm`: `{"type": "pad"}`(낮게 깔리는 화음), `{"type": "file", "file": "audio/bgm.wav"}`, `{"type": "none"}`.

## 4. 데모 소리 → `audio/`, `make_audio.py`

들려줄 소리는 진짜여야 한다. 만드는 방법을 `make_audio.py`로 남겨 다시 만들 수 있게 한다(예시 에피소드 참고).

- 문장 하나를 TTS로: `python3 reels/reel.py say "문장" out.wav ko-KR-Chirp3-HD-Charon` (끝은 구글 목소리 이름, 또는 내장 모델의 번호. 화면 속 인물의 말은 나레이션과 다른 목소리로 만든다)
- 같은 음성의 코덱 비교: `python3 reels/reel.py codec 원본.wav audio/` → A(PCM 64k)·B(GSM 13k)·C(Codec2 700bps)
- 만든 뒤 `python3 reels/reel.py listen audio/파일.wav`로 받아 적어서, 대본이 말하는 대로 들리는지 확인한다. "알아들을 수 있다"고 말하려면 받아쓰기가 실제로 알아들어야 한다.

## 5. 무대 → `stage.html`

무대는 HTML 파일 하나이고, 시간 t(초)의 화면 전체를 다시 그리는 함수 하나다. 장면을 나누지 않는다.
렌더러가 프레임마다 `seek(t)`를 불러 캡처하므로, 같은 t에는 항상 같은 화면이 나와야 한다.

```html
<!doctype html><meta charset="utf-8">
<link rel="stylesheet" href="../../kit/kit.css">
<svg id="s" width="1080" height="1920" viewBox="0 0 1080 1920"></svg>
<script src="../../kit/kit.js"></script>
<script>
const R = Reel, { ramp, lerp, clamp, g, path, seg, text, span, glow, C } = R;
const svg = R.$("#s");
const tA = R.at("p1"), tB = R.at("p2");                 // 줄이 시작하는 시각
const HEAD = [{ t: 0 }, { t: tA, chap: "01 · 문제", title: "소리를 그대로 보내면" }];

function wave(t) {                                       // 조각마다 SVG 문자열을 돌려준다
  const k = ramp(t, tB, tB + 0.6);                       // tB부터 0.6초 동안 0→1
  const d = R.plot((x) => Math.sin(2 * Math.PI * (3 + 2 * k) * x), 70, 1010, 760, 180);
  return g(ramp(t, tA, tA + 0.3), path(d, C.fg, 4));
}

Reel.stage((t) => {
  svg.innerHTML = wave(t);
  R.header(t, HEAD);
});
</script>
```

kit이 주는 것 (`reels/kit/kit.js`):

| 이름 | 하는 일 |
| --- | --- |
| `R.at(id, k)` | 줄 `id`의 나레이션 k 지점(0=시작, 1=끝)의 시각 |
| `R.end(id)` | 줄이 끝나는(다음 줄이 시작하는) 시각 |
| `R.word(id, "단어")` | 줄에서 그 글자가 든 자막 단어를 말하기 시작하는 시각 |
| `R.clipTime(id, n)` | 줄의 n번째 클립 `{t0, t1}` |
| `R.ramp(t, a, b)` | a~b초 사이에 0→1로 부드럽게. 모든 움직임의 기본 |
| `R.vis(t, a, b)` | a에서 나타나 b에서 사라지는 투명도 |
| `R.lerp`, `R.clamp`, `R.ease`, `R.pop` | 보간, 자르기, 부드럽게, 살짝 넘치는 등장 |
| `R.level(t)` | 그 순간 소리(나레이션·클립·효과음)의 세기 0~1 |
| `R.clip(file)`, `R.clipSr`, `R.sample(s, pos)` | 실제 오디오 샘플(4 kHz, -1~1)과 그 사이를 부드럽게 읽기 |
| `R.plot(f, x0, x1, mid, amp, n, k0, k1)` | 함수 f(0~1) → SVG path. k1을 0→1로 올리면 왼쪽부터 그려진다 |
| `R.g(o, inner, extra)` | 투명도 o인 묶음. `extra`에 `transform` 등 |
| `R.path`, `R.seg`, `R.text`, `R.span`, `R.glow` | 선·직선·글자·글자 일부 색·은은한 빛 |
| `R.C` | 색: `fg` 흰색, `mu` 흐린 글자, `dim` 보조선, `a` 주황(지금 설명하는 것), `b` 파랑(숫자·두 번째 것) |
| `R.header(t, items)` | 머리말(작은 챕터 표시 + 제목)을 시각에 맞춰 바꾼다 |
| `R.num(x)` | 1,234처럼 쉼표를 넣은 정수 |

자막(말하는 단어 강조)과 상단 진행 바는 kit이 자동으로 그린다. 무대에서 따로 만들지 않는다.

화면 배치 (1080×1920): 머리말 250~400, 그림 430~1250, 자막 1340~1490. 그 아래와 맨 위 220은 Instagram UI가 덮으므로 비운다.
그림은 좌우 70~1010 안에 그리고, 1100보다 아래에서는 오른쪽 940을 넘는 글자를 두지 않는다.

여러 에피소드에서 다시 쓸 만한 그리기 부품(막대 파형, 측정 점, 숫자 묶음 등)이 생기면 `kit.js`로 옮긴다. 옮길 때는 별도 커밋으로 하고 이 표에 적는다.

## 6. 검수 (눈과 귀)

에이전트는 영상을 재생해서 볼 수 없으므로, 정지 화면과 받아쓰기로 확인한다. 이 단계를 건너뛰지 않는다.

```bash
python3 reels/reel.py check   reels/episodes/<slug>            # 파일 검사 + 말투 경고(같은 어미 반복, 평서형 어미 비율, 쓰지 않는 말)
python3 reels/reel.py plan    reels/episodes/<slug>            # 줄마다 시작·끝 시각과 자막. 전체 길이 확인
python3 reels/reel.py preview reels/episodes/<slug>            # → build/preview.png (줄마다 2장)
python3 reels/reel.py frames  reels/episodes/<slug> 12.4 m3    # → build/frames/ (원본 크기. 초 또는 줄 id)
```

1. `preview.png`를 열어 전체 흐름을 본다. 그다음 장이 바뀌는 순간마다 0.2~0.3초 간격으로 `frames`를 찍어 전환이 이어지는지 본다.
2. GUIDE.md의 "화면 점검"을 하나씩 확인한다. 걸리는 것이 있으면 고치고 다시 찍는다. 세 번까지 반복한다.
3. `build`한 뒤 `python3 reels/reel.py listen reels/episodes/<slug>`로 줄마다 받아 적어, 나레이션과 클립이 제자리에서 들리는지 확인한다.

## 7. 완성과 보고

```bash
python3 reels/reel.py build reels/episodes/<slug>      # → out/<slug>.mp4
```

사용자에게 보고할 것: MP4, 길이, 고른 형식과 훅, 단순화한 부분, 사용한 TTS, 검수에서 확인한 것과 확인하지 못한 것(예: 소리의 느낌은 들어 보지 못함).
커밋하는 것은 `brief.md`, `script.md`, `episode.json`, `stage.html`, `make_audio.py`, `audio/`뿐이다. `build/`, `out/`, `.models/`는 커밋하지 않는다(.gitignore).

## 하지 말 것

- 대본에 확인하지 않은 수치나 사실을 쓰지 않는다. 모르면 brief.md에 "확인 필요"로 적고 그 내용은 빼고 만든다.
- 무대에서 실제 시간(CSS animation, transition, setTimeout, Date.now(), Math.random())으로 움직이지 않는다.
- 장식을 넣지 않는다: 내용을 감싸기만 하는 상자·카드, 그림자, 그라데이션 배경, 아이콘, 이모지, 데이터가 아닌 입자나 그래프.
- `reels/reel.py`나 `reels/kit/`을 한 에피소드에 맞추려고 고치지 않는다. 공통 기능이 정말 필요하면 별도 변경으로 하고 이유를 적는다.
