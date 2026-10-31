#!/usr/bin/env python3
"""카드마다 기사와 관련된 무료 스톡 사진을 한 장 받아 출처를 카드 JSON에 기록한다.

    PIXABAY_API_KEY=... python3 scripts/photo.py cards/2026-10-29/ae21ef86a0.json [...]
    python3 scripts/photo.py --exclude 1234567 cards/...json      # 이 사진을 빼고 다시 고른다
    PEXELS_API_KEY=... python3 scripts/photo.py --provider pexels cards/...json

제공처는 --provider > config/semifeed.json의 photo_provider 순서로 정한다 (기본 pixabay).
둘 다 상업 이용·수정이 허용되고 출처 표기 의무가 없는 라이선스지만, 출처는 항상 기록한다.
    python3 scripts/photo.py --clear cards/...json                # 사진 없이 기본 그래픽으로 둔다

정기 실행은 후보 모드를 쓴다. 첫 결과 하나만 보고 세 번 다시 고르면 사진 없는 카드가 많았다 (2026-10-31).
    python3 scripts/photo.py --candidates cards/...json [...]     # 카드마다 후보 최대 20장 + 썸네일
    python3 scripts/contact_sheet.py cards/...json [...]          # 후보를 한 장에 모아 본다
    python3 scripts/photo.py --pick 1234567 cards/...json         # 후보 중 고른 사진을 붙인다
후보는 카드의 photo_queries(검색어마다 앞에서 PER_QUERY장)와 config의 photo_fallback_queries
(분야 category를 건 일반 검색어, 검색어마다 PER_FALLBACK장)에서 모은다. 일반 검색어 덕분에
기사 맞춤 검색어가 모두 빗나가도 반도체·전자 분야 사진은 항상 몇 장 남는다.

검색어는 카드 JSON의 photo_queries(Claude가 쓴 영어 키워드 여러 개, 잘 맞는 순서)다.
예전 카드의 photo_query(한 개)도 읽는다. 이 스크립트는 판단하지 않는다:
검색어 순서대로 결과를 관련도 순서로 보고(검색어마다 최대 MAX_PAGES쪽), 아래 사진을 빼고 첫 번째 가로 사진을 고른다.
  - --exclude 사진, 최근 REUSE_DAYS일 카드에 쓴 사진 id
  - 최근 PHOTOGRAPHER_DAYS일 카드에 쓴 작가의 사진 (한 작가는 같은 장면을 여러 장 올린다)
  - 태그에 BLOCKED_TAG_WORDS(인물·음식·동물·돈 등)가 있는 사진. 실제로 1순위에 나와 매번 반려되던 것들이다
id와 작가가 달라도 같은 사진일 수 있다 (다른 계정이 다시 올린 사진). 그건 Claude가 scripts/contact_sheet.py로
최근 카드와 나란히 놓고 보고 --exclude로 뺀다. 이미지 해시로는 안개·잘림 차이 때문에 구분되지 않았다.
그래서 같은 검색어와 같은 이력이면 언제나 같은 사진이 나온다.
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
import time
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
# 이 기간(오늘 포함 이틀) 안에 다른 카드에 쓴 작가의 사진은 고르지 않는다.
# 3일이던 것을 줄였다: 후보가 많이 빠졌고, 같은 장면 재업로드는 contact sheet에서 눈으로 거른다.
PHOTOGRAPHER_DAYS = 1
MAX_PAGES = 2  # 검색어마다 앞쪽 결과가 모두 빠졌을 때만 다음 쪽을 본다
PER_QUERY = 4  # 후보 모드: 카드 검색어마다 모을 후보 수
PER_FALLBACK = 1  # 후보 모드: 일반 검색어마다 모을 후보 수
# 태그(공백으로 나눈 단어)에 하나라도 있으면 뺀다. 'wafer'가 과자, 'factory'가 작업자 얼굴로 나오던 사례에서 뽑았다.
# 'male'/'female'은 커넥터 태그에도 쓰여서 넣지 않는다.
BLOCKED_TAG_WORDS = {
    "woman", "women", "man", "men", "girl", "girls", "boy", "boys", "people", "person", "portrait", "face",
    "child", "children", "kid", "kids", "baby", "model", "businessman", "businesswoman", "worker", "selfie",
    "food", "dessert", "cake", "cupcake", "cupcakes", "cookie", "cookies", "waffle", "waffles", "candy", "bread",
    "fruit", "pastry", "pastries", "sweets", "snack", "drink", "coffee", "ice", "cream", "muffin", "muffins",
    "chocolate", "strawberry", "strawberries", "tasty", "delicious", "yummy", "breakfast", "meal",
    "animal", "animals", "dog", "cat", "bird", "elephant", "insect",
    "money", "cash", "dollar", "euro", "wallet", "bitcoin", "cryptocurrency", "banknote",
    "logo", "religion", "church", "wedding", "fashion", "blood", "puppet", "paperwork",
}
MIN_WIDTH = 1600  # 원본 기준. 카드 폭 1080px을 잘라 써도 흐려지지 않을 크기
USER_AGENT = "Semifeed/1.0 (+https://github.com/plt8172/Semifeed)"


def photo_path(card_path: Path) -> Path:
    return card_path.with_name(f"{card_path.stem}.photo.jpg")


class History:
    """최근 카드 JSON에 기록된 사진. 이력은 카드 JSON 한 곳에만 두고, 실행마다 다시 읽는다."""

    def __init__(self, cards_dir: Path, today: datetime, skip: Path, provider: str):
        self.ids: set[str] = set()  # 같은 제공처 사진 id
        self.photographers: set[str] = set()  # 같은 제공처 작가 페이지
        id_cutoff = (today - timedelta(days=REUSE_DAYS)).date()
        author_cutoff = (today - timedelta(days=PHOTOGRAPHER_DAYS)).date()
        for day_dir in cards_dir.glob("*"):
            try:
                day = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < id_cutoff:
                continue
            for path in day_dir.glob("*.json"):
                if path.resolve() == skip.resolve():
                    continue
                photo = (load_json(path, {}) or {}).get("photo") or {}
                if photo.get("provider") != provider:
                    continue
                if photo.get("id"):
                    self.ids.add(str(photo["id"]))
                if day >= author_cutoff and photographer_key(photo):
                    self.photographers.add(photographer_key(photo))


def photographer_key(photo: dict) -> str:
    return photo.get("photographer_url") or photo.get("photographer") or ""


def blocked(photo: dict) -> bool:
    words = {word for tag in photo.get("alt", "").lower().split(",") for word in tag.split()}
    return not words.isdisjoint(BLOCKED_TAG_WORDS)


def http_json(url: str, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            # 분당 요청 한도(Pixabay 100회)에 걸리면 한 번만 기다렸다가 다시 묻는다.
            if error.code != 429 or attempt:
                raise
            wait = error.headers.get("Retry-After") or error.headers.get("X-RateLimit-Reset") or "30"
            time.sleep(min(int(float(wait)) + 1, 60))
    raise AssertionError("unreachable")


class Pexels:
    """Pexels License: 상업 이용·수정 허용, 출처 표기 의무 없음."""

    name = "pexels"
    key_env = "PEXELS_API_KEY"
    license = {"name": "Pexels License", "url": "https://www.pexels.com/license/"}

    def __init__(self, key: str):
        self.key = key

    per_page = 80  # API 최대값

    def search(self, query: str, page: int = 1, category: str | None = None) -> list[dict]:
        # Pexels에는 분야 필터가 없어 category는 무시한다.
        params = urllib.parse.urlencode({"query": query, "orientation": "landscape", "per_page": self.per_page, "page": page})
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
            "thumb_url": p["src"].get("medium") or p["src"]["large2x"],
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

    per_page = 100  # API 최대값은 200이지만 두 번째 쪽까지 보면 충분하다

    def search(self, query: str, page: int = 1, category: str | None = None) -> list[dict]:
        extra = {"category": category} if category else {}
        hits = self._get(q=query, image_type="photo", orientation="horizontal", safesearch="true",
                         per_page=self.per_page, page=page, **extra)
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
            "thumb_url": h.get("webformatURL") or h["largeImageURL"],
            "page_url": h.get("pageURL", ""),
            "photographer": user,
            "photographer_url": f"https://pixabay.com/users/{user}-{user_id}/" if user else "",
            "alt": h.get("tags", ""),
        }


PROVIDERS = {cls.name: cls for cls in (Pixabay, Pexels)}


def usable(photo: dict, excluded: set[str], history: History) -> bool:
    if photo["id"] in excluded or photo["id"] in history.ids:
        return False
    if photographer_key(photo) in history.photographers or blocked(photo):
        return False
    return photo["width"] >= MIN_WIDTH and photo["width"] > photo["height"]


def candidates(provider, queries: list[str], excluded: set[str], history: History, stats: dict):
    """검색어 순서, 결과 순서대로 쓸 수 있는 사진을 내놓는다. 앞에서 고르면 뒤쪽은 요청하지 않는다."""
    seen: set[str] = set()
    for query in queries:
        for page in range(1, MAX_PAGES + 1):
            photos = provider.search(query, page)
            stats["results"] += len(photos)
            for photo in photos:
                if photo["id"] not in seen and usable(photo, excluded, history):
                    seen.add(photo["id"])
                    yield query, photo
            if len(photos) < provider.per_page:
                break  # 마지막 쪽


def candidate_pool(provider, queries: list[str], fallbacks: list[dict], excluded: set[str], history: History,
                   stats: dict) -> list[dict]:
    """후보 모드: 카드 검색어마다 앞에서 PER_QUERY장, 일반 검색어마다 PER_FALLBACK장. 순서가 곧 추천 순서다."""
    pool: list[dict] = []
    seen: set[str] = set()
    plan = [(f"q{i}", q, None, PER_QUERY) for i, q in enumerate(queries, 1)]
    plan += [(f"f{i}", f["query"], f.get("category"), PER_FALLBACK) for i, f in enumerate(fallbacks, 1)]
    for label, query, category, take in plan:
        photos = provider.search(query, 1, category)
        stats["results"] += len(photos)
        taken = 0
        for photo in photos:
            if taken == take:
                break
            if photo["id"] in seen or not usable(photo, excluded, history):
                continue
            seen.add(photo["id"])
            pool.append({**photo, "query": query, "category": category, "label": label})
            taken += 1
    return pool


def candidates_dir(card_path: Path) -> Path:
    return card_path.with_name(f"{card_path.stem}.candidates")


def load_fallbacks(config: dict) -> list[dict]:
    result = []
    for item in config.get("photo_fallback_queries") or []:
        if isinstance(item, str):
            item = {"query": item}
        if item.get("query"):
            result.append({"query": item["query"], "category": item.get("category")})
    return result


def gather(card_path: Path, provider, excluded: set[str], fallbacks: list[dict], cards_dir: Path) -> str:
    """후보를 모아 <id>.candidates/list.json과 썸네일로 둔다. 이미 사진이 있는 카드는 건너뛴다."""
    card = load_json(card_path, None)
    if card is None:
        raise ValueError("card JSON not found")
    if card.get("photo"):
        return f"already has photo {card['photo'].get('id')} (use --clear first to choose again)"
    queries = card_queries(card)
    history = History(cards_dir, datetime.now(KST), card_path, provider.name)
    stats = {"results": 0}
    pool = candidate_pool(provider, queries, fallbacks, excluded, history, stats)
    out = candidates_dir(card_path)
    if out.exists():
        for old in out.iterdir():
            old.unlink()
    out.mkdir(exist_ok=True)
    kept = []
    for photo in pool:
        thumb = f"{photo['id']}.jpg"
        try:
            download(photo["thumb_url"], out / thumb)
        except (urllib.error.URLError, ValueError, OSError):
            continue  # 썸네일이 없으면 눈으로 확인할 수 없으니 후보에서 뺀다
        kept.append({**photo, "thumb": thumb})
    write_json(out / "list.json", {"provider": provider.name, "candidates": kept})
    if not kept:
        raise ValueError(f"no usable candidates ({stats['results']} results)")
    from_card = sum(1 for p in kept if p["label"].startswith("q"))
    return f"{len(kept)} candidates ({from_card} from photo_queries, {len(kept) - from_card} fallback) -> {out}/"


def pick(card_path: Path, provider, photo_id: str, cards_dir: Path) -> str:
    card = load_json(card_path, None)
    if card is None:
        raise ValueError("card JSON not found")
    listing = load_json(candidates_dir(card_path) / "list.json", None)
    if not listing:
        raise ValueError("no candidates; run --candidates first")
    if listing.get("provider") != provider.name:
        raise ValueError(f"candidates are from {listing.get('provider')}; use --provider {listing.get('provider')}")
    photo = next((p for p in listing["candidates"] if p["id"] == photo_id), None)
    if photo is None:
        raise ValueError(f"photo {photo_id} is not a candidate of this card")
    history = History(cards_dir, datetime.now(KST), card_path, provider.name)
    if photo_id in history.ids:
        raise ValueError(f"photo {photo_id} is already used by another recent card")
    dest = photo_path(card_path)
    entry = record(provider, photo, photo["query"], dest.name)
    if photo.get("category"):
        entry["category"] = photo["category"]
    download(entry["download_url"], dest)
    card["photo"] = entry
    write_json(card_path, card)
    return f"{provider.name} {photo_id} ({photo['label']} {photo['query']!r}) -> {dest}"


def download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("downloaded file is not a JPEG")
    dest.write_bytes(data)


def card_queries(card: dict) -> list[str]:
    queries = card.get("photo_queries") or [card.get("photo_query") or ""]
    if isinstance(queries, str):
        queries = [queries]
    result = []
    for query in queries:
        query = str(query).strip()
        if query and query not in result:
            result.append(query)
    return result


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

    queries = card_queries(card)
    if not queries:
        raise ValueError("photo_queries is empty")
    history = History(cards_dir, datetime.now(KST), card_path, provider.name)
    skip = set(excluded)
    if existing:
        skip.add(str(existing.get("id")))
    stats = {"results": 0}
    found = next(candidates(provider, queries, skip, history, stats), None)
    if found is None:
        raise ValueError(f"no usable photo for queries {queries!r} ({stats['results']} results)")
    query, photo = found

    entry = record(provider, photo, query, dest.name)
    download(entry["download_url"], dest)
    card["photo"] = entry
    write_json(card_path, card)
    rank = queries.index(query) + 1
    return f"{provider.name} {entry['id']} via query {rank} {query!r} ({entry['alt'] or 'no alt'}) -> {dest}"


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
    parser.add_argument("--candidates", action="store_true",
                        help="고르지 않고 카드마다 후보와 썸네일을 <id>.candidates/에 모은다")
    parser.add_argument("--pick", metavar="PHOTO_ID", help="--candidates로 모은 후보 중 이 사진을 붙인다")
    parser.add_argument("--cards-dir", type=Path, default=CARDS_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.pick and len(args.cards) != 1:
        parser.error("--pick은 카드 하나에만 쓴다")
    if args.clear:
        for card_path in args.cards:
            clear(card_path)
            print(f"[ok  ] {card_path}: photo cleared", file=sys.stderr)
        return 0

    config = load_json(args.config, {})
    name = args.provider or config.get("photo_provider") or DEFAULT_PROVIDER
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
            if args.candidates:
                message = gather(card_path, provider, excluded, load_fallbacks(config), args.cards_dir)
            elif args.pick:
                message = pick(card_path, provider, str(args.pick), args.cards_dir)
            else:
                message = process(card_path, provider, excluded, args.replace, args.cards_dir)
            print(f"[ok  ] {card_path}: {message}", file=sys.stderr)
        except (urllib.error.URLError, ValueError, KeyError, OSError) as error:
            failed += 1
            print(f"[FAIL] {card_path}: {error}", file=sys.stderr)
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
