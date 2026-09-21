# Changelog

## 2026-09-21
- 저사양 VM의 느린 Chrome 시작을 허용하도록 browserless 세션과 n8n 이미지 렌더링 요청 제한을 10분으로 확대

## 2026-09-20
- 기사 수집 범위를 최근 24시간에서 72시간으로 확대
- 자동 실행 시간을 매일 09시·12시·17시·21시(Asia/Seoul)로 확대
- RSS 피드를 한 개씩 순회하도록 변경해 EE Times 외 등록 매체도 실제 수집

## 2026-09-19
- `gcloud compute scp` 전송 시 VM SSH 사용자명을 명시해 다른 사용자 홈으로 백업이 들어가는 문제 방지
- 서버의 프로젝트 배포는 Git clone/pull로, 비공개 n8n 데이터 이전은 `gcloud compute scp`로 역할 분리
- 운영 공개 URL을 Google Cloud VM의 Tailscale Funnel 주소 `semifeed-server.tail8016b0.ts.net`으로 전환
- Google Cloud Debian VM에 Ubuntu Docker 저장소가 등록되지 않도록 배포판 자동 감지 및 복구 절차 보강
- Google Compute Engine 단일 VM에 Docker Compose와 Tailscale Funnel로 배포하는 전체 절차 및 검증·백업·전환 체크리스트 문서화
- n8n 비민감 서버 설정을 `config/n8n.env`로 분리하고 `.env`는 encryption key만 보관하도록 정리
- n8n과 browserless 호스트 포트를 localhost에만 바인딩해 Google Cloud 외부 직접 노출 차단
- 공용 뉴스 파이프라인과 수동 실행기·일일 스케줄러를 분리해 처리 로직 중복 없이 수동/자동 실행 경로 구성
- 매일 오전 9시(Asia/Seoul)에 공용 파이프라인을 호출하는 Schedule Trigger 워크플로우 추가
- n8n 외부 기본 URL을 Tailscale Funnel 주소로 고정해 다른 기기의 Slack에서도 승인/반려 가능하도록 설정
- n8n 환경 변수 `WEBHOOK_URL`을 `N8N_WEBHOOK_URL`로 갱신하고 외부 편집기 URL·서울 시간대·컨테이너 자동 재시작 설정 추가
- RSS·처리 개수·채널/Instagram 식별자·공개 URL을 `config/semifeed.json`으로 분리
- 워크플로우가 read-only 마운트된 JSON 설정 파일을 실행 시 읽도록 변경
- 워크플로우 JSON에 OpenRouter·Slack·Instagram Credential 참조를 포함해 임포트 후 노드별 수동 재선택 제거
- Instagram 전용으로 보이던 공개 URL 설정을 공용 `n8n_public_base_url`로 변경하고 미디어 Webhook 경로는 워크플로우에서 조립

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
- 승인 후 발행 대기 처리에서 중복 기록 배열이 없는 경우 초기화하도록 보강

## 2026-09-18
- Slack 승인 후 Instagram API with Instagram Login의 `/media`, `/media_publish` 호출로 실제 게시하도록 구현
- Instagram이 가져갈 JPEG를 로컬에 임시 저장하고 외부 HTTPS n8n Webhook으로 제공하는 미디어 전달 경로 추가
- Instagram Access Token은 n8n Header Auth Credential에, 계정 ID·API 버전·미디어 URL은 중앙 설정 노드에 분리
- Tailscale Funnel 고정 HTTPS 주소를 n8n Webhook 및 Instagram 미디어 공개 URL로 연결
