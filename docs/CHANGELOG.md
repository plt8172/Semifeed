# Changelog

## 2026-09-17
- 초기 프로젝트 구조 생성 (n8n 워크플로우, README, 예시 카드 템플릿 이관)
- 반도체·회로·산업·기업·테크 분야의 신뢰할 수 있는 RSS 피드 10개로 소스 구성 확장
- LLM 요약 호출을 Anthropic 직접 API에서 OpenRouter Chat Completions API로 전환
- 카드 이미지 렌더링을 htmlcsstoimage.com에서 로컬 browserless/chrome 컨테이너로 전환
- Slack 전송 방식을 image URL 블록에서 파일 업로드 방식으로 변경
- 워크플로우의 환경변수 의존성을 제거하고 n8n Credential 및 중앙 설정 노드 방식으로 변경
- Slack 승인 메시지의 fallback 텍스트와 파일 스레드 자동 추출을 보강
- 중앙 설정의 `max_items`로 테스트 시 처리 기사 수를 제한
- Slack 승인 메시지에 Block Kit 최상위 `blocks` 래퍼를 추가해 승인/반려 버튼 렌더링 수정
- Slack 파일 공유 정보 조회를 제거하고 승인 요청 부모 메시지의 `ts`를 이미지와 버튼 스레드에 직접 사용하도록 변경
- Slack 승인 처리를 별도 Wait 웹훅에서 내장 Send and Wait 방식으로 전환해 실행별 서명 URL로 콜백 연결
