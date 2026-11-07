#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub 新增仓库趋势 —— 工作台 GitHub 面板的独立命令行版。

不需要启动工作台，也不受面板开关影响（手动跑一次抓一次）。
零第三方依赖，复用 server.py 里的抓取函数（同一套代理/节流/口径）。

用法
----
    python github_trends.py                 # 最近 7 天，每天一行
    python github_trends.py --days 30       # 最近 30 天
    python github_trends.py --hours 12      # 最近 12 个整点
    python github_trends.py --range 2026-11-01T00:00 2026-11-07T00:00
    python github_trends.py --days 7 --csv out.csv
    python github_trends.py --days 7 --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server as wb  # noqa: E402  —— 复用同一套抓取函数


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
        r = wb._gh_query_range(s, e)
        if not r.get("ok"):
            print("查询失败：%s" % r.get("error"), file=sys.stderr)
            return 1
        if a.json:
            print(json.dumps(r, ensure_ascii=False))
        else:
            print("%s 个新仓库  %s → %s" % (_fmt(r["count"]), r["from"], r["to"]))
        return 0

    rows = []  # (label, count, ts)
    if a.hours > 0:
        cur = now.replace(minute=0, second=0, microsecond=0)
        for i in range(a.hours - 1, -1, -1):
            h0 = cur - timedelta(hours=i)
            h1 = now if i == 0 else h0 + timedelta(hours=1)
            c = wb._gh_fetch_count(h0, h1)["c"]
            rows.append((h0.strftime("%m-%d %H:%M"), c, h0))
    else:
        for i in range(a.days - 1, -1, -1):
            d0 = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            d1 = now if i == 0 else d0 + timedelta(days=1)
            c = wb._gh_fetch_count(d0, d1)["c"]
            rows.append((d0.strftime("%m-%d"), c, d0))

    if a.json:
        print(json.dumps([{"label": r[0], "count": r[1], "ts": int(r[2].timestamp())} for r in rows],
                         ensure_ascii=False))
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
        "最近 %d 个整点" % a.hours if a.hours else "最近 %d 天" % a.days, wb.GH_PROXY))
    print("-" * 58)
    for label, c, _ in rows:
        print("%-12s %9s  %s" % (label, _fmt(c), _bar(c, mx)))
    print("-" * 58)
    print("合计 %s" % _fmt(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())