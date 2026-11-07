#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""腾讯云询价配置向导 —— 填好 AK 后跑一次，自动取镜像、测价、回填配置。

用法
----
    1. 打开 config.json，把 cloud_apis.tencent 的两项填上：
         "secret_id":  "AKID..."      （腾讯云控制台 → 访问管理 → API 密钥管理）
         "secret_key": "..."
    2. 运行：python cloud_tencent_setup.py
    3. 脚本会：
         · 验证 AK
         · 拉一个公共 Ubuntu 镜像 ImageId
         · 对 cloud_price_data.json 里每条腾讯云配置试询价
         · 把可用的 api_spec 写回 cloud_price_data.json
         · 打印每条配置的官方标准价
    4. 回工作台刷新「云服务器比价」面板，卡片上会出现「官方询价」
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

# 机型 → 询价参数（腾讯云标准型 S5）
INSTANCE_TYPES = {
    "2核2G": "S5.MEDIUM2",
    "2核4G": "S5.MEDIUM4",
    "4核8G": "S5.LARGE8",
    "2核8G": "S5.MEDIUM8",
    "4核16G": "S5.LARGE16",
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
    tc = (cfg.get("cloud_apis") or {}).get("tencent") or {}
    sid, skey = (tc.get("secret_id") or "").strip(), (tc.get("secret_key") or "").strip()
    region = (tc.get("region") or "ap-guangzhou").strip()

    if not sid or not skey:
        print("config.json 里 cloud_apis.tencent 的 secret_id / secret_key 还是空的。")
        print("去腾讯云控制台 → 访问管理 → API 密钥管理，新建一个「只读」子账号密钥，")
        print("（子账号策略给 QcloudCVMReadOnlyAccess 就够），填进 config.json 再跑一次。")
        return 1

    print("1) 验证 AK 并取公共镜像…")
    try:
        images = cloud_api.tencent_images({"secret_id": sid, "secret_key": skey, "region": region})
    except Exception as e:  # noqa: BLE001
        print("   失败：%s" % e)
        print("   常见原因：SecretId 写错 / 子账号没给 CVM 读权限 / 地域写错（ap-guangzhou 等）")
        return 1
    if not images:
        print("   没取到公共镜像，换个 region 试试")
        return 1
    image_id = images[0]["id"]
    print("   OK：%s（%s）" % (image_id, images[0].get("name") or ""))

    # 探测哪个可用区支持询价（不同地域可用区编号不一样）
    print("2) 探测可用区…")
    zone = None
    for z in ("ap-guangzhou-6", "ap-guangzhou-5", "ap-guangzhou-4",
              "ap-guangzhou-3", "ap-guangzhou-2", "ap-guangzhou-1"):
        probe = {
            "Placement": {"Zone": z}, "ImageId": image_id, "InstanceType": "S5.MEDIUM2",
            "InstanceChargeType": "PREPAID", "InstanceChargePrepaid": {"Period": 1},
            "SystemDisk": {"DiskType": "CLOUD_PREMIUM", "DiskSize": 40},
            "InternetAccessible": {"PublicIpAssigned": True, "InternetMaxBandwidthOut": 3},
        }
        r = cloud_api.query("tencent", {"secret_id": sid, "secret_key": skey, "region": region}, probe)
        if r.get("ok"):
            zone = z
            print("   用 %s" % z)
            break
        print("   %s 不行：%s" % (z, (r.get("error") or "")[:60]))
    if not zone:
        print("   所有可用区都不行，可能账号没开 CVM 或地域写错")
        return 1

    data = _load(DATA_FILE)
    changed = 0
    for v in data.get("vendors", []):
        if v.get("id") != "tencent":
            continue
        # 只对 CVM 询价：轻量应用服务器是 Lighthouse 产品，CVM 的询价接口查不出它的价
        for seg in ("enterprise",):
            for it in v.get(seg, []):
                name = it.get("name", "")
                hit = None
                for k, v2 in INSTANCE_TYPES.items():
                    if k in name:
                        hit = v2
                        break
                if not hit:
                    continue
                period = 12 if it.get("unit") == "年" else 1
                spec = {
                    "Placement": {"Zone": zone},
                    "ImageId": image_id,
                    "InstanceType": hit,
                    "InstanceChargeType": "PREPAID",
                    "InstanceChargePrepaid": {"Period": period},
                    "SystemDisk": {"DiskType": "CLOUD_PREMIUM", "DiskSize": int(it.get("disk") or 40)},
                    "InternetAccessible": {
                        "PublicIpAssigned": True,
                        "InternetMaxBandwidthOut": int(it.get("bw") or 3),
                    },
                }
                print("3) 询价 %s …" % name, end=" ")
                r = cloud_api.query("tencent", {"secret_id": sid, "secret_key": skey, "region": region}, spec)
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