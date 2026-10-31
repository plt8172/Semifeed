#!/usr/bin/env python3
"""이번 실행에서 고른 사진과 최근 카드를 한 장에 모아, Claude가 겹치는 사진을 한 번에 찾게 한다.

    python3 scripts/contact_sheet.py cards/2026-10-29/ae21ef86a0.json [...]
    → contact_sheet.jpg (커밋하지 않음)

윗줄: 넘긴 카드 중 사진을 고른 카드의 사진(<id>.photo.jpg).
가운데: 아직 사진이 없고 photo.py --candidates로 후보를 모은 카드마다 한 줄씩, 후보 썸네일.
  칸 이름은 "사진 id · 출처"다. q1~q3은 카드의 photo_queries 순서, f1~은 config의 일반 검색어.
  고른 사진은 photo.py --pick <사진 id>로 붙인다.
아랫줄: 최근 DAYS일 동안 사진을 넣어 렌더된 다른 카드(<id>.jpg).
칸마다 사진 id를 적어서, 겹치는 사진을 찾으면 바로 photo.py --exclude에 쓸 수 있다.

photo.py는 같은 id와 같은 작가만 거른다. 다른 계정이 같은 사진을 다시 올린 경우는
이미지 해시로도 구분되지 않아서 (안개·잘림 차이) 눈으로 보고 판단한다.
"""

from __future__ import annotations

import argparse
import html
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import KST, ROOT, load_json  # noqa: E402
from render import image_data_uri, launch  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

CARDS_DIR = ROOT / "cards"
DAYS = 3
THUMB = 200


def recent_cards(cards_dir: Path, today: datetime, days: int, skip: set[Path]) -> list[Path]:
    """최근 days일 카드 중 사진이 들어간 것. 최근 것부터."""
    cutoff = (today - timedelta(days=days)).date()
    found = []
    for day_dir in cards_dir.glob("*"):
        try:
            if datetime.strptime(day_dir.name, "%Y-%m-%d").date() < cutoff:
                continue
        except ValueError:
            continue
        for path in day_dir.glob("*.json"):
            if path.resolve() in skip or not (load_json(path, {}) or {}).get("photo"):
                continue
            if path.with_suffix(".jpg").is_file():
                found.append(path)
    return sorted(found, key=lambda p: p.parent.name, reverse=True)


def tile(card_path: Path, image: str, label: str) -> str:
    uri = image_data_uri(card_path, image)
    picture = f'<img src="{uri}">' if uri else '<div class="none">사진 없음</div>'
    return f'<figure>{picture}<figcaption>{html.escape(label)}</figcaption></figure>'


def candidate_rows(new_cards: list[Path]) -> str:
    rows = []
    for path in new_cards:
        card = load_json(path, {}) or {}
        if card.get("photo"):
            continue
        folder = path.with_name(f"{path.stem}.candidates")
        listing = load_json(folder / "list.json", {}) or {}
        tiles = [tile(folder / "x", c["thumb"], f"{c['id']} · {c['label']}") for c in listing.get("candidates", [])]
        title = html.escape(f"{path.stem} 후보 — {card.get('headline') or card.get('title') or ''}")
        rows.append(f'<h2>{title}</h2><div class="row">{"".join(tiles) or "후보 없음"}</div>')
    return "".join(rows)


def build(new_cards: list[Path], recent: list[Path], days: int) -> str:
    top = []
    for path in new_cards:
        photo = (load_json(path, {}) or {}).get("photo") or {}
        if not photo and path.with_name(f"{path.stem}.candidates").is_dir():
            continue  # 아래 후보 줄에 나온다
        top.append(tile(path, photo.get("file", ""), f"{path.stem} · {photo.get('id', '-')}"))
    bottom = []
    for path in recent:
        photo = load_json(path, {})["photo"]
        bottom.append(tile(path, path.with_suffix(".jpg").name, f"{path.parent.name[5:]} · {photo.get('id', '-')}"))
    return f"""<!doctype html><meta charset="utf-8"><style>
body {{ margin: 0; padding: 16px; background: #fff; font: 14px sans-serif; width: {THUMB * 7 + 16 * 8}px; }}
h2 {{ font-size: 16px; margin: 8px 0; }}
.row {{ display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 16px; }}
figure {{ margin: 0; width: {THUMB}px; }}
img, .none {{ width: {THUMB}px; height: {THUMB}px; object-fit: cover; display: block; background: #ddd; }}
.none {{ display: flex; align-items: center; justify-content: center; }}
figcaption {{ margin-top: 4px; }}
</style>
<h2>이번 카드 사진 (카드 id · 사진 id)</h2><div class="row">{''.join(top) or '없음'}</div>
{candidate_rows(new_cards)}
<h2>최근 {days}일 카드 (날짜 · 사진 id)</h2><div class="row">{''.join(bottom) or '없음'}</div>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cards", nargs="+", type=Path, help="이번 실행의 cards/<날짜>/<id>.json")
    parser.add_argument("--out", type=Path, default=ROOT / "contact_sheet.jpg")
    parser.add_argument("--days", type=int, default=DAYS)
    parser.add_argument("--cards-dir", type=Path, default=CARDS_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args()

    skip = {path.resolve() for path in args.cards}
    recent = recent_cards(args.cards_dir, datetime.now(KST), args.days, skip)
    with sync_playwright() as playwright:
        browser = launch(playwright)
        page = browser.new_page()
        page.set_content(build(args.cards, recent, args.days))
        page.screenshot(path=str(args.out), type="jpeg", quality=80, full_page=True)
        browser.close()
    print(f"[ok  ] {args.out}: {len(args.cards)} new, {len(recent)} recent", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
