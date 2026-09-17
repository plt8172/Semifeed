# semiwire n8n 파이프라인 적용법

## 0. n8n + browserless 실행 (로컬)
```bash
docker compose up -d
```
실행 후 n8n은 http://localhost:5678, browserless는 http://localhost:3000에서 확인할 수 있어요.

browserless PNG 렌더링은 다음처럼 단독으로 확인할 수 있어요.

```bash
curl -X POST http://localhost:3000/screenshot \
  -H "Content-Type: application/json" \
  -d '{"html":"<h1>test</h1>"}' \
  --output test.png
```

## 1. 워크플로우 임포트
n8n 화면 우측 상단 `...` → `Import from File` → `n8n/semifeed_workflow.json` 선택.
노드가 좌→우로 쭉 나열된 게 보이면 정상.

## 2. 필요한 계정/키 준비
| 무엇 | 어디서 | 용도 |
|---|---|---|
| OpenRouter API 키 | openrouter.ai | 기사 요약·카드 문구 생성 |
| Slack App | api.slack.com/apps | 카드 미리보기 + 승인/반려 버튼 |

## 3. n8n Credentials와 설정값
- OpenRouter API 키는 `OpenRouter로 카드 문구 생성` 노드의 **Header Auth Credential**에 등록합니다. 헤더 이름은 `Authorization`, 값은 `Bearer <OpenRouter API 키>`입니다.
- Slack Bot User OAuth Token은 `Slack 승인 요청 시작`, `Slack에 카드 파일 업로드`, `Slack 승인 버튼 메시지` 노드에서 공통으로 선택하는 **Slack Credential**에 등록합니다.
- API 키와 토큰은 워크플로우나 저장소에 넣지 않습니다. `.env` 없이도 Docker Compose를 실행할 수 있습니다.
- `설정 (RSS 목록)` 노드에 RSS 목록, `hours_window`, `slack_channel_id`, `max_items`를 모아 둡니다. 채널을 바꿀 때는 `slack_channel_id`, 테스트 카드 수를 줄일 때는 `max_items`만 수정하세요.
- `카드 이미지 렌더링 (browserless)` 노드는 로컬 browserless에서 1080×1080 PNG를 생성합니다.

## 4. Slack App 설정 (제일 중요한 부분)
1. api.slack.com/apps → Create New App → From scratch
2. **OAuth & Permissions** → Bot Token Scopes에 `chat:write`, `chat:write.public`, `files:write` 추가 → 워크스페이스에 재설치 → Bot Token(`xoxb-...`) 복사
3. n8n의 `Slack 승인 요청 시작`, `Slack에 카드 파일 업로드`, `Slack 승인 버튼 메시지` 노드에 같은 Slack Credential 선택
4. `설정 (RSS 목록)` 노드의 `slack_channel_id`에 실제 채널 ID를 설정
5. 파일 업로드할 채널에 Slack Bot을 초대

승인 처리는 n8n Slack 노드의 **Send and Wait for Response** 기능을 사용합니다. 버튼에는 실행별 서명 URL이 들어가므로 Slack App의 Interactivity Request URL은 필요하지 않습니다. 로컬 n8n을 사용할 때는 n8n과 같은 컴퓨터에서 Slack 버튼을 눌러야 합니다. 다른 기기에서도 승인하려면 n8n에 외부에서 접근 가능한 HTTPS URL을 설정해야 합니다.

## 5. RSS 주소 채워넣기
`설정 (RSS 목록)` 노드의 `feeds` 배열에서 TODO로 표시된 한국 매체 RSS 주소를 실제 값으로 교체하세요.
보통 `사이트주소/feed` 또는 `사이트주소/rss.xml` 형태입니다. 사이트에 RSS 아이콘이 없으면 위 두 경로를 직접 브라우저에 쳐서 XML이 뜨는지 확인하면 됩니다.

## 6. 테스트 실행
1. 워크플로우 상단 `Execute Workflow` (수동 실행) 클릭
2. Slack 채널에 캡션이 부모 메시지로 게시되고, 같은 스레드에 PNG 카드와 승인/반려 버튼이 뜨는지 확인
3. 버튼을 누르면 브라우저에서 승인 결과가 기록되고 `Slack 승인 버튼 메시지` 노드가 재개됨 — n8n Executions 탭에서 로그 확인

## 7. 아직 안 만든 부분 (의도적으로 비워둠)
- `발행 (TODO: Instagram API)` 노드: Instagram Graph API 심사가 끝나기 전까지는 승인된 카드를 로컬 폴더에 저장하는 정도로만 채워두고, 심사 통과 후 실제 API 호출 코드로 교체하면 됩니다.
- 중복 방지는 워크플로우의 static data(메모리)에 저장되는 방식이라 n8n을 재시작하면 초기화될 수 있어요. 계속 쓰려면 Google Sheets나 SQLite 노드로 바꿔서 영구 저장하는 걸 추천합니다.
