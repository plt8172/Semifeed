# Design

## Source of truth

- Status: Draft
- Date: 2026-09-20
- Product surfaces: Instagram 1080×1080 뉴스 카드, Slack 승인 미리보기
- Evidence reviewed: `README.md`, `n8n/semifeed_workflow.json`의 기존 `HTML 카드 조립` 노드

## Brand

- Personality: 정확하고 차분한 반도체 산업 브리핑, 기술적이되 과장하지 않음
- Trust signals: 기사 출처, 이미지 출처, 발행일을 카드에 명시
- Avoid: 선정적인 썸네일, 근거 없는 수치 강조, 기사 원본 디자인 모방

## Product goals

- 핵심 뉴스를 한 장에서 빠르게 파악할 수 있게 한다.
- Slack 승인 화면과 Instagram 게시물의 시각 결과를 동일하게 유지한다.
- 사진이 없거나 로드되지 않아도 완성된 카드로 보이게 한다.
- Non-goals: 기사 전문 재현, 원문 이미지의 무단 재사용, 복잡한 데이터 시각화
- Success signals: 1080×1080에서 제목·요약·출처가 잘리지 않고 읽힘

## Personas and jobs

- 반도체 업계 종사자: 출근 전 주요 산업 변화를 빠르게 훑는다.
- 기술·투자 관심 독자: 사건의 의미를 세 문장 안에서 이해한다.
- 운영자: Slack에서 이미지와 출처를 확인한 뒤 게시 여부를 결정한다.

## Information architecture

1. 브랜드와 기사 분류
2. 대표 이미지 또는 반도체 그래픽 fallback
3. 핵심 제목
4. 최대 3개의 요약 문장
5. 기사 출처와 이미지 크레딧

## Design principles

- 한 카드에는 한 가지 주장만 전면에 둔다.
- 사진은 맥락을 보조하며 텍스트 가독성을 침범하지 않는다.
- 출처와 이미지 권리 정보는 작더라도 항상 남긴다.
- 외부 이미지 실패가 카드 렌더링 실패로 이어지지 않게 한다.

## Visual language

- Color: 짙은 남색 배경, 청록색 포인트, 고명도 본문
- Typography: Pretendard 우선, 시스템 산세리프 fallback
- Spacing: 64px 외곽 여백을 기준으로 8px 배수 사용
- Shape/elevation: 얇은 경계선과 24px 안팎의 둥근 모서리
- Motion: 정적 이미지이므로 사용하지 않음
- Imagery/iconography: 회로·웨이퍼·제조 장비 중심. 인물·기업 로고는 권리 확인 전 사용하지 않음

## Components

- `CardHeader`: 브랜드, 카테고리, 날짜
- `HeroMedia`: 대표 이미지, 이미지 크레딧, CSS fallback
- `StoryBody`: 제목과 최대 3개 요약
- `SourceFooter`: 매체명과 원문 안내
- 디자인 토큰은 우선 `templates/card.html`의 CSS custom properties가 소유한다.

## Accessibility

- 일반 본문과 배경의 대비는 WCAG AA 이상을 목표로 한다.
- 정보는 색상만으로 구분하지 않는다.
- 사진 위 텍스트에는 어두운 오버레이를 둔다.
- 장식용 이미지는 빈 대체 텍스트를 사용한다.

## Responsive behavior

- 현재 산출물은 Instagram용 1080×1080 고정 캔버스만 지원한다.
- 브라우저 미리보기에서는 캔버스 비율을 유지하며 화면 폭에 맞춰 축소한다.

## Interaction states

- Loading: 운영 워크플로우에서 렌더링 완료 후에만 전달
- Empty image: 반도체 패턴 fallback 표시
- Image error: 이미지 요소를 숨기고 fallback 유지
- Text overflow: 제목과 요약에 줄 수 제한 적용
- Error/offline: 외부 이미지 없이도 카드 본문 렌더링 유지

## Content voice

- 짧고 단정한 한국어 문장
- 과장어와 투자 권유 표현을 사용하지 않음
- 제목은 결론형, 요약은 사실과 의미를 구분
- 매체 출처와 이미지 크레딧을 혼동하지 않음

## Implementation constraints

- browserless/chrome에서 1080×1080 JPEG로 렌더링한다.
- 템플릿은 단일 HTML 파일이며 외부 JavaScript 의존성을 두지 않는다.
- 워크플로우 연결 전까지 `templates/card.html`은 독립 시안으로만 관리한다.
- 원격 이미지는 최종 렌더링 전에 다운로드·검증해 data URI로 삽입하는 방식을 우선 검토한다.

## Open questions

- [ ] 운영 이미지 소스를 Pexels, Unsplash, Wikimedia Commons 중 어디까지 허용할지 결정 — owner: 운영자, impact: 자동 수집·크레딧 방식
- [ ] 기업 보도자료 이미지를 매체별 이용조건 확인 후 허용 목록으로 관리할지 결정 — owner: 운영자, impact: 기사 연관성
- [ ] 카드에 이미지 크레딧을 항상 표시할지, 캡션에만 표시할지 결정 — owner: 운영자, impact: 레이아웃과 라이선스 준수
