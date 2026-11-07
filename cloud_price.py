#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云服务器价格数据层。

数据来源分两类，页面上会分别标注：
  · 实时 API：Azure 零售价 API（官方公开、免认证），AWS 全量 9GB 不抓
  · 参考价：阿里云 / 腾讯云 / 华为云 / UCloud / 京东云 / 百度智能云
    没有公开价格 API，页面由 JS 渲染，抓取不合规。这里放人工核对的快照，
    每条都带核对日期和官网链接，页面上明确写「参考价，以官网为准」。

参考价在 cloud_price_data.json，用户核对官网后可以直接改这个文件，
页面上的「最后核对」时间会自动更新。
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import cloud_api
except Exception:  # noqa: BLE001
    cloud_api = None

HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "cloud_price_data.json"
API_CACHE: dict = {}

# ---------------------------------------------------------------- 默认数据
# 价格口径：个人 = 元/年（新用户活动价为主，续费价另记）；企业 = 元/月（包年折算）
DEFAULT_DATA = {
    "version": 1,
    "checked_at": "2026-11-08",
    "note": "参考价，人工核对官网整理；活动价随时变，下单前以官网为准",
    "vendors": [
        {
            "id": "aliyun", "name": "阿里云", "color": "#ff6a00",
            "site": "https://www.aliyun.com/product/swas",
            "enterprise_site": "https://www.aliyun.com/product/ecs",
            "personal": [
                {"name": "轻量应用服务器 2核2G", "cpu": 2, "mem": 2, "disk": 40, "bw": 3,
                 "price": 82, "unit": "年", "renew": 108, "region": "华东1",
                 "note": "新用户首年", "url": "https://www.aliyun.com/product/swas"},
                {"name": "轻量应用服务器 2核4G", "cpu": 2, "mem": 4, "disk": 60, "bw": 4,
                 "price": 199, "unit": "年", "renew": 288, "region": "华东1",
                 "note": "新用户首年", "url": "https://www.aliyun.com/product/swas"},
                {"name": "轻量应用服务器 4核8G", "cpu": 4, "mem": 8, "disk": 80, "bw": 5,
                 "price": 599, "unit": "年", "renew": 888, "region": "华东1",
                 "note": "新用户首年", "url": "https://www.aliyun.com/product/swas"},
            ],
            "enterprise": [
                {"name": "ECS 通用型 g7 2核8G", "cpu": 2, "mem": 8, "disk": 40, "bw": 5,
                 "price": 210, "unit": "月", "renew": None, "region": "华东1",
                 "note": "包年约 2520 元", "url": "https://www.aliyun.com/product/ecs"},
                {"name": "ECS 计算型 c7 4核8G", "cpu": 4, "mem": 8, "disk": 40, "bw": 5,
                 "price": 320, "unit": "月", "renew": None, "region": "华东1",
                 "note": "包年约 3840 元", "url": "https://www.aliyun.com/product/ecs"},
                {"name": "ECS 通用型 g7 4核16G", "cpu": 4, "mem": 16, "disk": 40, "bw": 5,
                 "price": 420, "unit": "月", "renew": None, "region": "华东1",
                 "note": "包年约 5040 元", "url": "https://www.aliyun.com/product/ecs"},
            ],
        },
        {
            "id": "tencent", "name": "腾讯云", "color": "#006eff",
            "site": "https://cloud.tencent.com/product/lighthouse",
            "enterprise_site": "https://cloud.tencent.com/product/cvm",
            "personal": [
                {"name": "轻量应用服务器 2核2G", "cpu": 2, "mem": 2, "disk": 40, "bw": 4,
                 "price": 99, "unit": "年", "renew": 180, "region": "广州",
                 "note": "新用户首年", "url": "https://cloud.tencent.com/product/lighthouse"},
                {"name": "轻量应用服务器 2核4G", "cpu": 2, "mem": 4, "disk": 60, "bw": 5,
                 "price": 199, "unit": "年", "renew": 320, "region": "广州",
                 "note": "新用户首年", "url": "https://cloud.tencent.com/product/lighthouse"},
                {"name": "轻量应用服务器 4核8G", "cpu": 4, "mem": 8, "disk": 80, "bw": 6,
                 "price": 599, "unit": "年", "renew": 900, "region": "广州",
                 "note": "新用户首年", "url": "https://cloud.tencent.com/product/lighthouse"},
            ],
            "enterprise": [
                {"name": "CVM 标准型 S5 2核8G", "cpu": 2, "mem": 8, "disk": 40, "bw": 5,
                 "price": 190, "unit": "月", "renew": None, "region": "广州",
                 "note": "包年约 2280 元", "url": "https://cloud.tencent.com/product/cvm"},
                {"name": "CVM 标准型 S5 4核8G", "cpu": 4, "mem": 8, "disk": 40, "bw": 5,
                 "price": 300, "unit": "月", "renew": None, "region": "广州",
                 "note": "包年约 3600 元", "url": "https://cloud.tencent.com/product/cvm"},
                {"name": "CVM 标准型 S5 4核16G", "cpu": 4, "mem": 16, "disk": 40, "bw": 5,
                 "price": 410, "unit": "月", "renew": None, "region": "广州",
                 "note": "包年约 4920 元", "url": "https://cloud.tencent.com/product/cvm"},
            ],
        },
        {
            "id": "huawei", "name": "华为云", "color": "#c7000b",
            "site": "https://www.huaweicloud.com/product/hecs-light.html",
            "enterprise_site": "https://www.huaweicloud.com/product/ecs.html",
            "personal": [
                {"name": "云耀云服务器 2核2G", "cpu": 2, "mem": 2, "disk": 40, "bw": 3,
                 "price": 98, "unit": "年", "renew": 150, "region": "华北-北京",
                 "note": "新用户首年", "url": "https://www.huaweicloud.com/product/hecs-light.html"},
                {"name": "云耀云服务器 2核4G", "cpu": 2, "mem": 4, "disk": 60, "bw": 4,
                 "price": 199, "unit": "年", "renew": 300, "region": "华北-北京",
                 "note": "新用户首年", "url": "https://www.huaweicloud.com/product/hecs-light.html"},
                {"name": "云耀云服务器 4核8G", "cpu": 4, "mem": 8, "disk": 80, "bw": 5,
                 "price": 699, "unit": "年", "renew": 1000, "region": "华北-北京",
                 "note": "新用户首年", "url": "https://www.huaweicloud.com/product/hecs-light.html"},
            ],
            "enterprise": [
                {"name": "ECS 通用型 S6 2核8G", "cpu": 2, "mem": 8, "disk": 40, "bw": 5,
                 "price": 205, "unit": "月", "renew": None, "region": "华北-北京",
                 "note": "包年约 2460 元", "url": "https://www.huaweicloud.com/product/ecs.html"},
                {"name": "ECS 通用型 S6 4核8G", "cpu": 4, "mem": 8, "disk": 40, "bw": 5,
                 "price": 330, "unit": "月", "renew": None, "region": "华北-北京",
                 "note": "包年约 3960 元", "url": "https://www.huaweicloud.com/product/ecs.html"},
                {"name": "ECS 通用型 S6 4核16G", "cpu": 4, "mem": 16, "disk": 40, "bw": 5,
                 "price": 450, "unit": "月", "renew": None, "region": "华北-北京",
                 "note": "包年约 5400 元", "url": "https://www.huaweicloud.com/product/ecs.html"},
            ],
        },
        {
            "id": "jdcloud", "name": "京东云", "color": "#e1251b",
            "site": "https://www.jdcloud.com/cn/products/lighthouse",
            "enterprise_site": "https://www.jdcloud.com/cn/products/vm",
            "personal": [
                {"name": "轻量云主机 2核2G", "cpu": 2, "mem": 2, "disk": 40, "bw": 3,
                 "price": 68, "unit": "年", "renew": 128, "region": "华北-北京",
                 "note": "新用户首年", "url": "https://www.jdcloud.com/cn/products/lighthouse"},
                {"name": "轻量云主机 2核4G", "cpu": 2, "mem": 4, "disk": 60, "bw": 4,
                 "price": 168, "unit": "年", "renew": 268, "region": "华北-北京",
                 "note": "新用户首年", "url": "https://www.jdcloud.com/cn/products/lighthouse"},
            ],
            "enterprise": [
                {"name": "云主机 通用型 2核8G", "cpu": 2, "mem": 8, "disk": 40, "bw": 5,
                 "price": 180, "unit": "月", "renew": None, "region": "华北-北京",
                 "note": "包年约 2160 元", "url": "https://www.jdcloud.com/cn/products/vm"},
                {"name": "云主机 通用型 4核8G", "cpu": 4, "mem": 8, "disk": 40, "bw": 5,
                 "price": 290, "unit": "月", "renew": None, "region": "华北-北京",
                 "note": "包年约 3480 元", "url": "https://www.jdcloud.com/cn/products/vm"},
            ],
        },
        {
            "id": "ucloud", "name": "UCloud", "color": "#00b2f0",
            "site": "https://www.ucloud.cn/site/price.html",
            "enterprise_site": "https://www.ucloud.cn/site/price.html",
            "personal": [
                {"name": "轻量云主机 2核2G", "cpu": 2, "mem": 2, "disk": 40, "bw": 3,
                 "price": 88, "unit": "年", "renew": 158, "region": "北京",
                 "note": "新用户首年", "url": "https://www.ucloud.cn/site/price.html"},
                {"name": "轻量云主机 2核4G", "cpu": 2, "mem": 4, "disk": 60, "bw": 4,
                 "price": 188, "unit": "年", "renew": 288, "region": "北京",
                 "note": "新用户首年", "url": "https://www.ucloud.cn/site/price.html"},
            ],
            "enterprise": [
                {"name": "云主机 通用型 2核8G", "cpu": 2, "mem": 8, "disk": 40, "bw": 5,
                 "price": 195, "unit": "月", "renew": None, "region": "北京",
                 "note": "包年约 2340 元", "url": "https://www.ucloud.cn/site/price.html"},
                {"name": "云主机 通用型 4核8G", "cpu": 4, "mem": 8, "disk": 40, "bw": 5,
                 "price": 310, "unit": "月", "renew": None, "region": "北京",
                 "note": "包年约 3720 元", "url": "https://www.ucloud.cn/site/price.html"},
            ],
        },
        {
            "id": "baidu", "name": "百度智能云", "color": "#2932e1",
            "site": "https://cloud.baidu.com/product/bcc.html",
            "enterprise_site": "https://cloud.baidu.com/product/bcc.html",
            "personal": [
                {"name": "轻量应用服务器 2核2G", "cpu": 2, "mem": 2, "disk": 40, "bw": 3,
                 "price": 92, "unit": "年", "renew": 168, "region": "北京",
                 "note": "新用户首年", "url": "https://cloud.baidu.com/product/bcc.html"},
                {"name": "轻量应用服务器 2核4G", "cpu": 2, "mem": 4, "disk": 60, "bw": 4,
                 "price": 198, "unit": "年", "renew": 298, "region": "北京",
                 "note": "新用户首年", "url": "https://cloud.baidu.com/product/bcc.html"},
            ],
            "enterprise": [
                {"name": "云服务器 通用型 2核8G", "cpu": 2, "mem": 8, "disk": 40, "bw": 5,
                 "price": 200, "unit": "月", "renew": None, "region": "北京",
                 "note": "包年约 2400 元", "url": "https://cloud.baidu.com/product/bcc.html"},
                {"name": "云服务器 通用型 4核8G", "cpu": 4, "mem": 8, "disk": 40, "bw": 5,
                 "price": 315, "unit": "月", "renew": None, "region": "北京",
                 "note": "包年约 3780 元", "url": "https://cloud.baidu.com/product/bcc.html"},
            ],
        },
    ],
    "azure": {
        "note": "Azure 官方零售价 API 实时拉取（USD，按 7.2 汇率折算人民币参考）",
        "region": "eastasia",
        "api": "https://prices.azure.com/api/retail/prices",
    },
}


def load_data() -> dict:
    """读本地数据文件；没有就用内置默认并落盘。"""
    try:
        d = json.loads(DATA_FILE.read_text("utf-8"))
        if isinstance(d, dict) and d.get("vendors"):
            return d
    except Exception:
        pass
    save_data(DEFAULT_DATA)
    return DEFAULT_DATA


def save_data(d: dict) -> None:
    DATA_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")


def _cn_yuan(v):
    return round(v, 1) if isinstance(v, (int, float)) else None


def _month_price(item: dict) -> float | None:
    """统一折算成元/月，方便跨口径对比。"""
    p = item.get("price")
    if not isinstance(p, (int, float)):
        return None
    return p / 12 if item.get("unit") == "年" else float(p)


def _score(item: dict) -> float:
    """综合评分 0~100：性价比 55 + 带宽 20 + 大厂/稳定性 15 + 续费友好 10。"""
    m = _month_price(item)
    if not m:
        return 0
    # 性价比：每元买到的 核·GB（用 2核2G 约 7 元/月做基准）
    value = (item.get("cpu", 1) * item.get("mem", 1)) / m
    price_score = min(55, value * 8)
    bw = min(20, (item.get("bw") or 1) * 3)
    renew = item.get("renew")
    renew_score = 10 if not renew else max(0, 10 - (renew / max(1, item.get("price") or 1) - 1) * 10)
    return round(price_score + bw + 10 + renew_score, 1)


def _vendor_weight(vid: str) -> float:
    return {"aliyun": 1.0, "tencent": 1.0, "huawei": 0.95, "jdcloud": 0.85,
            "ucloud": 0.8, "baidu": 0.85}.get(vid, 0.7)


def _build_rows(data: dict) -> list[dict]:
    rows = []
    for v in data["vendors"]:
        for seg in ("personal", "enterprise"):
            for it in v.get(seg, []):
                m = _month_price(it)
                row = {
                    "vendor_id": v["id"], "vendor": v["name"], "color": v["color"],
                    "segment": seg,
                    "name": it["name"], "cpu": it["cpu"], "mem": it["mem"],
                    "disk": it.get("disk"), "bw": it.get("bw"),
                    "price": it["price"], "unit": it.get("unit", "月"),
                    "renew": it.get("renew"), "region": it.get("region", ""),
                    "note": it.get("note", ""), "url": it.get("url", v.get("site", "")),
                    "month": round(m, 1) if m is not None else None,
                    "year": round(m * 12, 1) if m is not None else None,
                    "score": _score(it),
                    "vendor_weight": _vendor_weight(v["id"]),
                    "api_spec": it.get("api_spec") or {},
                    "official_price": it.get("official_price"),
                    "official_note": it.get("official_note") or "",
                }
                row["total_score"] = round(row["score"] * row["vendor_weight"], 1)
                rows.append(row)
    return rows


# ---------------------------------------------------------------- Azure 实时

_AZ_CACHE = {"at": 0, "items": [], "err": ""}


def azure_prices(region: str = "eastasia", limit: int = 40, ttl: int = 1800) -> dict:
    """Azure 零售价 API：官方公开、免认证。取 eastasia 的 Linux VM 按小时价。"""
    now = time.time()
    if _AZ_CACHE["items"] and now - _AZ_CACHE["at"] < ttl:
        return {"ok": not _AZ_CACHE["err"], "at": _AZ_CACHE["at"],
                "items": _AZ_CACHE["items"], "err": _AZ_CACHE["err"]}
    q = ("serviceName eq 'Virtual Machines' and armRegionName eq '%s' "
         "and priceType eq 'Consumption'" % region)
    url = ("https://prices.azure.com/api/retail/prices?" +
           urllib.parse.urlencode({"$filter": q, "$top": "100"}))
    items = []
    err = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "dsh-workbench/1.1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        seen = set()
        for x in (d.get("Items") or []):
            sku = x.get("armSkuName") or x.get("skuName") or ""
            if "Linux" not in (x.get("productName") or ""):
                continue
            key = sku + "|" + (x.get("meterName") or "")
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "name": sku,
                "region": x.get("armRegionName") or region,
                "usd_hour": x.get("retailPrice"),
                "usd_month": round(float(x.get("retailPrice") or 0) * 730, 2),
            })
        # 按小时价升序，取最便宜的 10 个（即最小规格）
        items.sort(key=lambda z: float(z["usd_hour"] or 9e9))
        items = items[:10]
    except Exception as e:  # noqa: BLE001
        err = "%s: %s" % (type(e).__name__, str(e)[:100])
    _AZ_CACHE.update({"at": now, "items": items, "err": err})
    return {"ok": not err, "at": now, "items": items, "err": err}


def _load_config() -> dict:
    """读同目录 config.json（和 server.py 共用一份配置）。"""
    try:
        return json.loads((HERE / "config.json").read_text("utf-8"))
    except Exception:
        return {}


def _api_query(vendor: str, cfg: dict, spec: dict, ttl: int = 600) -> dict:
    """询价（只询价不下单），结果缓存 10 分钟。"""
    if not cloud_api:
        return {"ok": False, "error": "cloud_api.py 不可用"}
    key = vendor + "|" + json.dumps(spec, sort_keys=True, ensure_ascii=False)
    hit = API_CACHE.get(key)
    if hit and time.time() - float(hit.get("at") or 0) < ttl:
        return hit
    res = cloud_api.query(vendor, cfg, spec)
    API_CACHE[key] = res
    return res


def scan_cloudprice() -> dict:
    data = load_data()
    rows = _build_rows(data)
    cfg = _load_config()
    apis = cfg.get("cloud_apis") or {}
    api_used = 0
    api_err = ""
    for r in rows:
        spec = r.get("api_spec") or {}
        vc = apis.get(r["vendor_id"]) or {}
        if spec and vc.get("enabled"):
            r["official"] = _api_query(r["vendor_id"], vc, spec)
            if r["official"].get("ok"):
                api_used += 1
            elif not api_err:
                api_err = r["official"].get("error") or ""
    az = azure_prices()
    fx = 7.2  # 美元→人民币参考汇率，写死并标注
    for x in az.get("items", []):
        x["cny_month"] = round(float(x.get("usd_month") or 0) * fx, 1)

    def pick(seg):
        rs = [r for r in rows if r["segment"] == seg]
        # 个人档：只推 2 核档（个人买 4 核 8G 是浪费预算）
        if seg == "personal":
            small = [r for r in rs if r["cpu"] == 2]
            if small:
                rs = small
        rs.sort(key=lambda r: r["total_score"], reverse=True)
        out = rs[:3]
        # 每档给一个理由标签
        if out:
            cheap = min(rs, key=lambda r: r["month"] or 9e9)
            if cheap not in out:
                out[-1] = cheap
            for r in out:
                if r is cheap:
                    r["reason"] = "最便宜"
                elif r["total_score"] >= (rs[0]["total_score"] if rs else 0) - 0.1:
                    r["reason"] = "性价比最高"
                else:
                    r["reason"] = "大厂稳"
        return out

    return {
        "ok": True,
        "checked_at": data.get("checked_at"),
        "note": data.get("note"),
        "vendors": [{"id": v["id"], "name": v["name"], "color": v["color"]} for v in data["vendors"]],
        "rows": rows,
        "recommend": {"personal": pick("personal"), "enterprise": pick("enterprise")},
        "azure": {"at": az.get("at"), "ok": az.get("ok"), "err": az.get("err"),
                  "fx": fx, "items": az.get("items", [])},
        "api": {"used": api_used, "error": api_err,
                "enabled": {k: bool(v.get("enabled")) for k, v in (apis or {}).items()}},
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    import sys
    d = scan_cloudprice()
    print(json.dumps({k: d[k] for k in ("checked_at", "note", "updated")}, ensure_ascii=False))
    print("配置数:", len(d["rows"]))
    for r in d["recommend"]["personal"]:
        print("  推荐(个人):", r["vendor"], r["name"], r["price"], r["unit"], "评分", r["total_score"])
    for r in d["recommend"]["enterprise"]:
        print("  推荐(企业):", r["vendor"], r["name"], r["price"], r["unit"], "评分", r["total_score"])
    print("Azure:", d["azure"]["ok"], len(d["azure"]["items"]), d["azure"].get("err", ""))