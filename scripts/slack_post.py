#!/usr/bin/env python3
"""카드마다 Slack 메시지 하나를 보낸다: 카드 이미지 + 캡션 미리보기 + [승인][반려] 버튼.

    SLACK_BOT_TOKEN=xoxb-... python3 scripts/slack_post.py cards/2026-10-19/381bbabb74.json [...]
    python3 scripts/slack_post.py --dry-run cards/...json   # 보낼 내용만 출력

카드 이미지는 파일 업로드 대신 GitHub raw URL을 Block Kit 이미지 블록으로 보여 준다.
Instagram도 같은 URL에서 이미지를 받아 가므로, Slack에서 보이는 이미지가 그대로 게시된다.
그래서 이 스크립트는 카드를 커밋·푸시한 뒤에 실행해야 하며, 보내기 전에 raw URL이 열리는지 확인한다.

버튼 value는 카드 경로 키("2026-10-19/381bbabb74")다. Worker는 이 키로
raw URL의 <id>.json(캡션)과 <id>.jpg(이미지)를 찾는다.

필요한 Slack 권한: chat:write (봇이 채널에 초대돼 있어야 한다).
종료 코드: 0 = 전부 전송, 1 = 하나 이상 실패.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG_PATH, load_json  # noqa: E402

SLACK_API = os.environ.get("SLACK_API_BASE", "https://slack.com/api")
CAPTION_LIMIT = 2200  # Instagram 캡션 최대 길이
HASHTAG_LIMIT = 30  # Instagram 해시태그 최대 개수
PREVIEW_LIMIT = 2800  # Slack section 텍스트 최대 3000자


def card_key(card_path: Path) -> str:
    """cards/<날짜>/<id>.json → "<날짜>/<id>". Worker와 약속한 버튼 value 형식."""
    return f"{card_path.parent.name}/{card_path.stem}"


def raw_url(config: dict, key: str, ext: str) -> str:
    repo = config.get("github_repo", "plt8172/Semifeed")
    branch = config.get("github_branch", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/cards/{key}.{ext}"


def validate(card: dict, image_path: Path) -> list[str]:
    errors = [f"missing field: {k}" for k in ("id", "headline", "caption", "link") if not card.get(k)]
    caption = card.get("caption", "")
    if len(caption) > CAPTION_LIMIT:
        errors.append(f"caption {len(caption)} chars > {CAPTION_LIMIT}")
    if caption.count("#") > HASHTAG_LIMIT:
        errors.append(f"more than {HASHTAG_LIMIT} hashtags")
    if not image_path.is_file():
        errors.append(f"image not rendered: {image_path}")
    return errors


def wait_until_public(url: str, attempts: int = 6, delay: float = 5.0) -> bool:
    """푸시 직후 raw CDN에 반영되기까지 잠깐 걸릴 수 있어 몇 번 다시 확인한다."""
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status == 200:
                    return True
        except urllib.error.URLError:
            pass
        if attempt < attempts - 1:
            time.sleep(delay)
    return False


def build_message(channel: str, card: dict, key: str, image_url: str) -> dict:
    caption = card["caption"]
    if len(caption) > PREVIEW_LIMIT:
        caption = caption[: PREVIEW_LIMIT - 1] + "…"
    return {
        "channel": channel,
        "text": f"게시 승인 요청: {card['headline']}",  # 알림·접근성용 대체 텍스트
        "unfurl_links": False,
        "unfurl_media": False,
        "blocks": [
            {"type": "image", "image_url": image_url, "alt_text": card["headline"]},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*캡션 미리보기*\n{caption}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"원문: <{card['link']}|{card.get('source') or '기사 링크'}> · 카드 `{key}`"}]},
            {
                "type": "actions",
                "block_id": "semifeed_review",
                "elements": [
                    {"type": "button", "action_id": "approve", "style": "primary", "value": key,
                     "text": {"type": "plain_text", "text": "승인"}},
                    {"type": "button", "action_id": "reject", "style": "danger", "value": key,
                     "text": {"type": "plain_text", "text": "반려"}},
                ],
            },
        ],
    }


def post_message(token: str, message: dict) -> dict:
    request = urllib.request.Request(
        f"{SLACK_API}/chat.postMessage",
        data=json.dumps(message).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cards", nargs="+", type=Path, help="cards/<날짜>/<id>.json")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--dry-run", action="store_true", help="보내지 않고 메시지 JSON만 출력")
    parser.add_argument("--skip-url-check", action="store_true", help="raw URL 공개 여부 확인 생략 (테스트용)")
    args = parser.parse_args()

    config = load_json(args.config, {})
    channel = os.environ.get("SLACK_CHANNEL_ID") or config.get("slack_channel_id")
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not args.dry_run and not token:
        print("SLACK_BOT_TOKEN 환경 변수가 없습니다.", file=sys.stderr)
        return 1

    failed = 0
    for card_path in args.cards:
        card = load_json(card_path, {})
        key = card_key(card_path)
        image_url = raw_url(config, key, "jpg")
        errors = validate(card, card_path.with_suffix(".jpg"))
        if not errors and not args.dry_run and not args.skip_url_check:
            for ext in ("jpg", "json"):
                if not wait_until_public(raw_url(config, key, ext)):
                    errors.append(f"not public yet (push first?): {raw_url(config, key, ext)}")
        if errors:
            failed += 1
            print(f"[FAIL] {card_path}: " + "; ".join(errors), file=sys.stderr)
            continue

        message = build_message(channel, card, key, image_url)
        if args.dry_run:
            print(json.dumps(message, ensure_ascii=False, indent=2))
            continue
        try:
            result = post_message(token, message)
        except urllib.error.URLError as error:
            result = {"ok": False, "error": str(error)}
        if result.get("ok"):
            print(f"[ok  ] {card_path} -> ts {result.get('ts')}", file=sys.stderr)
        else:
            failed += 1
            print(f"[FAIL] {card_path}: slack error {result.get('error')}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
