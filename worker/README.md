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

## 배포

```bash
cd worker
npm install
npx wrangler login

# 1. 상태 저장용 KV 만들기 → 출력된 id를 wrangler.toml의 REPLACE_WITH_KV_NAMESPACE_ID 자리에 넣기
npx wrangler kv namespace create STATE

# 2. 시크릿 등록 (값은 프롬프트에 붙여 넣으며 저장소에는 남지 않습니다)
npx wrangler secret put SLACK_SIGNING_SECRET   # Slack App → Basic Information → Signing Secret
npx wrangler secret put SLACK_BOT_TOKEN        # xoxb-... (chat:write 권한)
npx wrangler secret put IG_ACCESS_TOKEN        # Instagram 장기 토큰

# 3. 배포 → https://semifeed.<계정>.workers.dev 주소가 출력됩니다
npm run deploy
```

4. Slack App 설정 → **Interactivity & Shortcuts** → Request URL을 위 Worker 주소로 바꿉니다.
   기존 n8n 승인 흐름은 이때부터 동작하지 않으므로 n8n 스케줄러를 먼저 멈춥니다.
5. 실시간 로그: `npx wrangler tail`

## 개발

```bash
npm test           # Slack·Instagram·GitHub 호출을 흉내 낸 단위 테스트
npm run typecheck
```
