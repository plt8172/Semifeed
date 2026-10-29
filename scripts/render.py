#!/usr/bin/env python3
"""카드 메타데이터(<id>.json)를 templates/layouts/<레이아웃>.html에 채워 1080×1080 JPEG로 렌더링한다.

    python3 scripts/render.py cards/2026-10-19/381bbabb74.json [...]
    → 같은 폴더에 381bbabb74.jpg
    python3 scripts/render.py --layout classic cards/...json   # 레이아웃을 지정한다

레이아웃은 --layout > 카드 JSON의 layout > config/semifeed.json의 card_layout 순서로 정한다.
레이아웃 목록과 레이아웃이 지켜야 할 약속은 templates/README.md에 있다.

카드 JSON 필드:
    id            카드 id (fetch.py 후보의 id)
    headline      제목, 2줄 안
    bullets       요약 문장 1~3개
    source        카드 하단에 표시할 매체명 (예: "EE Times")
    category      상단 분류 배지 (예: "산업", "메모리")
    published_at  기사 발행일 (YYYY-MM-DD 또는 ISO 8601)
    image         선택. JSON 기준 상대 경로의 로컬 이미지. 없으면 photo.file, 둘 다 없으면 기본 배경
    image_credit  선택. 이미지 크레딧. 없으면 photo.credit
    photo         선택. scripts/photo.py가 기록한 사진 출처 (file, credit 등)
    layout        선택. 이 카드에만 쓸 레이아웃 이름
    caption, link 렌더링에는 쓰지 않음 (Worker가 Instagram 캡션으로 사용)

텍스트는 DOM의 textContent로 넣어 기사 문구가 HTML로 해석되지 않게 한다.
제목이나 본문이 영역을 넘치면 JPEG를 만들지 않고 종료 코드 2로 끝낸다.
문구를 줄여 다시 실행하라는 신호다.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG_PATH, ROOT, load_json  # noqa: E402

LAYOUTS_DIR = ROOT / "templates" / "layouts"
DEFAULT_LAYOUT = "photo"
FALLBACK_CHROMIUM = "/opt/pw-browsers/chromium"
JPEG_QUALITY = 92

FILL_SCRIPT = """
(card) => {
  const set = (field, value) => {
    const el = document.querySelector(`[data-field="${field}"]`);
    if (el && value != null) el.textContent = value;
  };
  set('headline', card.headline);
  set('category', card.category);
  set('published-at', card.date);
  set('source', card.source);
  // 크레딧이 없으면 레이아웃의 기본 문구를 그대로 둔다.
  if (card.image_credit) set('image-credit', card.image_credit);

  const list = document.querySelector('[data-field="bullets"]');
  list.replaceChildren(...card.bullets.map((text) => {
    const li = document.createElement('li');
    li.textContent = text;
    return li;
  }));

  const img = document.querySelector('[data-field="image"]');
  if (card.image) {
    img.src = card.image;
    img.hidden = false;
  }
}
"""

# 잘림을 감지한다: 제목은 max-height+overflow:hidden, 본문은 footer가 카드 밖으로 밀리는지 본다.
OVERFLOW_SCRIPT = """
() => {
  const problems = [];
  const h1 = document.querySelector('h1');
  if (h1.scrollHeight > h1.clientHeight + 1) problems.push(`headline ${h1.scrollHeight}px > ${h1.clientHeight}px`);
  const story = document.querySelector('.story');
  if (story.scrollHeight > story.clientHeight + 1) problems.push(`story ${story.scrollHeight}px > ${story.clientHeight}px`);
  return problems;
}
"""


def format_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y.%m.%d")
    except (TypeError, ValueError):
        return value or ""


def image_data_uri(card_path: Path, image: str | None) -> str | None:
    if not image:
        return None
    path = (card_path.parent / image).resolve()
    if not path.is_file():
        print(f"  warning: image not found, using fallback graphic: {path}", file=sys.stderr)
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def layout_names() -> list[str]:
    return sorted(path.stem for path in LAYOUTS_DIR.glob("*.html"))


def choose_layout(card: dict, override: str | None, config: dict) -> str:
    return override or card.get("layout") or config.get("card_layout") or DEFAULT_LAYOUT


def validate(card: dict) -> list[str]:
    errors = [f"missing field: {key}" for key in ("id", "headline", "bullets", "source") if not card.get(key)]
    bullets = card.get("bullets") or []
    if not isinstance(bullets, list) or not 1 <= len(bullets) <= 3:
        errors.append("bullets must be a list of 1-3 sentences")
    return errors


def launch(playwright):
    try:
        return playwright.chromium.launch()
    except PlaywrightError:
        # 설치된 playwright 버전과 내려받은 Chromium 리비전이 다를 때를 대비한다.
        executable = os.environ.get("SEMIFEED_CHROMIUM", FALLBACK_CHROMIUM)
        return playwright.chromium.launch(executable_path=executable)


def render(page, card_path: Path, out_path: Path, layout_override: str | None = None, config: dict | None = None) -> list[str]:
    card = json.loads(card_path.read_text(encoding="utf-8"))
    errors = validate(card)
    layout = choose_layout(card, layout_override, config or {})
    template = LAYOUTS_DIR / f"{layout}.html"
    if not template.is_file():
        errors.append(f"unknown layout: {layout} (available: {', '.join(layout_names())})")
    if errors:
        return errors
    photo = card.get("photo") or {}
    payload = {
        "headline": card["headline"],
        "bullets": card["bullets"],
        "source": card["source"],
        "category": card.get("category", "산업"),
        "date": format_date(card.get("published_at", "")),
        "image_credit": card.get("image_credit") or photo.get("credit"),
        "image": image_data_uri(card_path, card.get("image") or photo.get("file")),
    }
    page.goto(template.as_uri())
    page.evaluate(FILL_SCRIPT, payload)
    page.evaluate("document.fonts.ready")
    # 이미지가 깨지면 숨겨서 기본 그래픽이 보이게 한다 (DESIGN.md: Image error).
    page.evaluate("""() => {
      const img = document.querySelector('[data-field="image"]');
      if (!img.hidden && !(img.complete && img.naturalWidth)) img.hidden = true;
    }""")
    problems = page.evaluate(OVERFLOW_SCRIPT)
    if problems:
        return [f"text overflow: {p}" for p in problems]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.locator(".card").screenshot(path=str(out_path), type="jpeg", quality=JPEG_QUALITY)
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cards", nargs="+", type=Path, help="카드 메타데이터 JSON 경로")
    parser.add_argument("--out-dir", type=Path, help="JPEG 저장 폴더. 기본값은 JSON과 같은 폴더")
    parser.add_argument("--layout", choices=layout_names(), help="모든 카드에 쓸 레이아웃")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()
    config = load_json(args.config, {})

    failed = 0
    with sync_playwright() as playwright:
        browser = launch(playwright)
        page = browser.new_page(viewport={"width": 1080, "height": 1080}, device_scale_factor=1)
        for card_path in args.cards:
            out_path = (args.out_dir or card_path.parent) / f"{card_path.stem}.jpg"
            errors = render(page, card_path, out_path, args.layout, config)
            if errors:
                failed += 1
                print(f"[FAIL] {card_path}: " + "; ".join(errors), file=sys.stderr)
            else:
                print(f"[ok  ] {card_path} -> {out_path}", file=sys.stderr)
        browser.close()
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
