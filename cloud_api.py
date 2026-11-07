#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云厂商官方询价 API 对接 —— 只询价、不下单、不产生费用。

支持的接口（都是厂商公开文档里的官方 API，需要自己账号的只读 AK）：
  · 腾讯云  CVM  InquiryPriceRunInstances  TC3-HMAC-SHA256
  · 阿里云  ECS  DescribePrice             RPC 签名（HMAC-SHA1）
  · 华为云  BSS  ListRateOnPeriodDetail    AK/SK 签名（需要开通 BSS 接口 + 产品 ID）

注意：
  1. 这里返回的是**官方标准价**（原价 / 折扣价），通常不含新用户活动价，
     和面板上的「参考价」（活动价）是两回事，页面上分开显示。
  2. 没有 AK 时不要启用；启用后会把询价结果缓存 10 分钟，避免反复调用。
  3. 华为云的 BSS 接口参数依赖具体产品 ID，默认关闭，需要时再配。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

TIMEOUT = 25


def _http(url: str, method: str = "GET", headers: dict | None = None,
          body: bytes | None = None, timeout: int = TIMEOUT) -> dict:
    req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 阿里云等把错误信息放在 4xx 的 JSON body 里
        raw = e.read().decode("utf-8", "ignore")
        try:
            return json.loads(raw)
        except Exception:
            raise RuntimeError("HTTP %d: %s" % (e.code, raw[:160])) from None


# ---------------------------------------------------------------- 腾讯云

def tc3_call(cfg: dict, service: str, action: str, version: str,
             region: str, payload: dict, timeout: int = TIMEOUT) -> dict:
    """腾讯云通用调用（TC3-HMAC-SHA256），返回 Response 字段。"""
    sid, skey = cfg.get("secret_id") or "", cfg.get("secret_key") or ""
    if not sid or not skey:
        raise RuntimeError("未配置 secret_id / secret_key")

    host = "%s.tencentcloudapi.com" % service
    payload_text = json.dumps(payload, ensure_ascii=False)
    ts = int(time.time())
    date = time.strftime("%Y-%m-%d", time.gmtime(ts))
    ct = "application/json; charset=utf-8"
    canonical_headers = "content-type:%s\nhost:%s\nx-tc-action:%s\n" % (ct, host, action.lower())
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    canonical_request = "POST\n/\n\n%s\n%s\n%s" % (canonical_headers, signed_headers, hashed_payload)
    scope = "%s/%s/tc3_request" % (date, service)
    string_to_sign = "TC3-HMAC-SHA256\n%d\n%s\n%s" % (
        ts, scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest())
    k_date = hmac.new(("TC3" + skey).encode("utf-8"), date.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_date, service.encode("utf-8"), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = ("TC3-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s"
                     % (sid, scope, signed_headers, signature))
    headers = {
        "Authorization": authorization,
        "Content-Type": ct,
        "X-TC-Action": action,
        "X-TC-Version": version,
        "X-TC-Timestamp": str(ts),
        "X-TC-Region": region,
    }
    d = _http("https://" + host, "POST", headers, payload_text.encode("utf-8"), timeout)
    resp = d.get("Response") or {}
    if resp.get("Error"):
        raise RuntimeError("%s: %s" % (resp["Error"].get("Code"), resp["Error"].get("Message")))
    return resp


def tencent_inquiry(cfg: dict, spec: dict, timeout: int = TIMEOUT) -> dict:
    """InquiryPriceRunInstances：只询价，不创建实例。"""
    region = cfg.get("region") or "ap-guangzhou"
    resp = tc3_call(cfg, "cvm", "InquiryPriceRunInstances", "2017-03-12",
                    region, spec, timeout=timeout)
    p = resp.get("Price") or {}
    inst = p.get("InstancePrice") or {}
    bw = p.get("BandwidthPrice") or {}
    return {
        "original": inst.get("OriginalPrice"),
        "discount": inst.get("DiscountPrice"),
        "bandwidth": bw.get("DiscountPrice") or bw.get("OriginalPrice"),
        "unit": inst.get("ChargeUnit"),
        "raw": p,
    }


def tencent_images(cfg: dict, region: str | None = None, platform: str = "Ubuntu") -> list:
    """列公共镜像（拿询价要用的 ImageId）。"""
    region = region or cfg.get("region") or "ap-guangzhou"
    resp = tc3_call(cfg, "cvm", "DescribeImages", "2017-03-12", region,
                    {"ImageType": "PUBLIC_IMAGE", "Platform": platform, "Limit": 10})
    return [{"id": x.get("ImageId"), "name": x.get("ImageName")}
            for x in (resp.get("ImageSet") or [])]


# ---------------------------------------------------------------- 阿里云

def _pct(s) -> str:
    return urllib.parse.quote(str(s), safe="~")


def aliyun_price(cfg: dict, spec: dict, timeout: int = TIMEOUT) -> dict:
    """DescribePrice：只查价。spec 需要 InstanceType / ImageId / Period / PriceUnit。"""
    ak, sk = cfg.get("access_key_id") or "", cfg.get("access_key_secret") or ""
    if not ak or not sk:
        raise RuntimeError("未配置 access_key_id / access_key_secret")

    params = {
        "Action": "DescribePrice",
        "Version": "2014-05-26",
        "Format": "JSON",
        "AccessKeyId": ak,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": str(uuid.uuid4()),
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "RegionId": cfg.get("region") or "cn-hangzhou",
    }
    params.update({k: v for k, v in spec.items() if v not in (None, "")})
    canonical = "&".join("%s=%s" % (_pct(k), _pct(v)) for k, v in sorted(params.items()))
    string_to_sign = "GET&%2F&" + _pct(canonical)
    signature = base64.b64encode(
        hmac.new((sk + "&").encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    ).decode()
    url = "https://ecs.aliyuncs.com/?" + canonical + "&Signature=" + _pct(signature)

    d = _http(url, "GET", {"User-Agent": "dsh-workbench/1.1"}, None, timeout)
    if d.get("Code"):
        raise RuntimeError("%s: %s" % (d.get("Code"), d.get("Message")))
    info = d.get("PriceInfo") or {}
    price = info.get("Price") or {}
    return {
        "original": price.get("OriginalPrice"),
        "discount": price.get("DiscountPrice"),
        "trade": price.get("TradePrice"),
        "currency": price.get("Currency"),
        "unit": price.get("PriceUnit"),
        "raw": price,
    }


# ---------------------------------------------------------------- 华为云

def huawei_rate(cfg: dict, spec: dict, timeout: int = TIMEOUT) -> dict:
    """ListRateOnPeriodDetail：按需/包周期产品价格。

    华为云的 BSS 接口要先知道产品的 cloud_service_type / resource_type /
    resource_spec（格式如 s6.large.2），并且在账号里开通 BSS 读取权限，
    比另外两家重，默认不启用。
    """
    ak, sk = cfg.get("ak") or "", cfg.get("sk") or ""
    if not ak or not sk:
        raise RuntimeError("未配置 ak / sk")
    if not spec.get("product_infos"):
        raise RuntimeError("华为云需要 product_infos 配置（见文档）")

    host = "bss.myhuaweicloud.com"
    uri = "/v2/bills/ratings/period-resources/subscribe-rate"
    payload = json.dumps(spec, ensure_ascii=False)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    ct = "application/json; charset=utf-8"
    canonical_headers = "content-type:application/json\nhost:%s\nx-sdk-date:%s\n" % (host, ts)
    signed_headers = "content-type;host;x-sdk-date"
    hex_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = "POST\n%s\n\n%s\n%s\n%s" % (uri, canonical_headers, signed_headers, hex_payload)
    string_to_sign = "SDK-HMAC-SHA256\n%s\n%s" % (
        ts, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest())
    signature = hmac.new(sk.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = ("SDK-HMAC-SHA256 Access=%s, SignedHeaders=%s, Signature=%s"
                     % (ak, signed_headers, signature))

    headers = {
        "Authorization": authorization,
        "Content-Type": ct,
        "X-Sdk-Date": ts,
        "Host": host,
    }
    d = _http("https://" + host + uri, "POST", headers, payload.encode("utf-8"), timeout)
    if d.get("error_code"):
        raise RuntimeError("%s: %s" % (d.get("error_code"), d.get("error_msg")))
    return {"raw": d}


# ---------------------------------------------------------------- 统一入口

FUNCS = {
    "tencent": tencent_inquiry,
    "aliyun": aliyun_price,
    "huawei": huawei_rate,
}


def query(vendor: str, cfg: dict, spec: dict) -> dict:
    fn = FUNCS.get(vendor)
    if not fn:
        return {"ok": False, "error": "不支持的厂商：%s" % vendor}
    t0 = time.time()
    try:
        data = fn(cfg, spec)
        return {"ok": True, "at": time.time(), "ms": int((time.time() - t0) * 1000), "data": data}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "at": time.time(), "ms": int((time.time() - t0) * 1000),
                "error": "%s: %s" % (type(e).__name__, str(e)[:160])}