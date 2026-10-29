#!/usr/bin/env python3
"""RSS/Atom 피드를 수집해 최근 N시간 안의 새 기사만 candidates.json으로 쓴다.

결정적인 일만 한다: 수집, 시간 필터, 중복 제거, 출처별 개수 제한.
어떤 기사를 카드로 만들지는 이 결과를 읽는 Claude가 판단한다.

    python3 scripts/fetch.py                    # config/semifeed.json의 feeds 수집
    python3 scripts/fetch.py --feed a.xml ...   # 로컬 파일·URL로 대체 (오프라인 검증용)
    python3 scripts/fetch.py --now 2026-10-19T09:00:00+09:00

표준 라이브러리만 사용한다. 예약 작업 환경에서 설치 단계 없이 돌아가게 하기 위해서다.
종료 코드: 0 = 피드 하나 이상 성공, 1 = 모든 피드 실패.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG_PATH, KST, ROOT, SEEN_PATH, card_id, load_json, load_seen, normalize_link, source_of, write_json  # noqa: E402

USER_AGENT = "Mozilla/5.0 (compatible; Semifeed/2.0; +https://github.com/plt8172/Semifeed)"
TIMEOUT_SECONDS = 20
SUMMARY_LIMIT = 600

ATOM = "{http://www.w3.org/2005/Atom}"


def read_feed(location: str) -> bytes:
    path = Path(location)
    if path.exists():
        return path.read_bytes()
    request = urllib.request.Request(location, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def parse_xml(raw: bytes) -> ET.Element:
    """expat이 모르는 인코딩(EUC-KR 등)도 읽도록 직접 디코딩한 뒤 파싱한다."""
    head = raw[:200].decode("ascii", errors="ignore")
    match = re.search(r'encoding=["\']([A-Za-z0-9_\-]+)["\']', head)
    encoding = match.group(1) if match else "utf-8"
    try:
        text = raw.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        text = raw.decode("utf-8", errors="replace")
    text = text.lstrip("﻿")
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    # XML 1.0에서 허용하지 않는 제어 문자가 섞인 피드가 있어 제거한다.
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return ET.fromstring(text)


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        # 시간대 없는 날짜는 국내 매체가 대부분이라 KST로 본다.
        parsed = parsed.replace(tzinfo=KST)
    return parsed


def clean_text(value: str | None, limit: int | None = None) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def find_text(element: ET.Element, *tags: str) -> str | None:
    for tag in tags:
        child = element.find(tag)
        if child is not None and (child.text or "").strip():
            return child.text
    return None


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_entries(root: ET.Element) -> list[dict]:
    entries = []
    if root.tag == f"{ATOM}feed":
        for entry in root.findall(f"{ATOM}entry"):
            link = None
            for candidate in entry.findall(f"{ATOM}link"):
                if candidate.get("rel", "alternate") == "alternate" and candidate.get("href"):
                    link = candidate.get("href")
                    break
            entries.append({
                "title": find_text(entry, f"{ATOM}title"),
                "link": link,
                "date": find_text(entry, f"{ATOM}published", f"{ATOM}updated"),
                "summary": find_text(entry, f"{ATOM}summary", f"{ATOM}content"),
            })
    else:
        # RSS 2.0과 RSS 1.0(RDF)은 네임스페이스만 다르므로 로컬 태그명으로 읽는다.
        for item in (e for e in root.iter() if local(e.tag) == "item"):
            fields: dict[str, str] = {}
            for child in item:
                name = local(child.tag)
                if child.text and child.text.strip() and name not in fields:
                    fields[name] = child.text
            entries.append({
                "title": fields.get("title"),
                "link": fields.get("link") or fields.get("guid"),
                "date": fields.get("pubDate") or fields.get("date"),
                "summary": fields.get("description") or fields.get("encoded"),
            })
    return entries


def collect(feeds: list[str], now: datetime, hours: int, seen: dict[str, str], per_source: int) -> tuple[list[dict], list[dict]]:
    cutoff = now - timedelta(hours=hours)
    items: dict[str, dict] = {}
    report = []
    for feed in feeds:
        status = {"feed": feed, "ok": False, "entries": 0, "kept": 0}
        try:
            entries = parse_entries(parse_xml(read_feed(feed)))
        except Exception as error:  # 피드 하나의 실패가 전체 실행을 멈추지 않게 한다.
            status["error"] = f"{type(error).__name__}: {error}"
            report.append(status)
            continue
        status.update(ok=True, entries=len(entries))
        for entry in entries:
            link = (entry["link"] or "").strip()
            title = clean_text(entry["title"])
            published = parse_date(entry["date"])
            if not link.startswith("http") or not title or published is None:
                continue
            if published < cutoff or published > now + timedelta(hours=1):
                continue
            key = normalize_link(link)
            if key in seen or key in items:
                continue
            items[key] = {
                "id": card_id(link),
                "title": title,
                "link": link,
                "source": source_of(link),
                "feed": feed,
                "published_at": published.astimezone(KST).isoformat(timespec="minutes"),
                "summary": clean_text(entry["summary"], SUMMARY_LIMIT),
            }
            status["kept"] += 1
        report.append(status)

    # 출처별 최신순으로 per_source개까지만 남겨 한 매체가 후보를 독점하지 않게 한다.
    by_source: dict[str, list[dict]] = {}
    for item in sorted(items.values(), key=lambda i: i["published_at"], reverse=True):
        bucket = by_source.setdefault(item["source"], [])
        if len(bucket) < per_source:
            bucket.append(item)
    candidates = [item for source in sorted(by_source) for item in by_source[source]]
    return candidates, report


def source_name(host: str, names: dict[str, str]) -> str:
    """카드에 표시할 매체명. rss.etnews.com처럼 하위 도메인이 붙어도 찾는다. 없으면 호스트 그대로."""
    for domain, name in names.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--seen", type=Path, default=SEEN_PATH)
    parser.add_argument("--out", type=Path, default=ROOT / "candidates.json")
    parser.add_argument("--feed", action="append", help="config의 feeds 대신 사용할 URL 또는 로컬 파일 (반복 가능)")
    parser.add_argument("--now", help="기준 시각 (ISO 8601). 기본값은 현재 시각")
    parser.add_argument("--per-source", type=int, default=8, help="출처별 최대 후보 수")
    args = parser.parse_args()

    config = load_json(args.config, {})
    feeds = args.feed or config.get("feeds", [])
    hours = int(config.get("hours_window", 72))
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=KST)

    candidates, report = collect(feeds, now, hours, load_seen(args.seen), args.per_source)
    names = config.get("source_names", {})
    for item in candidates:
        item["source_name"] = source_name(item["source"], names)
    write_json(args.out, {
        "generated_at": now.astimezone(KST).isoformat(timespec="seconds"),
        "hours_window": hours,
        "feeds": report,
        "candidates": candidates,
    })

    for status in report:
        mark = "ok  " if status["ok"] else "FAIL"
        detail = f"{status['kept']}/{status['entries']}" if status["ok"] else status["error"]
        print(f"[{mark}] {status['feed']}  {detail}", file=sys.stderr)
    print(f"candidates: {len(candidates)} -> {args.out}", file=sys.stderr)
    return 0 if any(s["ok"] for s in report) else 1


if __name__ == "__main__":
    sys.exit(main())
