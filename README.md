# semiwire n8n 파이프라인 적용법

## 0. n8n 실행 (로컬)
```bash
docker run -it --rm --name n8n -p 5678:5678 -v ~/.n8n:/home/node/.n8n n8nio/n8n
```
브라우저에서 http://localhost:5678 접속.

## 1. 워크플로우 임포트
n8n 화면 우측 상단 `...` → `Import from File` → `semiwire_workflow.json` 선택.
노드가 좌→우로 쭉 나열된 게 보이면 정상.

## 2. 필요한 계정/키 준비
| 무엇 | 어디서 | 용도 |
|---|---|---|
| Anthropic API 키 | console.anthropic.com | 기사 요약·카드 문구 생성 |
| htmlcsstoimage.com 계정 | hcti.io (무료 티어 있음) | HTML → PNG 렌더링 |
| Slack App | api.slack.com/apps | 카드 미리보기 + 승인/반려 버튼 |

## 3. n8n Credentials 등록
- `Claude로 카드 문구 생성` 노드: Header Auth 자격증명 만들어서 `x-api-key`에 Anthropic 키 입력
  (또는 노드 파라미터의 `$credentials.anthropicApi.apiKey` 부분을 실제 값으로 바로 바꿔도 됨 — 연습 단계에선 이게 더 빠름)
- `카드 이미지 렌더링` 노드: hcti.io User ID:API Key를 base64 인코딩해서 `$credentials.htmlCssToImage.basicAuth` 자리에 입력

## 4. Slack App 설정 (제일 중요한 부분)
1. api.slack.com/apps → Create New App → From scratch
2. **OAuth & Permissions** → Bot Token Scopes에 `chat:write`, `chat:write.public` 추가 → 워크스페이스에 설치 → Bot Token(`xoxb-...`) 복사
3. n8n의 Slack 노드 Credentials에 이 토큰 등록
4. **Interactivity & Shortcuts** 켜기 → Request URL에 n8n의 `승인 대기 (Wait)` 노드가 활성화(Activate) 후 생성해주는 웹훅 URL을 붙여넣기
   - Wait 노드를 더블클릭하면 "Webhook URLs" 항목에 URL이 보여요. 워크플로우를 Activate 해야 이 URL이 실제로 동작합니다.
5. `Slack에 승인 요청` 노드의 `channelId`를 실제 채널 ID로 교체

## 5. RSS 주소 채워넣기
`설정 (RSS 목록)` 노드의 `feeds` 배열에서 TODO로 표시된 한국 매체 RSS 주소를 실제 값으로 교체하세요.
보통 `사이트주소/feed` 또는 `사이트주소/rss.xml` 형태입니다. 사이트에 RSS 아이콘이 없으면 위 두 경로를 직접 브라우저에 쳐서 XML이 뜨는지 확인하면 됩니다.

## 6. 테스트 실행
1. 워크플로우 상단 `Execute Workflow` (수동 실행) 클릭
2. Slack 채널에 카드 이미지 + 승인/반려 버튼이 뜨는지 확인
3. 버튼을 누르면 Wait 노드가 재개되면서 워크플로우가 이어짐 — n8n Executions 탭에서 로그 확인

## 7. 아직 안 만든 부분 (의도적으로 비워둠)
- `발행 (TODO: Instagram API)` 노드: Instagram Graph API 심사가 끝나기 전까지는 승인된 카드를 로컬 폴더에 저장하는 정도로만 채워두고, 심사 통과 후 실제 API 호출 코드로 교체하면 됩니다.
- 중복 방지는 워크플로우의 static data(메모리)에 저장되는 방식이라 n8n을 재시작하면 초기화될 수 있어요. 계속 쓰려면 Google Sheets나 SQLite 노드로 바꿔서 영구 저장하는 걸 추천합니다.
