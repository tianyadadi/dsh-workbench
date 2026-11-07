#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阿里云询价配置向导 —— 填好 AK 后跑一次，自动取镜像、逐条询价、回填配置。

用法
----
    1. 打开 config.json，把 cloud_apis.aliyun 填上：
         "access_key_id":     "LTAI..."
         "access_key_secret": "..."
       （阿里云控制台 → 右上角头像 → AccessKey 管理；或 RAM 子账号 + AliyunECSReadOnlyAccess）
    2. 运行：python cloud_aliyun_setup.py
    3. 回工作台刷新「云服务器比价」面板
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cloud_api  # noqa: E402

CFG_FILE = HERE / "config.json"
DATA_FILE = HERE / "cloud_price_data.json"

# 关键词 → 阿里云实例规格
INSTANCE_TYPES = {
    "2核2G": "ecs.e-c1m1.large",
    "2核4G": "ecs.e-c1m2.large",
    "4核8G": "ecs.e-c1m2.xlarge",
    "2核8G": "ecs.g7.large",
    "4核16G": "ecs.g7.2xlarge",
}


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return {}


def _save(p: Path, d: dict) -> None:
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")


def main() -> int:
    cfg = _load(CFG_FILE)
    al = (cfg.get("cloud_apis") or {}).get("aliyun") or {}
    ak = (al.get("access_key_id") or "").strip()
    sk = (al.get("access_key_secret") or "").strip()
    region = (al.get("region") or "cn-hangzhou").strip()

    if not ak or not sk:
        print("config.json 里 cloud_apis.aliyun 的 access_key_id / access_key_secret 还是空的。")
        print("去阿里云控制台 → 右上角头像 → AccessKey 管理，新建一个「只读」密钥，")
        print("（RAM 子账号挂 AliyunECSReadOnlyAccess 就够），填进 config.json 再跑一次。")
        return 1

    print("1) 验证 AK 并取系统镜像…")
    try:
        images = cloud_api.aliyun_images({"access_key_id": ak, "access_key_secret": sk, "region": region})
    except Exception as e:  # noqa: BLE001
        print("   失败：%s" % e)
        print("   常见原因：AccessKey 写错 / 子账号没给 ECS 读权限 / 地域写错（cn-hangzhou 等）")
        return 1
    if not images:
        print("   没取到系统镜像")
        return 1
    image_id = images[0]["id"]
    print("   OK：%s（%s）" % (image_id, images[0].get("name") or ""))

    data = _load(DATA_FILE)
    changed = 0
    for v in data.get("vendors", []):
        if v.get("id") != "aliyun":
            continue
        for seg in ("personal", "enterprise"):
            for it in v.get(seg, []):
                name = it.get("name", "")
                hit = None
                # 先精确匹配 "2核2G" 这类，避免 "4核8G" 被 "2核8G" 误匹配
                for k in sorted(INSTANCE_TYPES, key=len, reverse=True):
                    if k in name:
                        hit = INSTANCE_TYPES[k]
                        break
                if not hit:
                    continue
                period = 12 if it.get("unit") == "年" else 1
                spec = {
                    "InstanceType": hit,
                    "ImageId": image_id,
                    "Period": period,
                    "PriceUnit": "Month",
                    "Amount": 1,
                }
                print("2) 询价 %s（%s）…" % (name, hit), end=" ")
                r = cloud_api.query("aliyun", {"access_key_id": ak, "access_key_secret": sk, "region": region}, spec)
                if r.get("ok"):
                    d = r["data"]
                    print("%.1f 元（原价 %.1f 元）" % (
                        float(d.get("discount") or d.get("original") or 0),
                        float(d.get("original") or 0)))
                    it["api_spec"] = spec
                    changed += 1
                else:
                    print("失败：%s" % (r.get("error") or "")[:80])

    if changed:
        _save(DATA_FILE, data)
        print("\n已把 %d 条 api_spec 写回 cloud_price_data.json" % changed)
    else:
        print("\n没有写回任何配置（询价全失败）")
    print("\n下一步：打开 http://127.0.0.1:8799/?panel=cloudprice 刷新看看")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())