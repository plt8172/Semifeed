# Semifeed Worker

Slack의 [승인][반려] 버튼을 받아 Instagram에 게시하는 Cloudflare Worker입니다. 요청이 올 때만 실행되므로 관리할 서버가 없습니다.

## 동작

```
Slack 버튼 클릭 ─▶ 서명 검증 ─▶ 즉시 200 응답 (Slack은 3초 안에 응답을 요구)
                              └▶ waitUntil에서 계속
   반려: 메시지를 "❌ 반려됨"으로 변경
   승인: "⏳ 게시 중…" → cards/<날짜>/<id>.json에서 캡션 읽기
         → Instagram /media (image_url = cards/<날짜>/<id>.jpg의 raw URL)
         → 20초 동안 컨테이너 상태 확인 → /media_publish → "✅ 게시 완료 + 링크"
         → 20초 안에 처리가 안 끝나면 KV에 맡기고 5분 Cron이 마무리
         → 실패하면 "⚠️ 게시 실패: 이유"와 함께 버튼을 되살려 다시 승인 가능
Cron 매일 03:00 KST: Instagram 장기 토큰을 갱신해 KV에 저장
```

- 같은 카드를 두 번 눌러도 KV의 상태(`card:<날짜>/<id>`)로 한 번만 게시합니다.
- 무료 플랜의 `waitUntil`은 응답 후 약 30초까지만 이어지므로 상태 확인은 20초로 끊고 나머지는 Cron에 넘깁니다.
- 처음 등록한 `IG_ACCESS_TOKEN`은 첫 갱신 이후로는 쓰지 않고 KV의 `ig_token`을 씁니다. 토큰을 수동으로 교체할 때는 Secret을 바꾸고 KV의 `ig_token`을 지웁니다.

## 배포 (Cloudflare 대시보드에서 관리)

Worker는 Cloudflare Workers Builds로 이 저장소에 연결돼 있어서 `main`에 푸시하면 자동으로 배포됩니다. 클론이나 CLI는 필요 없습니다.

| 항목 | 값 |
| --- | --- |
| Worker | `semifeed` (https://semifeed.plutofeed.workers.dev) |
| 연결 | 저장소 `plt8172/Semifeed`, 브랜치 `main`, Root directory `/worker`, Deploy command `npx wrangler deploy` |
| 빌드 토큰 | `semifeed build token` |
| KV | 바인딩 `STATE` → 네임스페이스 `semifeed-STATE` |
| Secret | `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN`(xoxb-, `chat:write`), `IG_ACCESS_TOKEN`(값만, "Bearer" 없이) |
| Variable | `wrangler.toml`의 `[vars]` (`IG_USER_ID`, `IG_API_VERSION`, `CARDS_BASE_URL`) |
| Cron | `wrangler.toml`의 `[triggers]` |

- 위치: dash.cloudflare.com → Workers & Pages → `semifeed` → Settings. 빌드 기록은 Deployments, 실시간 로그는 Observability 탭.
- Secret은 대시보드의 Variables and secrets에서 바꿉니다. 배포해도 유지됩니다.
- Variable·Cron·KV 바인딩은 `wrangler.toml`이 기준입니다. 대시보드에서 바꾸면 다음 배포 때 `wrangler.toml` 값으로 되돌아가므로 이 파일을 고쳐서 푸시합니다.
- Slack App → **Interactivity & Shortcuts** → Request URL은 위 Worker 주소입니다.
- 같은 구조의 새 Worker를 만들 때: Workers & Pages → Create → Import a repository → 저장소 선택, Root directory `/worker`. KV는 Storage & databases → Workers KV에서 `<worker 이름>-STATE`로 만들고 id를 `wrangler.toml`에 넣습니다.

CLI로 직접 다룰 때는 `cd worker && npm install && npx wrangler login` 후 `npx wrangler tail`(로그), `npx wrangler secret put <이름>`을 쓸 수 있습니다.

## 개발

```bash
npm test           # Slack·Instagram·GitHub 호출을 흉내 낸 단위 테스트
npm run typecheck
```
