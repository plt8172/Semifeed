#!/usr/bin/env python3
"""처리한 기사 링크를 state/seen.json에 기록한다.

카드를 만든 시점에 기록하며 승인·반려 여부와는 무관하다.
반려된 기사가 다음 실행에서 다시 후보로 올라오지 않게 하기 위해서다.

    python3 scripts/mark_seen.py https://example.com/a https://example.com/b
    python3 scripts/mark_seen.py --prune-days 30   # 30일보다 오래된 기록 정리
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import KST, SEEN_PATH, load_seen, normalize_link, save_seen  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("links", nargs="*")
    parser.add_argument("--seen", type=Path, default=SEEN_PATH)
    parser.add_argument("--prune-days", type=int, help="이 일수보다 오래된 기록 삭제 (수집 창보다 길게 둔다)")
    args = parser.parse_args()

    now = datetime.now(KST)
    seen = load_seen(args.seen)
    for link in args.links:
        seen.setdefault(normalize_link(link), now.isoformat(timespec="seconds"))
    if args.prune_days:
        cutoff = now - timedelta(days=args.prune_days)
        seen = {k: v for k, v in seen.items() if datetime.fromisoformat(v) >= cutoff}
    save_seen(seen, args.seen)
    print(f"seen: {len(seen)} links -> {args.seen}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
