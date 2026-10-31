# 카드 레이아웃

`scripts/render.py`는 `templates/layouts/<이름>.html` 중 하나에 카드 내용을 채워 1080×1350(4:5 세로) JPEG로 찍는다.
레이아웃은 `--layout` > 카드 JSON의 `layout` > `config/semifeed.json`의 `card_layout` 순서로 정한다.

| 이름 | 모습 | 상태 |
| --- | --- | --- |
| `photo` | 위쪽 900px에 사진, 아래로 배경색에 녹아드는 그라데이션 위에 제목·요약. 장식 없음. 사진이 없으면 어두운 단색 그라데이션 | 기본값 (2026-10-29~) |
| `classic` | 상단 바·브랜드 마크·패턴 히어로(사진 자리)·하단 본문. 첫 운영 디자인 | 보존용 |

## 새 레이아웃 추가

`layouts/`에 HTML 파일 하나를 추가하면 바로 `--layout <파일 이름>`으로 쓸 수 있다. 렌더러와의 약속은 다음뿐이다.

- 루트 요소 `.card`가 1080×1350이다. 이 요소만 캡처된다 (`render.py`의 `CARD_WIDTH`, `CARD_HEIGHT`).
- 프로필 그리드는 카드 가운데를 3:4로 잘라 좌우 약 34px이 안 보인다. 글자는 좌우 64px 이상 안쪽에 둔다.
- 사진은 가로 원본 폭 1280px로 받는다. 세로 카드 전체에 깔면 확대돼 흐려지므로 사진 영역 높이를 900px 안팎으로 둔다.
- 렌더러가 `data-field`로 값을 넣는다: `headline`, `bullets`(`<ul>`, `<li>`로 채움), `category`, `published-at`, `source`,
  `image`(`<img hidden>`; 사진이 있으면 data URI가 들어가고 `hidden`이 풀린다), `image-credit`(크레딧이 있을 때만 덮어씀).
  없는 필드는 건너뛰므로 레이아웃이 쓰지 않는 값은 빼도 된다.
- 넘침 감지: `h1`(제목)과 `.story`(본문 묶음)에 고정 높이나 `max-height` + `overflow: hidden`을 둔다.
  내용이 넘치면 렌더러가 JPEG를 만들지 않고 종료 코드 2를 낸다.
- 폰트는 `../../fonts/PretendardVariable.woff2`를 `@font-face`로 읽는다. 외부 리소스·JavaScript는 쓰지 않는다.
- 사진 위 글자에는 그라데이션이나 오버레이를 깔아 대비를 확보한다 (`DESIGN.md`).

브라우저에서 파일을 직접 열면 예시 문구로 채워진 모습을 볼 수 있다.
