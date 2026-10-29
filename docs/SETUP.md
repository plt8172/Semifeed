# 운영 준비: 전체 흐름과 직접 연결할 것

## 전체 흐름

```
[1] Claude Code 예약 작업 (09·12·17·21시 KST)
    fetch.py        RSS 10개 → 72시간 이내, 처리한 적 없는 기사 → candidates.json
    Claude          기사 선별 + 카드 문구·캡션 작성 → cards/<날짜>/<id>.json
    render.py       카드 JSON → cards/<날짜>/<id>.jpg (문구가 넘치면 Claude가 줄여 다시 렌더)
    mark_seen.py    선별한 기사를 state/seen.json에 기록 (승인 여부와 무관)
    git push main   카드가 raw.githubusercontent.com 주소로 공개됨
    slack_post.py   카드 이미지 + 캡션 미리보기 + [승인][반려] 버튼 전송

[2] 사람: Slack에서 [승인] 또는 [반려] 클릭

[3] Cloudflare Worker (클릭이 올 때만 실행)
    반려 → 메시지를 "반려됨"으로 변경
    승인 → raw URL의 <id>.json에서 캡션 읽기
         → Instagram에 raw URL의 <id>.jpg로 게시 → 메시지를 "게시 완료 + 링크"로 변경

[4] Worker Cron
    5분마다   Instagram 처리가 늦은 게시 마무리
    매일 03시 Instagram 장기 토큰 갱신 (KV에 저장)
```

LLM API 키(OpenRouter, Anthropic)는 필요 없습니다. 기사 선별과 문구 작성은 예약 작업을 실행하는 Claude가 직접 합니다.

## 토큰·시크릿이 들어가는 곳

| 값 | 어디서 얻나 | 넣을 곳 |
| --- | --- | --- |
| `SLACK_BOT_TOKEN` (`xoxb-…`) | Slack App → OAuth & Permissions → Bot User OAuth Token | ① Claude 클라우드 환경 ② Worker Secret |
| `SLACK_SIGNING_SECRET` | Slack App → Basic Information → App Credentials → Signing Secret | Worker Secret |
| `IG_ACCESS_TOKEN` (`IGAA…`, 장기 토큰) | Meta 개발자 앱 → Instagram API with Instagram Login | Worker Secret |
| `PIXABAY_API_KEY` | https://pixabay.com/api/docs/ 에서 로그인하면 바로 표시됨 (무료) | Claude 클라우드 환경 |
| `PEXELS_API_KEY` (선택) | https://www.pexels.com/api/ (2026-10-29 기준 신규 발급 중단) | Claude 클라우드 환경, `photo_provider`를 `pexels`로 바꿀 때만 |

토큰은 저장소·채팅에 붙여 넣지 않습니다.

## 직접 연결할 것

### 1. Claude (claude.ai)
- [x] 클라우드 환경 네트워크 허용: RSS 10개 도메인 + `slack.com`
- [ ] 같은 클라우드 환경에 `SLACK_BOT_TOKEN` 추가: 환경 메뉴의 톱니바퀴 → Network secrets(없으면 환경 변수). 프로젝트가 그 환경을 쓰도록 선택돼 있어야 합니다.
- [ ] 카드 사진: 같은 환경의 네트워크 허용에 `pixabay.com` 추가(API와 이미지 모두 이 도메인), 환경 변수에 `PIXABAY_API_KEY` 추가. 없어도 카드는 사진 없이 만들어집니다.
- [ ] GitHub 연결에 `plt8172/Semifeed` 쓰기 권한 확인: 예약 작업이 `main`에 카드를 푸시합니다.
- [ ] 예약 작업의 "Automatically approve" 켜기: 예약 작업을 만든 뒤 켭니다.

### 2. Slack App (api.slack.com/apps, 기존 앱 재사용 가능)
- [ ] Bot Token Scopes에 `chat:write`. 파일 업로드를 쓰지 않으므로 `files:write`는 필요 없습니다. 권한을 바꿨다면 앱을 다시 설치합니다.
- [x] 봇을 채널 `C0CD6SFCFS8`(Semifeed 워크스페이스)에 초대
- [ ] Interactivity & Shortcuts → Request URL을 Worker 주소로 변경 (Worker 배포 뒤, n8n을 멈춘 뒤)

### 3. Instagram (Meta 개발자 앱)
- [ ] 권한 `instagram_business_basic`, `instagram_business_content_publish`가 있는 **장기 토큰**(60일). 단기 토큰은 Cron 갱신이 되지 않습니다.
- [ ] 계정 ID가 `17841433117660601`이 맞는지 확인 (`worker/wrangler.toml`의 `IG_USER_ID`)

### 4. Cloudflare (무료 플랜)
- [ ] 계정 생성 → `cd worker && npm install && npx wrangler login`
- [ ] `npx wrangler kv namespace create STATE` → 출력된 id를 `worker/wrangler.toml`에 반영
- [ ] `npx wrangler secret put` 으로 `SLACK_SIGNING_SECRET`, `SLACK_BOT_TOKEN`, `IG_ACCESS_TOKEN` 등록
- [ ] `npm run deploy` → 출력된 `https://semifeed.<계정>.workers.dev` 주소를 Slack Request URL에 사용

자세한 배포 절차는 `worker/README.md`에 있습니다.

### 5. 전환 후 정리 (중복 게시 방지)
- [ ] 기존 n8n 스케줄러 Unpublish → GCE VM 중지 → Tailscale Funnel 해제

## 연결 순서

1. 이 브랜치를 `main`에 머지: raw URL이 `main` 기준이라 머지 전에는 실제 게시가 안 됩니다.
2. n8n 스케줄러 중지
3. Cloudflare 배포 → Slack Request URL 변경
4. Claude 환경에 `SLACK_BOT_TOKEN` 추가 → 예약 작업 생성·첫 실행으로 전체 검증
