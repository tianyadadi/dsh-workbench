#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub 新增 public 仓库趋势 —— 单文件 CLI，零第三方依赖。

整个工具就这一个文件，拷走就能跑（只需要 Python 3.8+）：

    python github_trends.py                 # 最近 7 天，每天一行
    python github_trends.py --days 30       # 最近 30 天
    python github_trends.py --hours 12      # 最近 12 个整点
    python github_trends.py --range 2026-11-01T00:00 2026-11-07T00:00
    python github_trends.py --days 7 --csv out.csv
    python github_trends.py --days 7 --json

口径与 dsh-workbench 的「GitHub 新增」面板一致：
  · 新增仓库数 = GitHub Search API 的 total_count，只统计 public 仓库
    （私有仓库 API 查不到，不做）
  · 按 `created:` 切时间窗，区间是**本地时区**，查询时转 UTC
  · 本机直连 api.github.com 会被 TCP 重置，默认经 gh-proxy.com 转发；
    同目录有 config.json 时读它的 github_proxies / github_proxy

注意：这是自包含实现（不 import server.py）。如果改了抓取口径，
记得和 workbench/server.py 的 GitHub 模块保持一致。
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

DEFAULT_PROXY = "https://gh-proxy.com/"


# ---------------------------------------------------------------- 配置

def _load_proxies() -> list[str]:
    """优先读同目录 config.json 的 github_proxies / github_proxy。"""
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = {}
    try:
        with open(os.path.join(here, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        pass
    ps = [str(p).strip() for p in (cfg.get("github_proxies") or []) if str(p).strip()]
    if not ps:
        ps = [str(cfg.get("github_proxy") or DEFAULT_PROXY).strip()]
    return [p.rstrip("/") + "/" for p in ps if p]


PROXIES = _load_proxies()
_LAST_REQ = [0.0]


# ---------------------------------------------------------------- 抓取

def _gap():
    """Search API 30 次/分钟，匀速 2.4 秒一条。"""
    wait = 2.4 - (time.time() - _LAST_REQ[0])
    if wait > 0:
        time.sleep(wait)
    _LAST_REQ[0] = time.time()


def _utc_iso(d: datetime) -> str:
    from datetime import timezone
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(target: str, timeout: int = 30) -> dict:
    """经代理请求 GitHub API；多个代理失败自动轮换。"""
    last = None
    for base in PROXIES:
        try:
            req = urllib.request.Request(
                base + target,
                headers={"User-Agent": "github-trends-cli/1.0",
                         "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            continue
    raise last if last else RuntimeError("没有可用代理")


def _count(s: datetime, e: datetime) -> int:
    q = "created:%s..%s" % (_utc_iso(s), _utc_iso(e))
    _gap()
    data = _get("https://api.github.com/search/repositories?" +
                urllib.parse.urlencode({"q": q, "per_page": 1}))
    if isinstance(data, dict) and data.get("message") and "total_count" not in data:
        raise RuntimeError(str(data["message"])[:120])
    return int(data.get("total_count") or 0)


# ---------------------------------------------------------------- 输出

def _fmt(n) -> str:
    return "—" if n is None else format(n, ",")


def _bar(n: int, mx: int, width: int = 28) -> str:
    if mx <= 0:
        return ""
    k = max(0, min(width, round(n / mx * width)))
    return "█" * k + "·" * (width - k)


def main() -> int:
    ap = argparse.ArgumentParser(description="GitHub 新增 public 仓库趋势")
    ap.add_argument("--days", type=int, default=7, help="最近几天（默认 7）")
    ap.add_argument("--hours", type=int, default=0, help="最近几个整点（给了就忽略 --days）")
    ap.add_argument("--range", nargs=2, metavar=("FROM", "TO"),
                    help="自定义区间，如 2026-11-01T00:00 2026-11-07T00:00")
    ap.add_argument("--csv", metavar="FILE", help="导出 CSV")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    a = ap.parse_args()

    now = datetime.now().astimezone()

    # 自定义区间：只查一次
    if a.range:
        try:
            s = datetime.fromisoformat(a.range[0]).astimezone()
            e = datetime.fromisoformat(a.range[1]).astimezone()
        except ValueError:
            print("时间格式要 2026-11-01T00:00", file=sys.stderr)
            return 2
        if e <= s:
            print("结束时间要晚于开始时间", file=sys.stderr)
            return 2
        if (e - s).days > 366:
            print("区间最多 1 年", file=sys.stderr)
            return 2
        c = _count(s, e)
        r = {"count": c, "from": s.strftime("%Y-%m-%d %H:%M"), "to": e.strftime("%Y-%m-%d %H:%M")}
        if a.json:
            print(json.dumps(r, ensure_ascii=False))
        else:
            print("%s 个新仓库  %s → %s" % (_fmt(c), r["from"], r["to"]))
        return 0

    rows = []  # (label, count, ts)
    if a.hours > 0:
        cur = now.replace(minute=0, second=0, microsecond=0)
        for i in range(a.hours - 1, -1, -1):
            h0 = cur - timedelta(hours=i)
            h1 = now if i == 0 else h0 + timedelta(hours=1)
            rows.append((h0.strftime("%m-%d %H:%M"), _count(h0, h1), h0))
    else:
        for i in range(a.days - 1, -1, -1):
            d0 = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            d1 = now if i == 0 else d0 + timedelta(days=1)
            rows.append((d0.strftime("%m-%d"), _count(d0, d1), d0))

    if a.json:
        print(json.dumps([{"label": r[0], "count": r[1], "ts": int(r[2].timestamp())}
                          for r in rows], ensure_ascii=False))
        return 0

    if a.csv:
        with open(a.csv, "w", encoding="utf-8-sig", newline="") as f:
            f.write("时间,新增仓库\n")
            for label, c, _ in rows:
                f.write("%s,%s\n" % (label, c))
        print("已写 %s（%d 行）" % (a.csv, len(rows)))
        return 0

    total = sum(c for _, c, _ in rows)
    mx = max((c for _, c, _ in rows), default=0)
    print("GitHub 新增 public 仓库  %s  （代理：%s）" % (
        "最近 %d 个整点" % a.hours if a.hours else "最近 %d 天" % a.days, PROXIES[0]))
    print("-" * 58)
    for label, c, _ in rows:
        print("%-12s %9s  %s" % (label, _fmt(c), _bar(c, mx)))
    print("-" * 58)
    print("合计 %s" % _fmt(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())