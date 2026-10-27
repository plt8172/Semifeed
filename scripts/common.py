"""Semifeed 스크립트가 함께 쓰는 경로·링크 정규화·상태 파일 처리."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "semifeed.json"
SEEN_PATH = ROOT / "state" / "seen.json"
KST = timezone(timedelta(hours=9))

# 같은 기사가 추적 파라미터만 달리해 다시 들어오는 경우를 막기 위해 제거한다.
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "cmpid"}


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_link(link: str) -> str:
    """중복 판정용 링크: 스킴·호스트 소문자화, www 제거, utm_*·추적 파라미터·fragment 제거."""
    parts = urlsplit(link.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", host, path, urlencode(query), ""))


def card_id(link: str) -> str:
    """정규화 링크의 해시 앞 10자리. 같은 기사는 어느 실행에서든 같은 id를 갖는다."""
    return hashlib.sha1(normalize_link(link).encode("utf-8")).hexdigest()[:10]


def source_of(link: str) -> str:
    host = urlsplit(link).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def load_seen(path: Path = SEEN_PATH) -> dict[str, str]:
    """{정규화 링크: 기록 시각(ISO)}. 파일이 없으면 빈 상태로 시작한다."""
    data = load_json(path, {"links": {}})
    return dict(data.get("links", {}))


def save_seen(links: dict[str, str], path: Path = SEEN_PATH) -> None:
    write_json(path, {"links": dict(sorted(links.items()))})
