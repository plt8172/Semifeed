# RUN.md: 예약 작업 실행 절차

Claude Code 예약 작업이 실행될 때마다 이 문서를 처음부터 끝까지 순서대로 따른다.
판단이 필요한 일(기사 선별, 카드 문구)만 Claude가 하고, 나머지는 반드시 `scripts/`의 스크립트로 한다.
스크립트가 실패하면 우회하지 말고, 이 실행을 멈춘 뒤 실패 내용을 보고한다. 이번 실행 중에 스크립트나 설정 파일을 고치지 않는다.

시각과 날짜는 모두 한국 시간(KST) 기준이다.

## 0. 준비

```bash
git checkout main && git pull --ff-only origin main
python3 -c "import playwright" 2>/dev/null || pip install -q -r requirements.txt
test -n "$SLACK_BOT_TOKEN" || echo "SLACK_BOT_TOKEN 없음"
test -n "$PEXELS_API_KEY" || echo "PEXELS_API_KEY 없음"
TODAY=$(TZ=Asia/Seoul date +%F)
```

`SLACK_BOT_TOKEN`이 없으면 카드를 만들지 말고 여기서 멈춘다. 카드를 만들어도 승인 요청을 보낼 수 없고,
`state/seen.json`에 기록되면 그 기사들이 다시 후보로 올라오지 않기 때문이다.

`PEXELS_API_KEY`가 없으면 멈추지 않는다. 3-1(사진 수집)만 건너뛰고 마지막 보고에 적는다. 사진은 카드의 필수 요소가 아니다.

## 1. 수집

```bash
python3 scripts/fetch.py
```

- 종료 코드 1(모든 피드 실패)이면 멈추고 보고한다.
- 일부 피드가 실패한 것은 계속 진행하되, 마지막 보고에 실패한 피드와 오류를 적는다.
- `candidates.json`의 `candidates`가 비어 있으면 "새 기사 없음"으로 보고하고 끝낸다.

## 2. 기사 선별 (Claude 판단)

`candidates.json`을 읽고 `config/semifeed.json`의 `max_items`(최대 장수) 이하로 고른다. 좋은 기사가 없으면 0장도 괜찮다.

고르는 기준:
- 반도체·전기전자 산업에 실제로 의미 있는 소식: 공정·메모리·파운드리·장비·소재·패키징·AI 칩 설계·공급망·정책·주요 기업 실적과 투자
- 같은 사건을 다룬 기사가 여러 매체에 있으면 하나만 고른다 (정보가 가장 구체적인 쪽).
- 한 매체에서 2개를 넘기지 않는다. 출처가 고르게 섞이도록 한다.
- 제외: 할인·쇼핑 기사, 제품 단순 리뷰, 광고성·스폰서 글, 루머만 있는 기사, 산업과 무관한 소비자 IT 소식

## 3. 카드 메타데이터 작성 (Claude 판단)

고른 기사마다 `cards/$TODAY/<id>.json`을 만든다. `<id>`는 후보의 `id`를 그대로 쓴다.

```json
{
  "id": "후보의 id",
  "link": "후보의 link",
  "source": "후보의 source_name",
  "category": "메모리 | 파운드리 | 장비·소재 | 패키징 | AI·설계 | 정책·공급망 | 기업·실적 | 전자·부품 중 하나",
  "published_at": "후보의 published_at",
  "headline": "제목",
  "bullets": ["요약 1", "요약 2", "요약 3"],
  "caption": "Instagram 캡션",
  "photo_query": "사진 검색어 (영어 2~4단어)"
}
```

문구 규칙 (`DESIGN.md`의 Content voice):
- 한국어. 제목은 결론형으로 한 줄 반 이내(공백 포함 약 26자). 요약은 3개, 각 45자 안팎.
- 요약은 사실 → 의미 순으로 쓴다. 과장어, 투자 권유, 근거 없는 수치를 쓰지 않는다.
- 내용은 후보의 `title`과 `summary`에 있는 사실만 쓴다. 요약이 부족하면 원문 링크를 열어 확인할 수 있고, 열 수 없으면 확인된 내용만 쓴다. 숫자·회사명·일정을 지어내지 않는다.
- 캡션 형식 (2,200자, 해시태그 30개 이하):

```
<제목>

• <요약 1>
• <요약 2>
• <요약 3>

출처: <source>
<link>

#반도체 #semiconductor #<분야 태그 2~6개>
```

`photo_query` 규칙 (`DESIGN.md`의 Imagery):
- 기사 주제를 보여 줄 수 있는 사물·장소를 영어로 쓴다. 예: `silicon wafer`, `semiconductor cleanroom`, `circuit board closeup`, `data center servers`, `lithium battery cells`.
- 회사명·제품명·인물을 넣지 않는다. 스톡 사진에는 그 회사의 실제 모습이 없고, 엉뚱한 로고나 인물 사진이 나오기 쉽다.
- 너무 넓은 단어(`technology`, `business`)는 피한다. 같은 실행의 카드끼리 검색어가 겹치지 않게 한다.

## 3-1. 사진 수집

`PEXELS_API_KEY`가 없으면 이 단계를 건너뛴다.

```bash
python3 scripts/photo.py cards/$TODAY/<이번에 만든 id>.json ...
```

스크립트가 Pexels 검색 결과에서 최근 30일 동안 쓰지 않은 첫 번째 가로 사진을 `cards/$TODAY/<id>.photo.jpg`로 받고,
출처·작가·라이선스를 카드 JSON의 `photo`에 기록한다. 사진 파일은 커밋되지 않는다 (`.gitignore`). 출처 기록만 커밋한다.

받은 사진을 카드마다 직접 열어 보고 판단한다 (Claude 판단):
- 기사 주제와 맞는가. 인물 얼굴, 회사 로고·상표, 읽히는 글자가 크게 나오면 쓰지 않는다.
- 맞지 않으면 그 사진 id를 빼고 다시 고른다: `python3 scripts/photo.py --exclude <photo.id> cards/$TODAY/<id>.json`
  (검색어를 바꿨다면 `--replace`). 카드 하나에 세 번까지 시도한다.
- 세 번 해도 맞는 사진이 없으면 `python3 scripts/photo.py --clear cards/$TODAY/<id>.json`으로 비우고 넘어간다.

종료 코드 1(키 없음)이나 3(일부 카드 실패)이어도 멈추지 않는다. 실패한 카드는 사진 없이 다음 단계로 간다.

## 4. 렌더

```bash
python3 scripts/render.py cards/$TODAY/<이번에 만든 id>.json ...
```

같은 날 앞선 실행의 카드는 다시 렌더하지 않는다 (이미 게시됐을 수 있다).

- 종료 코드 2로 `text overflow`가 난 카드는 제목이나 요약을 줄여 그 카드만 다시 렌더한다. 세 번 해도 넘치면 그 카드의 `.json`을 지우고 보고한다.
- 다른 오류면 멈추고 보고한다.
- 렌더된 JPEG를 직접 열어 보고, 글자가 깨지거나 비어 있으면 멈추고 보고한다.

## 5. 처리 기록

렌더까지 성공한 카드의 기사 링크를 기록한다. 승인 여부와 무관하게 기록해서, 반려된 기사가 다음 실행에 다시 올라오지 않게 한다.

```bash
python3 scripts/mark_seen.py <카드 link> <카드 link> ... --prune-days 30
```

## 6. 커밋·푸시

카드 이미지가 `main`의 raw URL로 공개돼야 Slack 미리보기와 Instagram 게시가 된다. 그래서 반드시 `main`에 푸시한다.

```bash
git add cards/$TODAY state/seen.json
git commit -m "cards: $TODAY $(TZ=Asia/Seoul date +%H:%M) KST, N장"
git push origin main
```

푸시가 거절되면 `git pull --rebase origin main` 후 한 번 더 푸시한다. 그래도 실패하면 멈추고 보고한다.
`candidates.json`은 커밋하지 않는다 (`.gitignore`에 있음).

## 7. Slack 승인 요청

```bash
python3 scripts/slack_post.py cards/$TODAY/<이번에 만든 id>.json ...
```

이번 실행에서 만든 카드만 넘긴다. 같은 날 앞선 실행의 카드를 다시 보내지 않는다.
`not public yet`이 나면 1분 기다렸다가 한 번 더 실행한다.

## 8. 보고

마지막에 다음을 짧게 출력한다.

- 후보 수, 고른 카드 수와 각 카드의 제목·출처
- Slack 전송 결과
- 사진: 카드별 Pexels 사진 id와 검색어, 다시 고른 횟수, 사진 없이 간 카드와 이유
- 실패한 피드, 렌더에서 뺀 카드, 그 밖의 오류
