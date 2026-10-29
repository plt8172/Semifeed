#!/usr/bin/env python3
"""카드마다 기사와 관련된 무료 스톡 사진을 한 장 받아 출처를 카드 JSON에 기록한다.

    PIXABAY_API_KEY=... python3 scripts/photo.py cards/2026-10-29/ae21ef86a0.json [...]
    python3 scripts/photo.py --exclude 1234567 cards/...json      # 이 사진을 빼고 다시 고른다
    PEXELS_API_KEY=... python3 scripts/photo.py --provider pexels cards/...json

제공처는 --provider > config/semifeed.json의 photo_provider 순서로 정한다 (기본 pixabay).
둘 다 상업 이용·수정이 허용되고 출처 표기 의무가 없는 라이선스지만, 출처는 항상 기록한다.
    python3 scripts/photo.py --clear cards/...json                # 사진 없이 기본 그래픽으로 둔다

검색어는 카드 JSON의 photo_query(Claude가 쓴 영어 키워드)다. 이 스크립트는 판단하지 않는다:
검색 결과를 관련도 순서대로 보고, 최근 30일 카드에 쓴 사진과 --exclude 사진을 빼고
첫 번째 가로 사진을 고른다. 그래서 같은 검색어와 같은 이력이면 언제나 같은 사진이 나온다.
고른 사진이 기사와 맞는지는 Claude가 파일을 열어 확인하고, 아니면 --exclude나 검색어를 바꿔 다시 실행한다.

결과:
    cards/<날짜>/<id>.photo.jpg   받은 사진. 저장소에는 커밋하지 않는다 (.gitignore)
    카드 JSON의 photo             출처·작가·라이선스·원본 링크. 이 기록만 있으면 같은 사진을 다시 받을 수 있다

이미 photo가 기록된 카드는 다시 고르지 않는다. 사진 파일만 없으면 같은 사진을 다시 받는다.
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
from common import CONFIG_PATH, KST, ROOT, load_json, write_json  # noqa: E402

DEFAULT_PROVIDER = "pixabay"
PEXELS_API = os.environ.get("PEXELS_API_BASE", "https://api.pexels.com/v1")
PIXABAY_API = os.environ.get("PIXABAY_API_BASE", "https://pixabay.com/api")
CARDS_DIR = ROOT / "cards"
REUSE_DAYS = 30  # 이 기간 안에 다른 카드에 쓴 사진은 다시 고르지 않는다
PER_PAGE = 30
MIN_WIDTH = 1600  # 원본 기준. 카드 폭 1080px을 잘라 써도 흐려지지 않을 크기
USER_AGENT = "Semifeed/1.0 (+https://github.com/plt8172/Semifeed)"


def photo_path(card_path: Path) -> Path:
    return card_path.with_name(f"{card_path.stem}.photo.jpg")


def recently_used(cards_dir: Path, today: datetime, skip: Path, provider: str) -> set[str]:
    """최근 REUSE_DAYS일 카드 JSON에 기록된 같은 제공처 사진 id. 같은 사진이 연달아 나오지 않게 한다."""
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
            if photo.get("provider") == provider and photo.get("id"):
                used.add(str(photo["id"]))
    return used


def http_json(url: str, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


class Pexels:
    """Pexels License: 상업 이용·수정 허용, 출처 표기 의무 없음."""

    name = "pexels"
    key_env = "PEXELS_API_KEY"
    license = {"name": "Pexels License", "url": "https://www.pexels.com/license/"}

    def __init__(self, key: str):
        self.key = key

    def search(self, query: str) -> list[dict]:
        params = urllib.parse.urlencode({"query": query, "orientation": "landscape", "per_page": PER_PAGE})
        result = http_json(f"{PEXELS_API}/search?{params}", {"Authorization": self.key})
        return [self.normalize(p) for p in result.get("photos", [])]

    def refresh(self, photo: dict) -> str:
        return photo["download_url"]  # Pexels 이미지 주소는 바뀌지 않는다

    @staticmethod
    def normalize(p: dict) -> dict:
        # large2x는 폭 약 1880px로 압축된 JPEG다. 원본(수십 MB)보다 가볍고 카드에 쓰기에 충분하다.
        return {
            "id": str(p["id"]),
            "width": p.get("width", 0),
            "height": p.get("height", 0),
            "download_url": p["src"]["large2x"],
            "page_url": p["url"],
            "photographer": p.get("photographer", ""),
            "photographer_url": p.get("photographer_url", ""),
            "alt": p.get("alt", ""),
        }


class Pixabay:
    """Pixabay Content License: 상업 이용·수정 허용, 출처 표기 의무 없음.
    이미지 주소(largeImageURL, 폭 1280px)는 임시라서 다시 받을 때는 id로 새 주소를 조회한다."""

    name = "pixabay"
    key_env = "PIXABAY_API_KEY"
    license = {"name": "Pixabay Content License", "url": "https://pixabay.com/service/license-summary/"}

    def __init__(self, key: str):
        self.key = key

    def _get(self, **params) -> list[dict]:
        # 키가 쿼리 문자열에 들어가므로 이 URL은 로그에 남기지 않는다.
        query = urllib.parse.urlencode({"key": self.key, **params})
        return http_json(f"{PIXABAY_API}/?{query}").get("hits", [])

    def search(self, query: str) -> list[dict]:
        hits = self._get(q=query, image_type="photo", orientation="horizontal", safesearch="true", per_page=PER_PAGE)
        return [self.normalize(h) for h in hits]

    def refresh(self, photo: dict) -> str:
        hits = self._get(id=photo["id"])
        if not hits:
            raise ValueError(f"pixabay photo {photo['id']} no longer available")
        return hits[0]["largeImageURL"]

    @staticmethod
    def normalize(h: dict) -> dict:
        user, user_id = h.get("user", ""), h.get("user_id", "")
        return {
            "id": str(h["id"]),
            "width": h.get("imageWidth", 0),
            "height": h.get("imageHeight", 0),
            "download_url": h["largeImageURL"],
            "page_url": h.get("pageURL", ""),
            "photographer": user,
            "photographer_url": f"https://pixabay.com/users/{user}-{user_id}/" if user else "",
            "alt": h.get("tags", ""),
        }


PROVIDERS = {cls.name: cls for cls in (Pixabay, Pexels)}


def choose(photos: list[dict], excluded: set[str]) -> dict | None:
    for photo in photos:
        if photo["id"] in excluded:
            continue
        if photo["width"] < MIN_WIDTH or photo["width"] <= photo["height"]:
            continue
        return photo
    return None


def download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("downloaded file is not a JPEG")
    dest.write_bytes(data)


def record(provider, photo: dict, query: str, file_name: str) -> dict:
    label = provider.name.capitalize()
    return {
        "provider": provider.name,
        "id": photo["id"],
        "query": query,
        "file": file_name,
        "download_url": photo["download_url"],
        "page_url": photo["page_url"],
        "photographer": photo["photographer"],
        "photographer_url": photo["photographer_url"],
        "alt": photo["alt"],
        "width": photo["width"],
        "height": photo["height"],
        "license": provider.license["name"],
        "license_url": provider.license["url"],
        "credit": f"Photo: {photo['photographer'] or 'Unknown'} / {label}",
    }


def process(card_path: Path, provider, excluded: set[str], replace: bool, cards_dir: Path) -> str:
    """사진을 붙이고 한 줄 결과를 돌려준다. 실패하면 ValueError나 URLError를 던진다."""
    card = load_json(card_path, None)
    if card is None:
        raise ValueError("card JSON not found")
    dest = photo_path(card_path)
    existing = card.get("photo")

    if existing and not replace and str(existing.get("id")) not in excluded:
        name = existing.get("provider")
        if not dest.is_file():
            if name != provider.name:
                raise ValueError(f"photo is from {name}; re-download needs that provider (--provider {name})")
            download(provider.refresh(existing), dest)
            return f"re-downloaded {name} {existing['id']}"
        return f"kept {name} {existing['id']}"

    query = (card.get("photo_query") or "").strip()
    if not query:
        raise ValueError("photo_query is empty")
    skip = recently_used(cards_dir, datetime.now(KST), card_path, provider.name) | excluded
    if existing:
        skip.add(str(existing.get("id")))
    photos = provider.search(query)
    photo = choose(photos, skip)
    if photo is None:
        raise ValueError(f"no usable photo for query {query!r} ({len(photos)} results)")

    entry = record(provider, photo, query, dest.name)
    download(entry["download_url"], dest)
    card["photo"] = entry
    write_json(card_path, card)
    return f"{provider.name} {entry['id']} ({entry['alt'] or 'no alt'}) -> {dest}"


def clear(card_path: Path) -> None:
    card = load_json(card_path, {})
    if card.pop("photo", None) is not None:
        write_json(card_path, card)
    photo_path(card_path).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cards", nargs="+", type=Path, help="cards/<날짜>/<id>.json")
    parser.add_argument("--exclude", action="append", default=[], metavar="PHOTO_ID",
                        help="고르지 않을 사진 id. 여러 번 쓸 수 있다")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), help="사진 제공처. 기본값은 config의 photo_provider")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--replace", action="store_true", help="이미 기록된 사진을 버리고 새로 고른다")
    parser.add_argument("--clear", action="store_true", help="사진 기록과 파일을 지운다")
    parser.add_argument("--cards-dir", type=Path, default=CARDS_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.clear:
        for card_path in args.cards:
            clear(card_path)
            print(f"[ok  ] {card_path}: photo cleared", file=sys.stderr)
        return 0

    name = args.provider or load_json(args.config, {}).get("photo_provider") or DEFAULT_PROVIDER
    if name not in PROVIDERS:
        print(f"알 수 없는 사진 제공처: {name}", file=sys.stderr)
        return 1
    cls = PROVIDERS[name]
    key = os.environ.get(cls.key_env, "")
    if not key:
        print(f"{cls.key_env} 환경 변수가 없습니다.", file=sys.stderr)
        return 1
    provider = cls(key)

    excluded = {str(x) for x in args.exclude}
    failed = 0
    for card_path in args.cards:
        try:
            message = process(card_path, provider, excluded, args.replace, args.cards_dir)
            print(f"[ok  ] {card_path}: {message}", file=sys.stderr)
        except (urllib.error.URLError, ValueError, KeyError, OSError) as error:
            failed += 1
            print(f"[FAIL] {card_path}: {error}", file=sys.stderr)
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
