# semiwire n8n 파이프라인 적용법

## 0. n8n + browserless 실행 (로컬)
```bash
docker compose up -d
```
실행 후 n8n은 http://localhost:5678, browserless는 http://localhost:3000에서 확인할 수 있어요.

현재 외부 주소는 `https://plutos-macbook-air.tail8016b0.ts.net/`이며, Tailscale Funnel이 로컬 n8n의 5678 포트로 전달합니다. Compose에는 이 주소가 `N8N_WEBHOOK_URL`과 `N8N_EDITOR_BASE_URL`로 설정되어 있어 Slack 승인 버튼의 실행별 응답 URL도 외부 HTTPS 주소로 생성됩니다.

browserless JPEG 렌더링은 다음처럼 단독으로 확인할 수 있어요.

```bash
curl -X POST http://localhost:3000/screenshot \
  -H "Content-Type: application/json" \
  -d '{"html":"<h1>test</h1>","options":{"type":"jpeg","quality":90}}' \
  --output test.jpg
```

## 1. 워크플로우 임포트
n8n 화면 우측 상단 `...` → `Import from File` → `n8n/semifeed_workflow.json` 선택.
노드가 좌→우로 쭉 나열된 게 보이면 정상.

## 2. 필요한 계정/키 준비
| 무엇 | 어디서 | 용도 |
|---|---|---|
| OpenRouter API 키 | openrouter.ai | 기사 요약·카드 문구 생성 |
| Slack App | api.slack.com/apps | 카드 미리보기 + 승인/반려 버튼 |
| Instagram Access Token | Meta for Developers의 Instagram API setup | 승인된 카드 게시 |

## 3. n8n Credentials와 설정값
- OpenRouter API 키는 `OpenRouter로 카드 문구 생성` 노드의 **Header Auth Credential**에 등록합니다. 헤더 이름은 `Authorization`, 값은 `Bearer <OpenRouter API 키>`입니다.
- Slack Bot User OAuth Token은 `Slack 승인 요청 시작`, `Slack에 카드 파일 업로드`, `Slack 승인 버튼 메시지` 노드에서 공통으로 선택하는 **Slack Credential**에 등록합니다.
- API 키와 토큰은 워크플로우나 저장소에 넣지 않습니다. `.env` 없이도 Docker Compose를 실행할 수 있습니다.
- RSS 목록과 비민감 운영 설정은 `config/semifeed.json`에서 관리합니다. 이 디렉터리는 컨테이너의 `/data/config`에 읽기 전용으로 마운트되며, 워크플로우의 `설정 파일 읽기` → `설정 (RSS 목록)` 노드가 실행할 때마다 파일을 읽습니다.
- `Instagram 게시 컨테이너 생성`, `Instagram 게시 발행` 노드는 같은 **Header Auth Credential**을 사용합니다. 헤더 이름은 `Authorization`, 값은 `Bearer <Instagram Access Token>`입니다.
- `config/semifeed.json`의 `instagram_user_id`, `instagram_api_version`, `n8n_public_base_url`을 실제 값으로 변경합니다. `n8n_public_base_url`은 경로를 제외한 외부 HTTPS n8n 기본 주소입니다.
- App ID와 App Secret은 워크플로우 JSON에 넣지 않습니다. 게시 호출에는 Access Token Credential만 사용합니다.
- `카드 이미지 렌더링 (browserless)` 노드는 Instagram 게시 규격에 맞춰 로컬 browserless에서 1080×1080 JPEG를 생성합니다.

## 4. Slack App 설정 (제일 중요한 부분)
1. api.slack.com/apps → Create New App → From scratch
2. **OAuth & Permissions** → Bot Token Scopes에 `chat:write`, `chat:write.public`, `files:write` 추가 → 워크스페이스에 재설치 → Bot Token(`xoxb-...`) 복사
3. n8n의 `Slack 승인 요청 시작`, `Slack에 카드 파일 업로드`, `Slack 승인 버튼 메시지` 노드에 같은 Slack Credential 선택
4. `config/semifeed.json`의 `slack_channel_id`에 실제 채널 ID를 설정
5. 파일 업로드할 채널에 Slack Bot을 초대

승인 처리는 n8n Slack 노드의 **Send and Wait for Response** 기능을 사용합니다. 버튼에는 실행별 서명 URL이 들어가므로 Slack App의 Interactivity Request URL은 필요하지 않습니다. 현재 Compose의 `N8N_WEBHOOK_URL`이 Tailscale Funnel HTTPS 주소를 가리키므로 휴대폰이나 다른 PC의 Slack에서도 승인/반려할 수 있습니다.

외부 Slack 사용 조건은 다음과 같습니다.

- Tailscale Funnel 상태에 `https://plutos-macbook-air.tail8016b0.ts.net` → `http://127.0.0.1:5678` 프록시가 표시되어야 합니다.
- n8n 컨테이너와 승인 대기 중인 실행이 계속 살아 있어야 합니다.
- Slack Bot은 대상 채널에 초대되어 있어야 합니다. 다른 채널로 바꾸려면 `설정 (RSS 목록)`의 `slack_channel_id`를 변경하고 Bot을 그 채널에도 초대합니다.
- 과거 실행에서 생성된 버튼은 해당 실행이 종료되면 다시 사용할 수 없습니다. 새 실행으로 받은 버튼을 사용합니다.

## 5. RSS 주소 채워넣기
`config/semifeed.json`의 `feeds` 배열에서 RSS 주소를 관리합니다.
보통 `사이트주소/feed` 또는 `사이트주소/rss.xml` 형태입니다. 사이트에 RSS 아이콘이 없으면 위 두 경로를 직접 브라우저에 쳐서 XML이 뜨는지 확인하면 됩니다.

## 6. 테스트 실행
1. 워크플로우 상단 `Execute Workflow` (수동 실행) 클릭
2. Slack 채널에 캡션이 부모 메시지로 게시되고, 같은 스레드에 JPEG 카드와 승인/반려 버튼이 뜨는지 확인
3. 버튼을 누르면 브라우저에서 승인 결과가 기록되고 `Slack 승인 버튼 메시지` 노드가 재개됨 — n8n Executions 탭에서 로그 확인

## 7. Instagram 게시 설정
1. Meta 앱의 Instagram API setup에서 `instagram_business_basic`, `instagram_business_content_publish` 권한으로 `semifeed` 계정 Access Token을 발급합니다.
2. 다음 요청으로 `instagram_user_id`를 확인합니다. `<VERSION>`과 `<ACCESS_TOKEN>`은 실제 값으로 바꿉니다.

```bash
curl -G "https://graph.instagram.com/<VERSION>/me" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  --data-urlencode "fields=user_id,username"
```

3. n8n에서 Header Auth Credential을 하나 만들고 `Instagram 게시 컨테이너 생성`, `Instagram 게시 발행` 두 노드에 지정합니다.
4. `config/semifeed.json`에서 아래 값을 변경합니다.
   - `instagram_user_id`: 위 API 응답의 `user_id`
   - `instagram_api_version`: Meta 앱에 표시된 지원 버전(기본값 `v25.0`)
   - `n8n_public_base_url`: 경로를 제외한 n8n 외부 HTTPS 기본 주소. 워크플로우가 여기에 `/webhook/semifeed-media`를 붙여 Instagram 이미지 URL을 생성합니다.
5. 워크플로우를 활성화합니다. Production Webhook은 워크플로우가 활성화되어야 Meta가 이미지를 가져갈 수 있습니다.
6. 로컬 n8n 주소(`localhost`)는 Meta에서 접근할 수 없습니다. 기존 도메인, 리버스 프록시 또는 HTTPS 터널을 통해 n8n Production Webhook이 인터넷에서 열려 있어야 합니다.

승인 전 JPEG는 `data/instagram/`에 저장되고, 무작위 파일명을 아는 요청에만 Webhook이 파일을 반환합니다. 이 Webhook은 댓글·DM 이벤트 수신용이 아니라 Instagram 게시 API가 이미지 파일을 가져가기 위한 용도입니다. 운영 시 오래된 JPEG를 주기적으로 삭제하세요.

승인 후 실행 순서는 다음과 같습니다.

```text
JPEG 임시 저장 → Slack 승인 → Instagram /media → Instagram /media_publish → 게시 ID 기록
```

## 8. 운영 시 보강할 부분
- 중복 방지는 워크플로우의 static data(메모리)에 저장되는 방식이라 n8n을 재시작하면 초기화될 수 있어요. 계속 쓰려면 Google Sheets나 SQLite 노드로 바꿔서 영구 저장하는 걸 추천합니다.
- `data/instagram/`의 오래된 임시 이미지는 자동 정리되지 않습니다. 게시 안정화 후 보존 기간 기반 정리 작업을 추가하는 것을 권장합니다.

## 9. 서버 운영 체크리스트

Compose 서비스에는 `restart: unless-stopped`가 설정되어 있어 Docker 엔진이 재시작되면 n8n과 browserless도 자동으로 다시 올라옵니다. 단, 이 구성은 Mac 자체가 서버 역할을 하므로 Mac이 잠자기 상태이거나 꺼져 있거나 Docker Desktop/Tailscale이 종료되면 Slack 승인과 Instagram 이미지 전달도 중단됩니다.

재시작 및 상태 확인 명령은 다음과 같습니다.

```bash
docker compose up -d
docker compose ps
curl -fsS http://localhost:5678/healthz
curl -fsS http://localhost:3000/pressure
tailscale funnel status
curl -fsS https://plutos-macbook-air.tail8016b0.ts.net/healthz
```

Mac 로그인 시 Docker Desktop과 Tailscale을 자동 실행하도록 설정하고, 운영 중에는 시스템 잠자기를 방지해야 합니다. 워크플로우도 n8n에서 활성화된 상태여야 Production Webhook과 정기 실행이 유지됩니다.

## 10. `.env`와 설정 파일의 역할

- `.env`는 `N8N_ENCRYPTION_KEY`, 데이터베이스 비밀번호처럼 서버 시작에 필요한 민감한 인프라 값에만 사용하고 Git에는 커밋하지 않습니다.
- Slack, OpenRouter, Instagram 토큰은 n8n Credentials에 저장합니다.
- 워크플로우 JSON에는 비밀값이 아닌 Credential ID·이름 참조가 포함되어 있어, 같은 ID의 Credential을 DB 이전 또는 CLI import로 준비하면 각 노드에 자동 연결됩니다.
- 워크플로우 ID도 고정되어 있어 CLI로 다시 임포트할 때 별도 복제본을 만들지 않고 같은 워크플로우를 갱신할 수 있습니다.
- RSS 목록, 처리 개수, 채널 ID, Instagram 계정 ID와 공개 URL처럼 비밀이 아닌 실행 설정은 `config/semifeed.json`에서 관리합니다.
- Docker Compose의 `.env` 값은 컨테이너에 명시적으로 전달해야 하며, n8n 워크플로우에서 `$env`로 직접 읽는 방식은 보안 설정에 따라 차단될 수 있으므로 사용하지 않습니다.

Slack 승인 버튼의 외부 응답 URL은 `config/semifeed.json`을 읽지 않습니다. n8n이 Compose의 `N8N_WEBHOOK_URL`을 기준으로 실행별 URL을 자동 생성합니다. `config/semifeed.json`의 `n8n_public_base_url`과 Compose의 `N8N_WEBHOOK_URL`은 같은 공개 origin을 가리켜야 합니다.
