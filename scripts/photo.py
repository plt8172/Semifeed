#!/usr/bin/env python3
"""카드마다 기사와 관련된 무료 스톡 사진을 Pexels에서 한 장 받아 출처를 카드 JSON에 기록한다.

    PEXELS_API_KEY=... python3 scripts/photo.py cards/2026-10-29/ae21ef86a0.json [...]
    python3 scripts/photo.py --exclude 1234567 cards/...json      # 이 사진을 빼고 다시 고른다
    python3 scripts/photo.py --clear cards/...json                # 사진 없이 기본 그래픽으로 둔다

검색어는 카드 JSON의 photo_query(Claude가 쓴 영어 키워드)다. 이 스크립트는 판단하지 않는다:
Pexels 검색 결과를 관련도 순서대로 보고, 최근 30일 카드에 쓴 사진과 --exclude 사진을 빼고
첫 번째 가로 사진을 고른다. 그래서 같은 검색어와 같은 이력이면 언제나 같은 사진이 나온다.
고른 사진이 기사와 맞는지는 Claude가 파일을 열어 확인하고, 아니면 --exclude나 검색어를 바꿔 다시 실행한다.

결과:
    cards/<날짜>/<id>.photo.jpg   받은 사진. 저장소에는 커밋하지 않는다 (.gitignore)
    카드 JSON의 photo             출처·작가·라이선스·원본 링크. 이 기록만 있으면 같은 사진을 다시 받을 수 있다

이미 photo가 기록된 카드는 다시 고르지 않는다. 사진 파일만 없으면 기록된 주소에서 다시 받는다.
사진은 카드의 필수 요소가 아니다. 실패한 카드는 사진 없이 다음 단계로 넘어가도 된다.

종료 코드: 0 = 모든 카드에 사진 있음, 1 = API 키 없음 등 실행 불가, 3 = 사진을 못 붙인 카드가 있음.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import KST, ROOT, load_json, write_json  # noqa: E402

PEXELS_API = os.environ.get("PEXELS_API_BASE", "https://api.pexels.com/v1")
CARDS_DIR = ROOT / "cards"
LICENSE = {"name": "Pexels License", "url": "https://www.pexels.com/license/"}
REUSE_DAYS = 30  # 이 기간 안에 다른 카드에 쓴 사진은 다시 고르지 않는다
PER_PAGE = 30
MIN_WIDTH = 1600  # 카드 폭 1080px을 잘라 써도 흐려지지 않을 크기
USER_AGENT = "Semifeed/1.0 (+https://github.com/plt8172/Semifeed)"


def photo_path(card_path: Path) -> Path:
    return card_path.with_name(f"{card_path.stem}.photo.jpg")


def recently_used(cards_dir: Path, today: datetime, skip: Path) -> set[str]:
    """최근 REUSE_DAYS일 카드 JSON에 기록된 Pexels 사진 id. 같은 사진이 연달아 나오지 않게 한다."""
    used = set()
    cutoff = (today - timedelta(days=REUSE_DAYS)).date()
    for day_dir in cards_dir.glob("*"):
        try:
            if datetime.strptime(day_dir.name, "%Y-%m-%d").date() < cutoff:
                continue
        except ValueError:
            continue
        for path in day_dir.glob("*.json"):
            if path.resolve() == skip.resolve():
                continue
            photo = (load_json(path, {}) or {}).get("photo") or {}
            if photo.get("provider") == "pexels" and photo.get("id"):
                used.add(str(photo["id"]))
    return used


def api_get(key: str, path: str, params: dict) -> dict:
    url = f"{PEXELS_API}/{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def choose(photos: list[dict], excluded: set[str]) -> dict | None:
    for photo in photos:
        if str(photo.get("id")) in excluded:
            continue
        if photo.get("width", 0) < MIN_WIDTH or photo.get("width", 0) <= photo.get("height", 0):
            continue
        return photo
    return None


def download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if not data.startswith(b"\xff\xd8"):
        raise ValueError(f"not a JPEG: {url}")
    dest.write_bytes(data)


def record(photo: dict, query: str, file_name: str) -> dict:
    # large2x는 폭 약 1880px로 압축된 JPEG다. 원본(수십 MB)보다 가볍고 카드에 쓰기에 충분하다.
    return {
        "provider": "pexels",
        "id": str(photo["id"]),
        "query": query,
        "file": file_name,
        "download_url": photo["src"]["large2x"],
        "page_url": photo["url"],
        "photographer": photo.get("photographer", ""),
        "photographer_url": photo.get("photographer_url", ""),
        "alt": photo.get("alt", ""),
        "width": photo.get("width"),
        "height": photo.get("height"),
        "license": LICENSE["name"],
        "license_url": LICENSE["url"],
        "credit": f"Photo: {photo.get('photographer') or 'Unknown'} / Pexels",
    }


def process(card_path: Path, key: str, excluded: set[str], replace: bool, cards_dir: Path) -> str:
    """사진을 붙이고 한 줄 결과를 돌려준다. 실패하면 ValueError나 URLError를 던진다."""
    card = load_json(card_path, None)
    if card is None:
        raise ValueError("card JSON not found")
    dest = photo_path(card_path)
    existing = card.get("photo")

    if existing and not replace and str(existing.get("id")) not in excluded:
        if not dest.is_file():
            download(existing["download_url"], dest)
            return f"re-downloaded pexels {existing['id']}"
        return f"kept pexels {existing['id']}"

    query = (card.get("photo_query") or "").strip()
    if not query:
        raise ValueError("photo_query is empty")
    skip = recently_used(cards_dir, datetime.now(KST), card_path) | excluded
    if existing:
        skip.add(str(existing.get("id")))
    result = api_get(key, "search", {"query": query, "orientation": "landscape", "per_page": PER_PAGE})
    photo = choose(result.get("photos", []), skip)
    if photo is None:
        raise ValueError(f"no usable photo for query {query!r} ({len(result.get('photos', []))} results)")

    entry = record(photo, query, dest.name)
    download(entry["download_url"], dest)
    card["photo"] = entry
    write_json(card_path, card)
    return f"pexels {entry['id']} ({entry['alt'] or 'no alt'}) -> {dest}"


def clear(card_path: Path) -> None:
    card = load_json(card_path, {})
    if card.pop("photo", None) is not None:
        write_json(card_path, card)
    photo_path(card_path).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cards", nargs="+", type=Path, help="cards/<날짜>/<id>.json")
    parser.add_argument("--exclude", action="append", default=[], metavar="PHOTO_ID",
                        help="고르지 않을 Pexels 사진 id. 여러 번 쓸 수 있다")
    parser.add_argument("--replace", action="store_true", help="이미 기록된 사진을 버리고 새로 고른다")
    parser.add_argument("--clear", action="store_true", help="사진 기록과 파일을 지운다")
    parser.add_argument("--cards-dir", type=Path, default=CARDS_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.clear:
        for card_path in args.cards:
            clear(card_path)
            print(f"[ok  ] {card_path}: photo cleared", file=sys.stderr)
        return 0

    key = os.environ.get("PEXELS_API_KEY", "")
    if not key:
        print("PEXELS_API_KEY 환경 변수가 없습니다.", file=sys.stderr)
        return 1

    excluded = {str(x) for x in args.exclude}
    failed = 0
    for card_path in args.cards:
        try:
            message = process(card_path, key, excluded, args.replace, args.cards_dir)
            print(f"[ok  ] {card_path}: {message}", file=sys.stderr)
        except (urllib.error.URLError, ValueError, KeyError, OSError) as error:
            failed += 1
            print(f"[FAIL] {card_path}: {error}", file=sys.stderr)
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
