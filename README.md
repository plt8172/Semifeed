# Semifeed

반도체·전기전자 뉴스를 골라 1080×1350(4:5) 카드로 만들고, Slack 승인 후 Instagram에 게시하는 파이프라인입니다.

상시 서버 없이 두 부분으로 동작합니다.

- **Claude Code 예약 작업**: RSS 수집 → Claude가 기사 선별·문구 작성 → 카드 렌더링 → `cards/`에 커밋 → Slack에 승인 요청
- **Cloudflare Worker**: Slack 버튼 콜백을 받아 `raw.githubusercontent.com`의 카드 이미지로 Instagram에 게시

Claude는 판단이 필요한 일(기사 선별, 카드 문구)만 맡고, 나머지는 `scripts/`의 스크립트가 맡습니다. 실패 지점을 분명히 하고 결과를 재현할 수 있게 하기 위해서입니다.

## 진행 상황

| 단계 | 파일 | 상태 |
| --- | --- | --- |
| 1. 수집 | `scripts/fetch.py` | 완료 |
| 2. 렌더 | `scripts/render.py` | 완료 |
| 3. Slack 전송 | `scripts/slack_post.py` | 완료 |
| 4. 승인·게시 | `worker/` | 완료 (배포 전) |
| 5. 예약 작업 절차 | `RUN.md` | 완료 (예약 작업 생성 전) |

기존 n8n + Google Cloud VM 구성은 `legacy/`에 보관합니다. 운영에 필요한 연결·토큰은 `docs/SETUP.md`에 정리돼 있습니다.

## 구조

```
config/semifeed.json   RSS 목록, 수집 시간 창, Slack 채널·Instagram 계정 ID
scripts/fetch.py       RSS 수집, 72시간 필터, 중복 제거 → candidates.json
scripts/mark_seen.py   카드로 만든 기사 링크를 state/seen.json에 기록
scripts/photo.py       카드별 무료 스톡 사진(Pixabay, 선택적으로 Pexels)을 받고 출처·라이선스를 카드 JSON에 기록
scripts/render.py      카드 JSON + templates/layouts/<레이아웃>.html → JPEG
scripts/slack_post.py  카드 이미지(raw URL) + 캡션 + [승인][반려] 버튼을 Slack에 전송
state/seen.json        처리한 기사 링크 (승인 여부와 무관하게 생성 시점에 기록)
cards/<날짜>/<id>.*    카드 이미지와 메타데이터 (Worker가 raw URL로 읽음)
templates/layouts/     카드 레이아웃 (photo 기본, classic 보존). templates/README.md
fonts/                 Pretendard 가변 폰트 (SIL OFL 1.1)
worker/                Cloudflare Worker: Slack 버튼 → Instagram 게시, 토큰 갱신 (worker/README.md)
tests/                 스크립트 테스트와 샘플 피드·카드
```

## 실행

예약 작업에서는 Claude가 `RUN.md` 절차대로 아래 단계를 모두 실행합니다. 아래 명령은 손으로 한 단계씩 확인할 때 씁니다.

```bash
# 1. 수집: candidates.json 생성 (표준 라이브러리만 사용)
python3 scripts/fetch.py

# 1-1. 사진: 카드 JSON의 photo_queries(검색어 3개)로 Pixabay 검색 → <id>.photo.jpg (커밋하지 않음)
PIXABAY_API_KEY=... python3 scripts/photo.py cards/2026-10-19/<id>.json
#      이번 사진과 최근 3일 카드를 한 장에 모아 겹치는 사진을 눈으로 찾는다 → contact_sheet.jpg
python3 scripts/contact_sheet.py cards/2026-10-19/<id>.json
#      정기 실행은 후보를 모아 contact sheet에서 고른다 (RUN.md 3-1). 사진 없는 카드를 줄이려는 방식
PIXABAY_API_KEY=... python3 scripts/photo.py --candidates cards/2026-10-19/<id>.json
python3 scripts/contact_sheet.py cards/2026-10-19/<id>.json   # 후보 줄이 나온다
PIXABAY_API_KEY=... python3 scripts/photo.py --pick <photo id> cards/2026-10-19/<id>.json

# 2. 렌더: cards/2026-10-19/<id>.json → <id>.jpg
pip install -r requirements.txt
python3 scripts/render.py cards/2026-10-19/<id>.json

# 3. 카드를 커밋·푸시한 뒤 Slack 승인 요청 (raw URL이 열려야 전송)
SLACK_BOT_TOKEN=xoxb-... python3 scripts/slack_post.py cards/2026-10-19/<id>.json

# 4. 처리한 기사 기록
python3 scripts/mark_seen.py <기사 링크>...

# 테스트
python3 -m unittest discover tests
```

`render.py`는 제목·본문이 카드 영역을 넘치면 이미지를 만들지 않고 종료 코드 2로 끝냅니다. 문구를 줄여 다시 실행하라는 신호입니다.

카드 JSON 필드는 `scripts/render.py` 상단 설명과 `tests/fixtures/card_sample.json`을 참고합니다.

![샘플 카드](docs/sample-card.jpg)

## 시크릿

토큰은 저장소에 커밋하지 않습니다. Slack 토큰은 예약 작업 환경 변수에, Instagram 토큰과 Slack 서명 비밀값은 Cloudflare Worker Secret에 둡니다.
