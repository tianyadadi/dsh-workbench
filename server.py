#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 本地工作台 —— 零第三方依赖的本地可视化服务。

设计要点
--------
* 只读本地文件：不联网、不调用模型、不消耗 token。
* 面板可扩展：在 PANELS 里注册一个 (key, scan_fn) 就多一个面板，
  前端 /api/panels 自动生成导航，不需要改 HTML。
* 数据全部现扫现返回，不落缓存，改完文件刷新页面即可。

用法
----
    python server.py --port 8799
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------------------------------------------------------------- 路径

HERE = Path(__file__).resolve().parent


def _cfg_load():
    f = HERE / "config.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


_CONFIG = _cfg_load()


def _expand(v):
    return os.path.expandvars(os.path.expanduser(str(v))) if v else ""


def _pick(*cands):
    """返回第一个存在的路径，全都不存在返回 None。"""
    for c in cands:
        if not c:
            continue
        try:
            pp = Path(_expand(c))
            if pp.exists():
                return pp
        except (OSError, ValueError):
            continue
    return None


DSH_HOME = Path(_expand(_CONFIG.get("dsh_home")
                        or os.environ.get("DSH_HOME")
                        or (Path.home() / ".dsh")))
PROFILE = DSH_HOME / "profiles" / "desktop"
SESSIONS = DSH_HOME / "storages" / "session_projcache" / "sessions"
ART_CONFIG = DSH_HOME / "artcraft.config.json"

# 插件安装目录（node_modules）
MODULES = _pick(
    _CONFIG.get("modules_dir"),
    os.environ.get("DSH_MODULES_DIR"),
    DSH_HOME.parent / "chajian" / "node_modules",
    DSH_HOME / "node_modules",
) or (DSH_HOME / "node_modules")

# 记忆库目录（含 index.sqlite）
MEMORY_DIR = _pick(
    _CONFIG.get("memory_dir"),
    os.environ.get("DSH_MEMORY_DIR"),
    DSH_HOME.parent / "memory",
    DSH_HOME / "memory",
) or (DSH_HOME / "memory")

# 交接文档目录（HANDOFF.md + archive/，给「文档占比」饼图用）
WORKAREA = _pick(
    _CONFIG.get("workarea_dir"),
    os.environ.get("DSH_WORKAREA_DIR"),
    DSH_HOME.parent / "workarea",
    DSH_HOME / "workarea",
) or (DSH_HOME / "workarea")

# ArtCraft 安装目录
ART_DIR = _pick(
    _CONFIG.get("artcraft_dir"),
    os.environ.get("DSH_ARTCRAFT_DIR"),
    DSH_HOME.parent / "artcraft",
    DSH_HOME / "artcraft",
) or (DSH_HOME / "artcraft")

# DSH 运行时目录（只读版本号，找不到就显示 "?"）
RUNTIME = _pick(
    _CONFIG.get("runtime_dir"),
    os.environ.get("DSH_RUNTIME_DIR"),
    DSH_HOME.parent / "harness" / "resources" / "runtime",
    Path.home() / "AppData" / "Local" / "Programs" / "deepseek-harness" / "resources" / "runtime",
) or (HERE / "_runtime_missing_")

# 插件 → 注册工具数（源码里 grep 不可靠，这里维护实测值；新插件按需补）
TOOL_COUNTS = {
    "@ninkch/dsh-artcraft": 10,
    "dsh-douyin-lite": 13,
    "dsh-task-ledger": 3,
    "dsh-ops": 6,
}

# 插件用途一句话（新装插件补这里，缺省显示包名）
PLUGIN_NOTES = {
    "@deepseek-ai/dsh-base": "DSH 内核基础层",
    "@deepseek-ai/dsh-web-app": "Web 界面外壳",
    "@ninkch/dsh-artcraft": "ArtCraft 家族桥接：10 工具 + 13 技能",
    "dsh-douyin-lite": "抖音浏览/日报/评论/私信",
    "dsh-task-ledger": "任务账本（待办登记与结账）",
    "dsh-ops": "文件读写检索与命令执行（ops_* 工具）",
    "dsh-plugin-wallpaper-engine": "动态壁纸引擎（含 7 个子包）",
    "dsh-whale-widget": "桌面鲸鱼挂件",
    "dsh-boot-animation": "开机动画",
    "dsh-language-rule": "强制中文规则",
    "dsh-campus-net": "校园网工具",
    "dsh-auto-maximize": "自动最大化窗口",
    "dshmarket": "插件市场",
    "@smalltailqwq/dsh-client-ui-skin-deep-whale-manager": "皮肤：深海鲸",
    "@smalltailqwq/dsh-client-ui-skin-maid-atelier": "皮肤：女仆工坊",
    "@smalltailqwq/dsh-client-ui-skin-orca-link": "皮肤：虎鲸链接",
}

KIND_CN = {
    "pitfall": "踩坑", "decision": "决定", "preference": "偏好",
    "context": "背景", "todo": "待办",
}

_VER_CACHE = {"v": None}
_SIZE_CACHE: dict = {}


# ---------------------------------------------------------------- 工具函数

def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024
    return "%.1f GB" % n


def dir_size(p: Path, limit: int = 40000) -> int:
    key = str(p)
    hit = _SIZE_CACHE.get(key)
    if hit and time.time() - hit[1] < 300:
        return hit[0]
    total, seen = 0, 0
    if not p.exists():
        return 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
            seen += 1
            if seen > limit:
                break
        if seen > limit:
            break
    _SIZE_CACHE[key] = (total, time.time())
    return total


def read_frontmatter(path: Path) -> dict:
    """读 SKILL.md 的 YAML frontmatter（只取 name/description，够用）。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if mm:
            out[mm.group(1)] = mm.group(2).strip().strip('"').strip("'")
    return out


def load_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


# ---------------------------------------------------------------- 扫描器

def scan_overview() -> dict:
    bundles = load_json(PROFILE / "package.json", {}).get("dsh", {}).get("profile", {}).get("bundles", [])
    skills = scan_skills()
    entries = scan_memory()["items"]
    cost = scan_cost()
    return {
        "dsh_version": _dsh_version(),
        "bundles": len(bundles),
        "skills_total": len(skills["items"]),
        "skills_user": len([s for s in skills["items"] if s["source"] == "用户"]),
        "memory_total": len(entries),
        "memory_active": len([e for e in entries if e["lifecycle"] == "Active"]),
        "memory_dormant": len([e for e in entries if e["lifecycle"] == "Dormant"]),
        "tools_tokens": cost.get("tools_tokens", 0),
        "system_tokens": cost.get("system_tokens", 0),
        "session_cost": cost.get("total_cost", 0),
        "artcraft_found": len([a for a in scan_artcraft()["items"] if a["found"]]),
        "disk": {
            "modules": human_size(dir_size(MODULES)),
            "artcraft": human_size(dir_size(ART_DIR)),
            "memory": human_size(dir_size(MEMORY_DIR)),
        },
        "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _dsh_version() -> str:
    if _VER_CACHE["v"]:
        return _VER_CACHE["v"]
    v = "?"
    # 1) 优先读预先生成的 version.txt（后台服务里调 dsh.cmd 不可靠）
    vf = HERE / "version.txt"
    try:
        if vf.exists():
            txt = vf.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            if txt:
                v = txt[0].strip()
    except Exception:
        pass
    # 2) 兜底：直接调用 CLI
    if v in ("", "?"):
        cli = RUNTIME / "cli" / "bin" / "dsh.cmd"
        try:
            import subprocess
            out = subprocess.run(["cmd", "/c", str(cli), "--version"],
                                 capture_output=True, text=True, timeout=25,
                                 stdin=subprocess.DEVNULL)
            lines = [x.strip() for x in (out.stdout or "").splitlines() if x.strip()]
            if lines:
                v = lines[-1]
        except Exception:
            pass
    _VER_CACHE["v"] = v
    return v


def scan_plugins() -> dict:
    pkg = load_json(PROFILE / "package.json", {})
    bundles = pkg.get("dsh", {}).get("profile", {}).get("bundles", [])
    deps = pkg.get("dependencies", {})
    # 已启用的（bundles）+ 装着但被关掉的（dependencies 里有、bundles 里没有）
    names = list(bundles)
    for d in deps:
        if d in names or d.startswith("@deepseek-ai/"):
            continue
        if "dsh" in d.lower() or "dsh" in d.lower():
            names.append(d)
    items = []
    for b in names:
        enabled = b in bundles
        path = MODULES / b
        present = path.exists() or b.startswith("@deepseek-ai")
        size = dir_size(path) if path.exists() else 0
        meta = load_json(path / "package.json", {}) if path.exists() else {}
        ver = meta.get("version") or deps.get(b) or ("内置" if b.startswith("@deepseek-ai") else "?")
        items.append({
            "name": b,
            "note": PLUGIN_NOTES.get(b, ""),
            "version": ver,
            "tools": TOOL_COUNTS.get(b, 0),
            "size": human_size(size),
            "present": present,
            "enabled": enabled,
            "configurable": (b in PLUGIN_CONFIGS) or (find_plugin_config(b) is not None),
            "protected": b in PROTECTED_BUNDLES,
            "is_builtin": b.startswith("@deepseek-ai"),
        })
    return {"items": items, "count": len(items), "doc": memory_doc()}


def scan_skills() -> dict:
    items = []
    seen = set()

    def add(path: Path, source: str):
        fm = read_frontmatter(path)
        name = fm.get("name") or path.parent.name
        if not name or name in seen:
            return
        seen.add(name)
        desc = fm.get("description", "")
        if len(desc) > 160:
            desc = desc[:160] + "…"
        items.append({
            "name": name,
            "source": source,
            "desc": desc,
            "path": str(path.parent),
            "tokens": round(len(desc) * 0.7 + 80),
        })

    # 1) 用户技能（junction 到 E 盘）
    user_dir = DSH_HOME / "skills"
    if user_dir.exists():
        for sub in sorted(user_dir.iterdir()):
            md = sub / "SKILL.md"
            if md.exists():
                add(md, "用户")

    # 2) DSH 内置技能
    builtin = RUNTIME / "office-skills"
    if builtin.exists():
        for sub in sorted(builtin.iterdir()):
            md = sub / "SKILL.md"
            if md.exists():
                add(md, "内置")

    # 3) 插件自带技能
    for pkg_name, label in (("@ninkch/dsh-artcraft", "ArtCraft"),):
        sk = MODULES / pkg_name / "skills"
        if sk.exists():
            for sub in sorted(sk.iterdir()):
                md = sub / "SKILL.md"
                if md.exists():
                    add(md, label)

    return {"items": items, "count": len(items), "doc": memory_doc()}


def memory_doc() -> dict:
    """解析 MEMORY.md（人类可读的时间线快照），给太阳视图用。"""
    md = MEMORY_DIR / "MEMORY.md"
    if not md.exists():
        return {"ok": False, "error": "MEMORY.md 不存在"}
    try:
        text = md.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "error": str(e)}
    snaps = re.findall(r"^## 快照\s+(\d{8}-\d{6})\s*(?:（([^）]*)）)?", text, re.M)
    entries = len(re.findall(r"^- \*\*\[", text, re.M))
    return {
        "ok": True,
        "path": str(md),
        "bytes": md.stat().st_size,
        "snapshots": len(snaps),
        "entries": entries,
        "latest": snaps[-1][0] if snaps else "",
        "latestNote": (snaps[-1][1] if snaps and len(snaps[-1]) > 1 else "") or "",
        "recent": [{"t": a, "note": b or ""} for a, b in snaps[-6:]][::-1],
    }


def scan_memory() -> dict:
    db = MEMORY_DIR / "index.sqlite"
    items = []
    if not db.exists():
        return {"items": [], "count": 0, "doc": memory_doc()}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, created_at, kind, title, tags, importance, activation, confidence,"
            " lifecycle_state, recall_count, reinforcement_count, verified, scope"
            " FROM entries WHERE deleted=0 ORDER BY id DESC"
        ).fetchall()
        for r in rows:
            items.append({
                "id": r["id"],
                "kind": r["kind"],
                "kind_cn": KIND_CN.get(r["kind"], r["kind"]),
                "title": r["title"],
                "tags": r["tags"] or "",
                "created": (r["created_at"] or "")[:10],
                "importance": round(r["importance"] or 0, 2),
                "activation": round(r["activation"] or 0, 2),
                "confidence": round(r["confidence"] or 0, 2),
                "lifecycle": r["lifecycle_state"] or "Active",
                "recalls": r["recall_count"] or 0,
                "reinforce": r["reinforcement_count"] or 0,
                "verified": r["verified"] or 0,
                "scope": r["scope"] or "",
            })
        con.close()
    except Exception as e:  # noqa: BLE001
        return {"items": [], "count": 0, "error": str(e), "doc": memory_doc()}
    return {"items": items, "count": len(items), "doc": memory_doc()}


# ---------------------------------------------------------------- 文档体量（按天 / 按月）

DOC_DAY_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
DOC_SNAP_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})-\d{6}")


def _doc_sources():
    """交接文档 + 记忆文档，全部本地 .md，只读。"""
    out = []
    h = WORKAREA / "HANDOFF.md"
    if h.exists():
        out.append(h)
    arch = WORKAREA / "archive"
    if arch.exists():
        out.extend(sorted(arch.glob("*.md")))
    m = MEMORY_DIR / "MEMORY.md"
    if m.exists():
        out.append(m)
    return out


def _section_day(title: str, body: str, fallback: str) -> str:
    m = DOC_DAY_RE.search(title) or DOC_DAY_RE.search(body[:800])
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
    m = DOC_SNAP_RE.search(title)
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
    return fallback


def scan_docstats() -> dict:
    """按天/按月统计文档体量占比（纯本地扫描，不联网、不耗 token）。

    口径：每个 .md 按 `## ` 切成节，节内取第一个日期（标题优先，其次正文前 800 字）；
    没有日期的节归到文件修改日期。MEMORY.md 的「## 快照 20261106-025729」也认。
    """
    days, months, files = {}, {}, []
    total_lines = total_bytes = 0

    for p in _doc_sources():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            mtime = time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))
        except Exception:  # noqa: BLE001
            continue

        fl = fb = 0
        for part in re.split(r"(?m)^(?=## )", text):
            if not part.strip():
                continue
            lines = part.count("\n") + (0 if part.endswith("\n") else 1)
            nbytes = len(part.encode("utf-8"))
            head = part.split("\n", 1)
            title = head[0].strip()
            body = head[1] if len(head) > 1 else ""
            day = _section_day(title, body, mtime)
            month = day[:7]
            for bucket, key in ((days, day), (months, month)):
                e = bucket.setdefault(key, {"lines": 0, "bytes": 0, "files": set()})
                e["lines"] += lines
                e["bytes"] += nbytes
                e["files"].add(p.name)
            fl += lines
            fb += nbytes
            total_lines += lines
            total_bytes += nbytes

        files.append({
            "name": p.name,
            "lines": fl,
            "bytes": fb,
            "kind": "archive" if "archive" in p.parts else ("memory" if p.name == "MEMORY.md" else "handoff"),
        })

    def finish(bucket):
        rows = []
        for k in sorted(bucket):
            e = bucket[k]
            rows.append({
                "key": k,
                "lines": e["lines"],
                "bytes": e["bytes"],
                "files": sorted(e["files"]),
                "pct": round(e["lines"] * 100.0 / total_lines, 2) if total_lines else 0.0,
            })
        return rows

    return {
        "ok": True,
        "days": finish(days),
        "months": finish(months),
        "files": sorted(files, key=lambda x: -x["lines"]),
        "total": {"lines": total_lines, "bytes": total_bytes, "files": len(files)},
        "sources": [str(p) for p in _doc_sources()],
    }


# ---------------------------------------------------------------- 待人工（注意力面板）

HANDOFF_LINE_LIMIT = 450


def scan_attention() -> dict:
    """只列「需要人处理」的事，健康项不占位。

    这条原则抄自 dsh-superagent 的 000-philosophy / 005-panel：
    * Quiet by default —— 一切正常时只留一行灰字，不摆卡片。
    * 问题必须可行动 —— 每条都给出「下一步做什么」。
    * 计数等于列表长度 —— 不虚报。
    """
    items = []
    checks = 0

    def issue(level, title, detail="", action=""):
        items.append({"level": level, "title": title, "detail": detail, "action": action})

    # 1) 配置里的关键路径
    for label, p, key in (("插件目录", MODULES, "modules_dir"),
                          ("记忆库", MEMORY_DIR, "memory_dir"),
                          ("ArtCraft", ART_DIR, "artcraft_dir"),
                          ("交接文档", WORKAREA, "workarea_dir")):
        checks += 1
        if not p.exists():
            issue("error", f"{label}路径不存在", str(p), f"改 config.json 里的 {key}")

    # 2) 加载列表里有、盘上没有 —— 典型「装了一半」
    #    核心包（dsh-base / dsh-web-app）自带在 DSH 里，不在 node_modules，必须跳过，
    #    否则每天都在报一条「不能关也修不了」的假问题。
    bundles = load_json(PROFILE / "package.json", {}).get("dsh", {}).get("profile", {}).get("bundles", [])
    checks += 1
    missing = [b for b in bundles
               if b not in PROTECTED_BUNDLES and not (MODULES / b).exists()]
    if missing:
        issue("error", f"{len(missing)} 个插件在加载列表里但目录不存在",
              "、".join(missing[:3]) + ("…" if len(missing) > 3 else ""),
              "到「插件」面板关掉或重装")

    # 3) 交接文档体量（超了就提醒归档，和 handoff.py 同一阈值）
    h = WORKAREA / "HANDOFF.md"
    if h.exists():
        checks += 1
        try:
            n = len(h.read_text(encoding="utf-8", errors="replace").splitlines())
            if n > HANDOFF_LINE_LIMIT:
                issue("warn", f"HANDOFF.md 已 {n} 行（上限 {HANDOFF_LINE_LIMIT}）",
                      "旧的一次性事项该搬进 archive/ 了",
                      "在 workarea 里跑 python handoff.py archive")
        except Exception:  # noqa: BLE001
            issue("warn", "HANDOFF.md 读不出来", str(h), "检查文件权限或编码")

    # 4) 记忆库
    checks += 1
    if not (MEMORY_DIR / "index.sqlite").exists():
        issue("warn", "记忆库 index.sqlite 不存在", "记忆面板会是空的", "跑 mem.cmd init")

    return {
        "items": items,
        "count": len(items),
        "checks": checks,
        "ok": not items,
        "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def scan_cost() -> dict:
    files = sorted(SESSIONS.glob("session-*.json"), key=os.path.getmtime) if SESSIONS.exists() else []
    if not files:
        return {}
    d = load_json(files[-1], {})
    rows = d.get("record", {}).get("rows", {})
    tu = rows.get("tokenUsage", {}).get("val", {})
    totals = tu.get("totals", {}) if isinstance(tu, dict) else {}
    cb = rows.get("contextBreakdown", {}).get("val", {})
    bd = cb.get("breakdown", {}) if isinstance(cb, dict) else {}
    ss = rows.get("sessionStats", {}).get("val", {})
    uncached = totals.get("uncachedInputTokens", 0)
    cache = totals.get("cacheReadTokens", 0)
    out = totals.get("outputTokens", 0)
    # 单价：元 / 百万 token（与 ctxcost 默认一致，可在页面里改）
    price_in, price_cache, price_out = 1.0, 0.1, 2.0
    total_cost = (uncached * price_in + cache * price_cache + out * price_out) / 1e6
    return {
        "session": files[-1].stem,
        "tools_tokens": bd.get("toolsTokens", 0),
        "system_tokens": bd.get("systemTokens", 0),
        "message_tokens": bd.get("messageTokens", 0),
        "surface_tokens": cb.get("surfaceTokens", 0),
        "uncached_input": uncached,
        "cache_read": cache,
        "output": out,
        "cache_rate": round(cache / (uncached + cache) * 100, 1) if (uncached + cache) else 0,
        "turns": ss.get("turns", 0),
        "steps": ss.get("steps", 0),
        "total_cost": round(total_cost, 4),
    }


def scan_artcraft() -> dict:
    cfg = load_json(ART_CONFIG, {})
    bins = cfg.get("bins", {})
    items = []
    for app in ("photocraft", "vectorcraft", "filmcraft", "lightcraft", "effectcraft",
                "soundcraft", "pdfcraft", "designcraft", "wordcraft", "deckcraft",
                "gridcraft", "cadcraft", "figcraft", "solidcraft"):
        raw = bins.get(app)
        found, exe = False, ""
        if raw:
            p = Path(raw)
            if p.is_dir():
                for f in p.iterdir():
                    if f.suffix.lower() == ".exe" and f.stem.lower() == app + "-cli":
                        found, exe = True, str(f)
            elif p.is_file():
                found, exe = True, str(p)
        items.append({"app": app, "configured": raw or "", "found": found, "exe": exe, "enabled": app in bins})
    return {"items": items, "count": len([i for i in items if i["found"]])}


def scan_tools() -> dict:
    """工具定义占用：总数来自会话缓存，明细按插件估算。"""
    cost = scan_cost()
    total = cost.get("tools_tokens", 0)
    plugins = scan_plugins()["items"]
    known = [(p["name"], p["tools"]) for p in plugins if p["tools"]]
    known_n = sum(n for _, n in known)
    per_builtin = round(total * 0.5 / 28) if total else 0  # 内置工具约 28 个
    items = []
    for name, n in known:
        items.append({"group": name, "tools": n, "tokens": round(total * 0.5 * n / known_n) if known_n else 0})
    items.append({"group": "DSH 内置 + ops", "tools": 28, "tokens": round(total * 0.5)})
    return {"items": items, "total": total}


# ── Agent 面板：读写 ~/.dsh/agents/（dsh-agent-hub 插件用的那份定义）──────────
AGENTS_DIR = DSH_HOME / "agents"


def _read_json_file(path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


def _write_json_file(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


def scan_agents():
    """列出所有 agent：启用状态、绑定技能、所属 persona 摘要。"""
    agents_path = AGENTS_DIR / "agents.json"
    ui_path = AGENTS_DIR / "ui.json"
    cfg = _read_json_file(agents_path, {"version": 1, "agents": []})
    ui = {"selectorVisible": True, **_read_json_file(ui_path, {})}
    raw = cfg.get("agents", []) if isinstance(cfg, dict) else []
    items = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        items.append({
            "id": str(a.get("id") or ""),
            "name": str(a.get("name") or a.get("id") or ""),
            "icon": str(a.get("icon") or ""),
            "order": a.get("order") if isinstance(a.get("order"), (int, float)) else 100,
            "enabled": a.get("enabled") is not False,
            "description": str(a.get("description") or ""),
            "skills": [str(s) for s in (a.get("skills") or [])],
            "persona": str(a.get("persona") or ""),
            "disabledTools": [str(t) for t in (a.get("disabledTools") or [])],
        })
    items.sort(key=lambda x: (x["order"], x["id"]))
    return {
        "ui": ui,
        "agents": items,
        "file": str(agents_path),
        "exists": agents_path.exists(),
        "total": len(items),
        "active": sum(1 for i in items if i["enabled"]),
        "hint": "改完在 DSH 里重载生效：让模型调用 agent_hub_reload，或重启 DSH",
    }


def toggle_agent(agent_id, enabled):
    """启用/禁用一个 agent，写回 agents.json。"""
    agents_path = AGENTS_DIR / "agents.json"
    cfg = _read_json_file(agents_path, {"version": 1, "agents": []})
    agents = cfg.get("agents", []) if isinstance(cfg, dict) else []
    hit = None
    for a in agents:
        if isinstance(a, dict) and a.get("id") == agent_id:
            a["enabled"] = bool(enabled)
            hit = a
            break
    if hit is None:
        return {"ok": False, "error": "没有这个 agent：%s" % agent_id}
    _write_json_file(agents_path, {"version": 1, "agents": agents})
    return {"ok": True, "id": agent_id, "enabled": bool(enabled), "needs_reload": True,
            "hint": "已保存；在 DSH 里调用 agent_hub_reload 或重启 DSH 生效"}


def set_agent_ui(selector_visible):
    """输入栏 agent 选择器的开关。"""
    ui_path = AGENTS_DIR / "ui.json"
    ui = {"selectorVisible": True, **_read_json_file(ui_path, {})}
    ui["selectorVisible"] = bool(selector_visible)
    _write_json_file(ui_path, ui)
    return {"ok": True, **ui}


# ── GitHub 新增仓库统计（工作台唯一联网面板）──────────────────────
# 开关
#   默认关闭。关闭时 scan_github 直接返回，不读缓存、不入队、不启动线程、不发请求；
#   前端也不轮询。开启状态持久化在 config.json 的 "github_enabled"。
# 口径
#   · 新增仓库数 = Search API 的 total_count（只统计 public 仓库；私有/闭源 API 查不到，不做）
#   · 上传者数   = 抽样 300 条仓库按 owner 去重，按去重率外推（估算值，不是精确值）
# 数据源
#   本机直连 api.github.com 会被 TCP 重置（2026-11-07 实测 0.02s 000），
#   默认经 gh-proxy.com 转发；可在 config.json 里用 "github_proxy" 换成自己的代理。
# 节流
#   Search API 30 次/分钟，队列 2.4 秒一条；历史窗口只抓一次（结果不会变），
#   当前小时 / 今日窗口每 60 秒重抓，上传者抽样 30 分钟一次。
# 说明
#   这是工作台唯一会联网的面板，只在打开它时才抓；页面关掉不产生任何请求。

_GH_PROXIES = [p.strip() for p in (_CONFIG.get("github_proxies") or []) if p and str(p).strip()]
if not _GH_PROXIES:
    _GH_PROXIES = [str(_CONFIG.get("github_proxy") or "https://gh-proxy.com/").rstrip("/") + "/"]
GH_PROXY = _GH_PROXIES[0]
_GH_PROXY_IDX = [0]
GH_CACHE_FILE = HERE / "_github_cache.json"
GH_REFRESH = max(30, int(_CONFIG.get("github_refresh_secs") or 60))
GH_SAMPLE_N = int(_CONFIG.get("github_sample_n") or 300)
GH_ALERT_HOUR = int(_CONFIG.get("github_alert_hour") or 0)   # 本小时破这个数就提醒，0=关

_GH_LOCK = threading.RLock()   # RLock：scan_github 持锁时会再进 _gh_ensure_worker
_GH_TASKS: deque = deque()
_GH_QUEUED: set = set()
_GH_BUSY = 0          # 正在跑的抓取线程数（最多 2）
_GH_RATE_LOCK = threading.Lock()
_GH_LAST_REQ = 0.0
_GH_STATS = {"req": 0, "ok": 0, "err": 0, "last_ok": 0, "last_err": ""}
_GH_RATE = {"search_left": None, "search_reset": 0, "core_left": None}


def _gh_enabled() -> bool:
    """默认关闭：只有用户开了开关才会去抓。"""
    return bool(_CONFIG.get("github_enabled", False))


def _gh_set_enabled(v: bool) -> dict:
    """开/关统计，写回 config.json（保留其它键），立即生效。"""
    _CONFIG["github_enabled"] = bool(v)
    if not v:
        with _GH_LOCK:
            _GH_TASKS.clear()
            _GH_QUEUED.clear()
    try:
        (HERE / "config.json").write_text(
            json.dumps(_CONFIG, ensure_ascii=False, indent=2), "utf-8")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "enabled": bool(v), "error": str(e)[:120]}
    return {"ok": True, "enabled": bool(v)}


def _gh_load() -> dict:
    try:
        d = json.loads(GH_CACHE_FILE.read_text("utf-8"))
        if isinstance(d, dict) and isinstance(d.get("w"), dict):
            return d
    except Exception:
        pass
    return {"v": 1, "w": {}, "latest": {}, "sample": {}, "stats": {}}


_GH_CACHE = _gh_load()


def _gh_save():
    try:
        tmp = GH_CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_GH_CACHE, ensure_ascii=False), "utf-8")
        tmp.replace(GH_CACHE_FILE)
    except Exception:
        pass


def _gh_prune(keep_days: int = 45, keep_hours: int = 72):
    """窗口 key 会随时间不断新增（每小时 1 个 h:、每天 1 个 d:），旧的不再查询，
    这里按保留期剪掉，避免缓存无限长。历史上限之后每个 key 都不再进读取范围。"""
    now = _dt.datetime.now().astimezone()
    cut_d = (now - _dt.timedelta(days=keep_days)).strftime("%Y-%m-%d")
    cut_h = (now - _dt.timedelta(hours=keep_hours)).strftime("%Y-%m-%dT%H")
    with _GH_LOCK:
        w = _GH_CACHE.get("w") or {}
        dead = [k for k in w
                if (k.startswith("d:") and k[2:] < cut_d) or (k.startswith("h:") and k[2:] < cut_h)]
        for k in dead:
            w.pop(k, None)


def _gh_iso(d: _dt.datetime) -> str:
    return d.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh_headers():
    return {"User-Agent": "dsh-workbench/1.1", "Accept": "application/vnd.github+json"}


def _gh_get(target_url: str, timeout: int = 30):
    """经代理请求 GitHub API，返回 (json, headers)。
    配了多个代理时轮流试：当前代理失败自动切下一个，全部失败才抛错。"""
    last = None
    n = len(_GH_PROXIES)
    for i in range(n):
        idx = (_GH_PROXY_IDX[0] + i) % n
        try:
            req = urllib.request.Request(_GH_PROXIES[idx] + target_url, headers=_gh_headers())
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
                _GH_PROXY_IDX[0] = idx
                return data, dict(r.headers)
        except Exception as e:  # noqa: BLE001 —— 换下一个代理
            last = e
            continue
    raise last if last else RuntimeError("no proxy configured")


def _gh_gap():
    """Search API 30 次/分钟，全局匀速 2.4 秒一条（两个线程共享这个节流）。"""
    global _GH_LAST_REQ
    with _GH_RATE_LOCK:
        wait = 2.4 - (time.time() - _GH_LAST_REQ)
        if wait > 0:
            time.sleep(wait)
        _GH_LAST_REQ = time.time()


def _gh_api(path: str, params: dict):
    _gh_gap()
    url = "https://api.github.com" + path + "?" + urllib.parse.urlencode(params)
    data, headers = _gh_get(url)
    try:
        if "X-RateLimit-Remaining" in headers:
            _GH_RATE["search_left"] = int(headers["X-RateLimit-Remaining"])
            _GH_RATE["search_reset"] = int(headers.get("X-RateLimit-Reset") or 0)
    except Exception:
        pass
    if isinstance(data, dict) and data.get("message") and "total_count" not in data:
        raise RuntimeError(str(data["message"])[:120])
    return data


def _gh_fetch_count(s: _dt.datetime, e: _dt.datetime) -> dict:
    q = "created:%s..%s" % (_gh_iso(s), _gh_iso(e))
    d = _gh_api("/search/repositories", {"q": q, "per_page": 1})
    return {"c": int(d.get("total_count") or 0), "t": time.time(),
            "s": int(s.timestamp()), "e": int(e.timestamp())}


def _gh_fetch_latest() -> dict:
    """最近 30 分钟抓 100 条，按 created_at 自己排序——GitHub search 不支持 sort=created。"""
    now = _dt.datetime.now().astimezone()
    q = "created:>=%s" % _gh_iso(now - _dt.timedelta(minutes=30))
    d = _gh_api("/search/repositories", {"q": q, "per_page": 100})
    rows = []
    for x in (d.get("items") or []):
        rows.append({
            "name": str(x.get("full_name") or "")[:60],
            "owner": str((x.get("owner") or {}).get("login") or ""),
            "lang": x.get("language") or "",
            "stars": int(x.get("stargazers_count") or 0),
            "created": x.get("created_at") or "",
        })
    rows.sort(key=lambda r: r["created"], reverse=True)
    return {"at": time.time(), "items": rows[:24]}


def _gh_fetch_sample() -> dict:
    """近 24h 抽 N 条：按 owner 去重估上传者数，顺带统计语言分布（零额外请求）。"""
    now = _dt.datetime.now().astimezone()
    q = "created:>=%s" % _gh_iso(now - _dt.timedelta(hours=24))
    seen, n = set(), 0
    langs: dict = {}
    stars_sum = 0
    pages = max(1, (GH_SAMPLE_N + 99) // 100)
    for page in range(1, pages + 1):
        d = _gh_api("/search/repositories", {"q": q, "per_page": 100, "page": page})
        items = d.get("items") or []
        if not items:
            break
        for x in items:
            n += 1
            login = (x.get("owner") or {}).get("login") or ""
            if login:
                seen.add(login)
            lg = x.get("language") or "未标注"
            langs[lg] = langs.get(lg, 0) + 1
            stars_sum += int(x.get("stargazers_count") or 0)
        if len(items) < 100:
            break
    top_langs = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:10]
    return {"at": time.time(), "n": n, "uniq": len(seen),
            "langs": [[k, v] for k, v in top_langs],
            "avg_stars": round(stars_sum / n, 1) if n else 0}


def _gh_fetch_hot() -> dict:
    """今天创建、star 最多的仓库（sort=stars 在 created 窗口内有效）。"""
    now = _dt.datetime.now().astimezone()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    q = "created:>=%s" % _gh_iso(day0)
    d = _gh_api("/search/repositories", {"q": q, "sort": "stars", "order": "desc", "per_page": 10})
    rows = []
    for x in (d.get("items") or [])[:10]:
        rows.append({
            "name": str(x.get("full_name") or "")[:60],
            "owner": str((x.get("owner") or {}).get("login") or ""),
            "lang": x.get("language") or "",
            "stars": int(x.get("stargazers_count") or 0),
            "created": x.get("created_at") or "",
        })
    return {"at": time.time(), "items": rows}


def _gh_query_range(s: _dt.datetime, e: _dt.datetime, timeout: int = 40) -> dict:
    """自定义区间的精确总数（同步查，1 次请求）。"""
    if e <= s:
        return {"ok": False, "error": "结束时间要晚于开始时间"}
    if (e - s).days > 366:
        return {"ok": False, "error": "区间最多 1 年"}
    q = "created:%s..%s" % (_gh_iso(s), _gh_iso(e))
    _gh_gap()
    data, _h = _gh_get("https://api.github.com/search/repositories?" +
                       urllib.parse.urlencode({"q": q, "per_page": 1}), timeout=timeout)
    return {"ok": True, "count": int(data.get("total_count") or 0),
            "from": s.strftime("%Y-%m-%d %H:%M"), "to": e.strftime("%Y-%m-%d %H:%M")}


def _gh_notify(title: str, body: str):
    """Windows 右下角通知；失败静默（不影响面板）。"""
    try:
        import subprocess
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
            "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            "$n = $t.GetElementsByTagName('text');"
            "$n.Item(0).AppendChild($t.CreateTextNode('%s')) | Out-Null;"
            "$n.Item(1).AppendChild($t.CreateTextNode('%s')) | Out-Null;"
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($t);"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('DSH 工作台').Show($toast);"
        ) % (title.replace("'", "''"), body.replace("'", "''"))
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=8)
    except Exception:
        pass


def _gh_worker():
    global _GH_BUSY, _GH_STATS
    while True:
        with _GH_LOCK:
            if not _gh_enabled():
                _GH_TASKS.clear()
                _GH_QUEUED.clear()
                _GH_BUSY = max(0, _GH_BUSY - 1)
                return
            if not _GH_TASKS:
                _GH_BUSY = max(0, _GH_BUSY - 1)
                return
            task = _GH_TASKS.popleft()
            _GH_QUEUED.discard(task["key"])
        try:
            if task["kind"] == "count":
                item = _gh_fetch_count(task["s"], task["e"])
                with _GH_LOCK:
                    _GH_CACHE["w"][task["key"]] = item
            elif task["kind"] == "latest":
                item = _gh_fetch_latest()
                with _GH_LOCK:
                    _GH_CACHE["latest"] = item
            elif task["kind"] == "sample":
                item = _gh_fetch_sample()
                with _GH_LOCK:
                    _GH_CACHE["sample"] = item
            elif task["kind"] == "hot":
                item = _gh_fetch_hot()
                with _GH_LOCK:
                    _GH_CACHE["hot"] = item
            with _GH_LOCK:
                _GH_STATS["req"] += 1
                _GH_STATS["ok"] += 1
                _GH_STATS["last_ok"] = time.time()
                _GH_STATS["last_err"] = ""
            _gh_save()
        except Exception as e:  # noqa: BLE001 —— 网络抖动/代理挂了都走这里
            task["try"] = int(task.get("try") or 0) + 1
            with _GH_LOCK:
                _GH_STATS["req"] += 1
                _GH_STATS["err"] += 1
                _GH_STATS["last_err"] = "%s: %s" % (type(e).__name__, str(e)[:120])
                if task["try"] <= 3:
                    _GH_TASKS.append(task)      # 放回队尾重试
                    _GH_QUEUED.add(task["key"])
            time.sleep(4 + task["try"] * 2)


def _gh_ensure_worker():
    global _GH_BUSY
    with _GH_LOCK:
        if _GH_BUSY >= 2:
            return
        _GH_BUSY += 1
        n = _GH_BUSY
    threading.Thread(target=_gh_worker, daemon=True, name="gh-fetch-%d" % n).start()


def _gh_plan_windows():
    """返回 [(key, start, end, ttl, partial)]：最近 30 个本地日 + 最近 24 个本地小时。"""
    loc = _dt.datetime.now().astimezone()
    now = loc
    cur = loc.replace(minute=0, second=0, microsecond=0)
    plan = []
    for i in range(29, -1, -1):
        d0 = (loc - _dt.timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        d1 = (d0 + _dt.timedelta(days=1)) if i else now
        plan.append(("d:" + d0.strftime("%Y-%m-%d"), d0, d1,
                     GH_REFRESH if i == 0 else 10 ** 9, i == 0))
    for i in range(23, -1, -1):
        h0 = cur - _dt.timedelta(hours=i)
        h1 = now if i == 0 else h0 + _dt.timedelta(hours=1)
        plan.append(("h:" + h0.strftime("%Y-%m-%dT%H"), h0, h1,
                     GH_REFRESH if i == 0 else 10 ** 9, i == 0))
    return plan


def _gh_valid(it: dict, end: _dt.datetime, ttl: float, partial: bool) -> bool:
    if not it or not isinstance(it.get("c"), int):
        return False
    if time.time() - float(it.get("t") or 0) >= ttl:
        return False
    if not partial and it.get("e") != int(end.timestamp()):
        return False
    return True


def scan_github(from_s: str = "", to_s: str = "") -> dict:
    loc = _dt.datetime.now().astimezone()
    if not _gh_enabled():
        # 关闭：不读缓存、不入队、不起线程、不发请求
        return {"ok": True, "enabled": False,
                "generated_at": loc.strftime("%Y-%m-%d %H:%M:%S"),
                "hint": "统计已关闭"}
    if from_s and to_s:
        # 自定义区间：同步查一次，不改主面板
        try:
            s = _dt.datetime.fromisoformat(from_s).astimezone()
            e = _dt.datetime.fromisoformat(to_s).astimezone()
        except Exception:
            return {"ok": False, "enabled": True, "error": "时间格式不对，要 2026-11-01T00:00"}
        r = _gh_query_range(s, e)
        r["enabled"] = True
        return r
    plan = _gh_plan_windows()
    _gh_prune()

    need = []
    with _GH_LOCK:
        for k, s, e, ttl, partial in plan:
            if not _gh_valid(_GH_CACHE["w"].get(k), e, ttl, partial):
                need.append((k, s, e))
        # 先保证 KPI 能用：今日 / 当前小时 / 最新入库 / 抽样，历史窗口排后面
        today_key = plan[29][0]                       # plan 前 30 条是日窗口，第 30 条是今天
        cur_key = plan[-1][0]                         # 最后一条是当前小时
        need.sort(key=lambda t: 0 if t[0] == today_key else (1 if t[0] == cur_key else (2 if t[0].startswith("h:") else 3)))
        for k, s, e in need:
            if k not in _GH_QUEUED:
                _GH_TASKS.append({"kind": "count", "key": k, "s": s, "e": e})
                _GH_QUEUED.add(k)
        # 最新入库 + 上传者抽样（插到队首，紧跟 KPI 窗口）
        lt = _GH_CACHE.get("latest") or {}
        if time.time() - float(lt.get("at") or 0) >= GH_REFRESH:
            if "latest" not in _GH_QUEUED:
                _GH_TASKS.appendleft({"kind": "latest", "key": "latest"})
                _GH_QUEUED.add("latest")
        smp = _GH_CACHE.get("sample") or {}
        if ("langs" not in smp) or time.time() - float(smp.get("at") or 0) >= 1800:
            if "sample" not in _GH_QUEUED:
                _GH_TASKS.insert(1, {"kind": "sample", "key": "sample"})
                _GH_QUEUED.add("sample")
        hot = _GH_CACHE.get("hot") or {}
        if time.time() - float(hot.get("at") or 0) >= 600:
            if "hot" not in _GH_QUEUED:
                _GH_TASKS.insert(2, {"kind": "hot", "key": "hot"})
                _GH_QUEUED.add("hot")
        if need or _GH_TASKS:
            _gh_ensure_worker()
        cached = _GH_CACHE["w"]
        done_ok = sum(1 for k, _s, _e, _ttl, _p in plan if isinstance((cached.get(k) or {}).get("c"), int))
        progress = {
            "done": done_ok,
            "total": len(plan),
            "queued": len(_GH_QUEUED),
            "busy": _GH_BUSY > 0,
        }
        latest = _GH_CACHE.get("latest") or {}
        sample = _GH_CACHE.get("sample") or {}
        hot = _GH_CACHE.get("hot") or {}
        stats = dict(_GH_STATS)
        rate = dict(_GH_RATE)

    def val(key):
        it = cached.get(key)
        return it.get("c") if it else None

    days = [(k, s, e) for k, s, e, ttl, partial in plan if k.startswith("d:")]
    hours = [(k, s, e) for k, s, e, ttl, partial in plan if k.startswith("h:")]

    today_n = val(days[-1][0])
    hour_n = val(hours[-1][0])
    h24_vals = [val(k) for k, _s, _e in hours]
    h24 = sum(h24_vals) if all(v is not None for v in h24_vals) else None

    uploaders = None
    if sample.get("n") and h24:
        ratio = sample.get("uniq", 0) / max(1, sample["n"])
        uploaders = {"n": int(round(h24 * ratio)), "ratio": round(ratio, 3),
                     "sample": sample["n"], "at": sample.get("at")}

    hourly = []
    for i, (k, s, _e) in enumerate(hours):
        hourly.append({"t": s.strftime("%H:%M"), "c": val(k), "cur": i == len(hours) - 1,
                       "ts": int(s.timestamp())})
    daily = []
    for k, s, _e in days:
        daily.append({"d": s.strftime("%m-%d"), "c": val(k),
                      "ts": int(s.timestamp()), "today": k == days[-1][0]})

    return {
        "ok": True,
        "enabled": True,
        "generated_at": loc.strftime("%Y-%m-%d %H:%M:%S"),
        "tz": loc.strftime("%z"),
        "source": "api.github.com/search/repositories",
        "proxy": GH_PROXY,
        "refresh_secs": GH_REFRESH,
        "progress": progress,
        "rate": rate,
        "stats": stats,
        "kpi": {
            "today": today_n,
            "today_label": loc.strftime("%Y-%m-%d"),
            "hour": hour_n,
            "hour_label": hours[-1][1].strftime("%H:%M") + " 止（本小时进行中）",
            "h24": h24,
            "uploaders": uploaders,
        },
        "hourly": hourly,
        "daily": daily,
        "latest": {"at": latest.get("at"), "items": latest.get("items") or []},
        "hot": {"at": hot.get("at"), "items": hot.get("items") or []},
        "langs": sample.get("langs") or [],
        "avg_stars": sample.get("avg_stars") or 0,
        "week": _gh_week_cmp(daily),
        "alert": _gh_alert(hour_n),
    }


def _gh_week_cmp(daily) -> dict | None:
    """最近 7 天 vs 前 7 天（用已有日数据，零额外请求）。"""
    ds = [d for d in daily if isinstance(d.get("c"), int)]
    if len(ds) < 14:
        return None
    prev = ds[-14:-7]
    cur = ds[-7:]
    p = sum(x["c"] for x in prev)
    c = sum(x["c"] for x in cur)
    return {"cur": c, "prev": p, "delta": c - p,
            "pct": round((c - p) / p * 100, 1) if p else None,
            "prev_range": "%s–%s" % (prev[0]["d"], prev[-1]["d"]),
            "cur_range": "%s–%s" % (cur[0]["d"], cur[-1]["d"])}


def _gh_alert(hour_n) -> dict | None:
    """本小时破阈值就弹 Windows 通知；同一阈值 30 分钟内只弹一次。"""
    if GH_ALERT_HOUR <= 0 or not hour_n or hour_n < GH_ALERT_HOUR:
        return None
    now_ts = time.time()
    if now_ts - float(_GH_CACHE.get("alert_at") or 0) > 1800:
        _GH_CACHE["alert_at"] = now_ts
        threading.Thread(target=_gh_notify, daemon=True, args=(
            "GitHub 新增爆发",
            "本小时已 %s 个新仓库，超过阈值 %s" % (format(hour_n, ","), format(GH_ALERT_HOUR, ",")),
        )).start()
    return {"threshold": GH_ALERT_HOUR, "value": hour_n}


# ── 云服务器比价（数据层在同目录 cloud_price.py）──────────────────
try:
    from cloud_price import scan_cloudprice  # noqa: E402
except Exception as _cp_err:  # noqa: BLE001
    def scan_cloudprice():
        return {"ok": False, "error": "cloud_price.py 加载失败：%s" % _cp_err}


# ── 本机配置（WMI / 性能计数器，只读、不联网）─────────────────────
# 结构分两层，方便扩展：
#   static —— 硬件信息，缓存 5 分钟（WMI 查询慢）
#   live   —— 实时占用，每次请求现取
# 以后加温度/风扇/电池：在 _SYS_LIVE_PS 里多取一个字段 + 前端多一个卡片即可。

_SYS_STATIC = {"at": 0.0, "data": {}}
_SYS_LIVE_AT = [0.0]
_SYS_LIVE = [{}]


def _ps_run(script: str, timeout: int = 15) -> str:
    import subprocess
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " + script],
            capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


_SYS_STATIC_PS = r"""
$ErrorActionPreference='SilentlyContinue'
$cs=Get-CimInstance Win32_ComputerSystem
$bb=Get-CimInstance Win32_BaseBoard
$os=Get-CimInstance Win32_OperatingSystem
$cpu=Get-CimInstance Win32_Processor|Select-Object -First 1
$mem=@(Get-CimInstance Win32_PhysicalMemory|ForEach-Object{@{size=[math]::Round($_.Capacity/1GB);speed=$_.Speed;vendor=$_.Manufacturer}})
$gpus=@(Get-CimInstance Win32_VideoController|ForEach-Object{@{name=$_.Name;vramWmi=[math]::Round($_.AdapterRAM/1MB)}})
$disks=@(Get-CimInstance Win32_DiskDrive|ForEach-Object{@{model=$_.Model;size=[math]::Round($_.Size/1GB)}})
$nics=@(Get-CimInstance Win32_NetworkAdapter|Where-Object{$_.PhysicalAdapter -and $_.Name -notmatch 'VMware|Virtual|虚拟|TAP|Loopback'}|ForEach-Object{$_.Name})
$vram=@(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*' -Name 'HardwareInformation.qwMemorySize'|ForEach-Object{[math]::Round($_.'HardwareInformation.qwMemorySize'/1GB,1)})
@{model=($cs.Manufacturer+' '+$cs.Model).Trim();board=$bb.Product;os=$os.Caption;osv=$os.Version;cpu=@{name=$cpu.Name;cores=$cpu.NumberOfCores;threads=$cpu.NumberOfLogicalProcessors;mhz=$cpu.MaxClockSpeed};mem=$mem;gpus=$gpus;vram=$vram;disks=$disks;nics=$nics}|ConvertTo-Json -Depth 4
"""

_SYS_LIVE_PS = r"""
$ErrorActionPreference='SilentlyContinue'
$cpu=(Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor|Where-Object{$_.Name -eq '_Total'}).PercentProcessorTime
$os=Get-CimInstance Win32_OperatingSystem
$g=(Get-Counter '\GPU Engine(*)\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples|Measure-Object -Property CookedValue -Sum
@{cpu=[int]$cpu;memUsed=[math]::Round(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/1MB,1);memTotal=[math]::Round($os.TotalVisibleMemorySize/1MB,1);gpu=[math]::Round($g.Sum,1)}|ConvertTo-Json
"""


def scan_sysinfo() -> dict:
    now = time.time()
    # 静态配置：缓存 5 分钟
    if (not _SYS_STATIC["data"]) or now - _SYS_STATIC["at"] > 300:
        raw = _ps_run(_SYS_STATIC_PS)
        try:
            _SYS_STATIC["data"] = json.loads(raw)
            _SYS_STATIC["at"] = now
        except Exception:
            pass
    # 实时：1 秒内复用，避免前端刷新时重复跑 PowerShell
    if now - _SYS_LIVE_AT[0] > 1.0 or not _SYS_LIVE[0]:
        raw = _ps_run(_SYS_LIVE_PS, timeout=10)
        try:
            _SYS_LIVE[0] = json.loads(raw)
            _SYS_LIVE_AT[0] = now
        except Exception:
            pass
    return {
        "ok": True,
        "static": _SYS_STATIC["data"] or {},
        "live": _SYS_LIVE[0] or {},
        "cached_at": _SYS_STATIC["at"],
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# 面板注册表：加一行就多一个面板（key 对应 /api/<key>）
PANELS = [
    ("overview", "概览", scan_overview),
    ("plugins", "插件", scan_plugins),
    ("skills", "技能", scan_skills),
    ("agents", "Agent", scan_agents),
    ("memory", "记忆", scan_memory),
    ("cost", "成本", scan_cost),
    ("artcraft", "ArtCraft", scan_artcraft),
    ("tools", "工具开销", scan_tools),
    ("github", "GitHub 新增", scan_github),
    ("cloudprice", "云服务器比价", scan_cloudprice),
    ("sysinfo", "本机配置", scan_sysinfo),
]

# 核心插件不允许从面板里关掉，否则 DSH 起不来
PROTECTED_BUNDLES = {"@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"}

# 常见字段名的中文标签（自动推断时用）
KEY_LABELS = {
    "scale": "缩放", "size": "大小", "width": "宽度", "height": "高度",
    "sound": "音效", "vol": "音量", "volume": "音量", "mute": "静音",
    "enabled": "启用", "enable": "启用", "on": "开启", "off": "关闭",
    "theme": "主题", "lang": "语言", "language": "语言", "model": "模型",
    "port": "端口", "host": "主机", "path": "路径", "dir": "目录",
    "opacity": "透明度", "speed": "速度", "duration": "时长",
    "timeout": "超时(ms)", "interval": "间隔(ms)", "delay": "延迟(ms)",
    "bubble": "气泡", "pos": "位置", "position": "位置", "offset": "偏移",
    "color": "颜色", "font": "字体", "size": "字号", "margin": "边距",
    "padding": "内边距", "radius": "圆角", "shadow": "阴影",
    "proxy": "代理", "url": "地址", "key": "密钥", "token": "令牌",
    "debug": "调试", "log": "日志", "verbose": "详细输出",
    "auto": "自动", "autoStart": "自动启动", "autoSave": "自动保存",
    "intervalMs": "间隔(ms)", "retry": "重试", "maxRetry": "最大重试",
    "cache": "缓存", "proxyOn": "代理开关", "themeName": "主题名",
}

# 插件 → 可视化字段定义（有这张表就渲染成滑块/开关，没有就退回 JSON 编辑器）
PLUGIN_FIELDS = {
    "dsh-whale-widget": [
        {"key": "scale", "label": "挂件大小", "type": "range", "min": 0.6, "max": 2.5, "step": 0.1,
         "hint": "默认 1.5；范围 0.6–2.5"},
        {"key": "sound", "label": "音效", "type": "bool"},
        {"key": "vol", "label": "音量", "type": "range", "min": 0, "max": 1, "step": 0.05},
        {"key": "soundSet", "label": "音效组", "type": "text", "hint": "如 duck"},
        {"key": "bubbleOn", "label": "显示余额气泡", "type": "bool"},
        {"key": "pressOn", "label": "按压反馈", "type": "bool"},
        {"key": "turnCostOn", "label": "每轮消耗提示", "type": "bool"},
        {"key": "turnCostCloseMs", "label": "提示停留（毫秒）", "type": "range",
         "min": 1000, "max": 20000, "step": 500},
        {"key": "scrollGapOn", "label": "滚动留白", "type": "bool"},
        {"key": "scrollGapPx", "label": "留白像素", "type": "range", "min": 0, "max": 200, "step": 1},
        {"key": "menuBtnHide", "label": "隐藏菜单按钮", "type": "bool"},
        {"key": "codexStatsOn", "label": "子智能体统计", "type": "bool"},
        {"key": "usageMode", "label": "用量模式", "type": "text", "hint": "如 ledger"},
        {"key": "peakMode", "label": "峰谷模式", "type": "text", "hint": "如 default"},
    ],
}

# 插件 → 可编辑的配置文件（工作台里的「参数」入口）
PLUGIN_CONFIGS = {
    "dsh-whale-widget": ("小鲸鱼挂件", DSH_HOME / ".dshw-size.json"),
    "@ninkch/dsh-artcraft": ("ArtCraft 桥接", ART_CONFIG),
}


def remove_plugin(name: str) -> dict:
    """从 profile 卸载插件：移出 bundle 列表 + 移除 dependency。

    保守做法：只改 profile/package.json，不动 node_modules 里的文件
    （那些文件不影响加载，重装时还能复用缓存）。重启 DSH 后生效。
    """
    if not name:
        return {"ok": False, "error": "缺少插件名"}
    if name in PROTECTED_BUNDLES:
        return {"ok": False, "error": "DSH 核心插件不能卸载"}
    pkg = PROFILE / "package.json"
    if not pkg.exists():
        return {"ok": False, "error": "找不到 profile package.json"}
    data = load_json(pkg, {})
    prof = data.setdefault("dsh", {}).setdefault("profile", {})
    bundles = prof.setdefault("bundles", [])
    deps = data.setdefault("dependencies", {})
    had_bundle = name in bundles
    had_dep = name in deps
    if not had_bundle and not had_dep:
        return {"ok": False, "error": "这个插件不在当前 profile 里"}
    bak = PROFILE / ("package.json.bak-remove-" + time.strftime("%Y%m%d-%H%M%S"))
    try:
        import shutil as _sh
        _sh.copy2(pkg, bak)
    except Exception:
        bak = None
    if had_bundle:
        bundles.remove(name)
    if had_dep:
        deps.pop(name, None)
    pkg.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _SIZE_CACHE.clear()
    return {
        "ok": True,
        "msg": "已卸载 %s，重启 DSH 生效" % name,
        "backup": bak.name if bak else "",
        "removedBundle": had_bundle,
        "removedDependency": had_dep,
        "filesKept": True,
    }


def _short_name(pkg: str) -> str:
    n = pkg.split("/")[-1]
    return n[4:] if n.startswith("dsh-") else n


_CFG_FIND_CACHE: dict = {}


def find_plugin_config(pkg: str):
    """自动找插件的 JSON 配置文件。返回 Path 或 None。"""
    if pkg in _CFG_FIND_CACHE:
        return _CFG_FIND_CACHE[pkg]
    short = _short_name(pkg)
    cands = []
    # 插件目录内优先
    try:
        base = MODULES / pkg
        if base.is_dir():
            for pat in ("*.config.json", "config.json", "settings.json", ".config.json"):
                cands.extend(sorted(base.glob(pat)))
    except OSError:
        pass
    # 用户目录下的常见命名
    for name in (f"{short}.json", f"{short}.config.json", f".{short}.json",
                 f".{short}-config.json", f".{short}-size.json"):
        cands.append(DSH_HOME / name)
    found = None
    for c in cands:
        try:
            if c.is_file():
                found = c
                break
        except OSError:
            continue
    _CFG_FIND_CACHE[pkg] = found
    return found


SKIP_KEYS = {"updatedat", "createdat", "id", "uuid", "version", "timestamps"}


def infer_fields(obj: dict, prefix: str = "", depth: int = 0) -> list:
    """从 JSON 推断表单字段；嵌套对象展开成 a.b 形式（最多两层）。"""
    out = []
    if depth > 2:
        return out
    for k, v in obj.items():
        if k.startswith("_") or k.lower() in SKIP_KEYS:
            continue
        full = (prefix + "." + k) if prefix else k
        label = KEY_LABELS.get(k, k if depth == 0 else full)
        if isinstance(v, dict):
            out.extend(infer_fields(v, full, depth + 1))
        elif isinstance(v, bool):
            out.append({"key": full, "label": label, "type": "bool", "value": v})
        elif isinstance(v, (int, float)):
            if 0 <= v <= 1:
                lo, hi, st = 0, 1, 0.05
            elif v <= 10:
                lo, hi, st = 0, 20, 0.5
            elif v <= 100:
                lo, hi, st = 0, 200, 5
            elif v <= 10000:
                lo, hi, st = 0, 20000, 500
            else:
                lo, hi, st = 0, int(max(v * 2, 1000)), max(1, int(v / 20))
            out.append({"key": full, "label": label, "type": "range",
                        "min": lo, "max": hi, "step": st, "value": v})
        elif isinstance(v, str):
            out.append({"key": full, "label": label, "type": "text", "value": v})
    return out


def plugin_config(name: str) -> dict:
    """读插件配置：优先手工登记的表，其次自动发现 + 自动推断字段。"""
    item = PLUGIN_CONFIGS.get(name)
    if item:
        label, p = item
    else:
        found = find_plugin_config(name)
        if not found:
            return {"ok": False,
                    "error": "没找到这个插件的 JSON 配置（它可能用别的格式，或参数只能在其界面里调）"}
        label, p = name, found
    p = Path(p)
    content = ""
    if p.exists():
        try:
            content = p.read_text(encoding="utf-8")
        except Exception as e:
            return {"ok": False, "error": "读取失败: %s" % e}

    fields = []
    if content:
        try:
            cur = json.loads(content)
        except Exception:
            cur = {}
        if isinstance(cur, dict):
            if name in PLUGIN_FIELDS:
                # 手工表：字段顺序和标签都可控
                for f in PLUGIN_FIELDS[name]:
                    fd = dict(f)
                    fd["value"] = cur.get(f["key"])
                    fields.append(fd)
            else:
                # 自动推断：有 JSON 就出表单
                fields = infer_fields(cur)
    return {"ok": True, "label": label, "path": str(p), "exists": p.exists(),
            "content": content, "fields": fields,
            "visual": bool(fields), "auto": name not in PLUGIN_CONFIGS}


def save_plugin_config(name: str, content: str) -> dict:
    item = PLUGIN_CONFIGS.get(name)
    if not item:
        return {"ok": False, "error": "该插件没有可编辑的配置文件"}
    label, p = item
    p = Path(p)
    try:
        data = json.loads(content)
    except Exception as e:
        return {"ok": False, "error": "JSON 格式不对：%s" % e}
    try:
        if p.exists():
            import shutil as _sh
            _sh.copy2(p, p.with_suffix(p.suffix + ".bak-" + time.strftime("%Y%m%d-%H%M%S")))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": "写入失败: %s" % e}
    return {"ok": True, "label": label, "path": str(p), "msg": "已保存（部分插件需刷新页面生效）"}


def toggle_artcraft(app: str, enabled: bool) -> dict:
    """开关 ArtCraft 应用：只改 artcraft.config.json 的 bins，不删文件。"""
    if not app:
        return {"ok": False, "error": "缺少应用名"}
    cfg = load_json(ART_CONFIG, {})
    bins = cfg.setdefault("bins", {})
    if enabled:
        if app in bins:
            return {"ok": True, "changed": False, "msg": "本来就是启用状态"}
        # 在安装目录里找该应用的 *-cli.exe
        found = ""
        base = ART_DIR / app
        if base.exists():
            for f in base.rglob("*-cli.exe"):
                found = f.parent.as_posix()
                break
        if not found:
            return {"ok": False, "error": "本地没找到 %s 的可执行文件，需要先下载" % app}
        bins[app] = found
    else:
        if app not in bins:
            return {"ok": True, "changed": False, "msg": "本来就是关闭状态"}
        bins.pop(app, None)
    try:
        if ART_CONFIG.exists():
            import shutil as _sh
            _sh.copy2(ART_CONFIG, ART_CONFIG.with_suffix(".json.bak-" + time.strftime("%Y%m%d-%H%M%S")))
        ART_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": "写入配置失败: %s" % e}
    return {"ok": True, "changed": True, "msg": ("已启用 " + app) if enabled else ("已关闭 " + app)}


def toggle_plugin(name: str, enabled: bool) -> dict:
    """只改 profile 的 dsh.profile.bundles，不动 dependencies。

    关闭 = 从 bundles 数组里摘掉（依赖还在盘上，随时能加回来）；
    改动前自动备份 package.json，需要重启 DSH 才生效。
    """
    if not name:
        return {"ok": False, "error": "缺少插件名"}
    if name in PROTECTED_BUNDLES:
        return {"ok": False, "error": "DSH 核心插件不能关"}
    pkg = PROFILE / "package.json"
    if not pkg.exists():
        return {"ok": False, "error": "找不到 profile package.json"}
    data = load_json(pkg, {})
    prof = data.setdefault("dsh", {}).setdefault("profile", {})
    bundles = prof.setdefault("bundles", [])
    if enabled:
        if name in bundles:
            return {"ok": True, "changed": False, "msg": "本来就是启用状态"}
        bundles.append(name)
    else:
        if name not in bundles:
            return {"ok": True, "changed": False, "msg": "本来就是关闭状态"}
        bundles.remove(name)
    bak = PROFILE / ("package.json.bak-%s" % time.strftime("%Y%m%d-%H%M%S"))
    try:
        import shutil as _sh
        _sh.copy2(pkg, bak)
    except Exception:
        bak = None
    pkg.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _SIZE_CACHE.clear()
    return {
        "ok": True,
        "changed": True,
        "bundles": len(bundles),
        "backup": bak.name if bak else "",
        "needRestart": True,
        "msg": ("已启用，重启 DSH 生效" if enabled else "已关闭，重启 DSH 生效"),
    }


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):  # 静默
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._send(200, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        try:
            if path in ("/", "/index.html"):
                html = (HERE / "index.html").read_bytes()
                self._send(200, html, "text/html; charset=utf-8")
                return
            # 静态资源：lib/*.js、galaxy.js（只允许 workbench 目录内的文件）
            if path.endswith(".js") or path.endswith(".css"):
                target = (HERE / path.lstrip("/")).resolve()
                try:
                    target.relative_to(HERE.resolve())
                except ValueError:
                    self._send(403, b"forbidden", "text/plain")
                    return
                if target.is_file():
                    ctype = "text/javascript; charset=utf-8" if target.suffix == ".js" else "text/css; charset=utf-8"
                    self._send(200, target.read_bytes(), ctype)
                    return
                self._send(404, b"not found", "text/plain")
                return
            if path == "/api/panels":
                self._json([{"key": k, "label": lab} for k, lab, _ in PANELS])
                return
            if path == "/api/docstats":
                self._json(scan_docstats())
                return
            if path == "/api/attention":
                self._json(scan_attention())
                return
            if path.startswith("/api/"):
                key = path[5:]
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                if key == "github":
                    # 支持 ?from=2026-11-01T00:00&to=2026-11-07T21:00 查自定义区间
                    self._json(scan_github((qs.get("from") or [""])[0], (qs.get("to") or [""])[0]))
                    return
                for k, _lab, fn in PANELS:
                    if k == key:
                        self._json(fn())
                        return
                self._json({"error": "unknown panel: %s" % key})
                return
            self._send(404, b"not found", "text/plain")
        except Exception as e:  # noqa: BLE001
            self._json({"error": "%s: %s" % (type(e).__name__, e)})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            body = {}
        try:
            if path == "/api/plugins/toggle":
                self._json(toggle_plugin(str(body.get("name") or ""), bool(body.get("enabled"))))
                return
            if path == "/api/github/toggle":
                self._json(_gh_set_enabled(bool(body.get("enabled"))))
                return
            if path == "/api/agents/toggle":
                self._json(toggle_agent(str(body.get("id") or ""), bool(body.get("enabled"))))
                return
            if path == "/api/agents/ui":
                self._json(set_agent_ui(bool(body.get("selectorVisible"))))
                return
            if path == "/api/plugin-config":
                if str(body.get("mode") or "") == "save":
                    self._json(save_plugin_config(str(body.get("name") or ""), str(body.get("content") or "")))
                else:
                    self._json(plugin_config(str(body.get("name") or "")))
                return
            if path == "/api/plugins/remove":
                self._json(remove_plugin(str(body.get("name") or "")))
                return
            if path == "/api/artcraft/toggle":
                self._json(toggle_artcraft(str(body.get("app") or ""), bool(body.get("enabled"))))
                return
            self._json({"ok": False, "error": "unknown endpoint: %s" % path})
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    if not (HERE / "index.html").exists():
        print("缺少 index.html", file=sys.stderr)
        return 1
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("DSH 工作台已启动: http://%s:%d" % (args.host, args.port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
