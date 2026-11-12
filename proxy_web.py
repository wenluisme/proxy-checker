#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代理测试台 —— 本地网页版(纯标准库,启动后自动打开浏览器)

用法:
    python3 proxy_web.py               # 启动并自动打开浏览器
    python3 proxy_web.py --port 8000   # 指定端口
    python3 proxy_web.py --no-browser  # 只启动服务,不自动开浏览器

依赖同目录下的 proxy_test.py(共用解析与请求逻辑)。
"""

import argparse
import collections
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 嵌入式 Python(runtime-win)是隔离模式,不会自动把脚本目录加进 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import proxy_test as core
import team
import unlock_check

unlock_check.EXTRA_SITES = team.custom_sites

DEFAULT_PORT = 7799

# ISO 3166 国家/地区代码 → 中文名
COUNTRY_CN = {
    "AD": "安道尔", "AE": "阿联酋", "AF": "阿富汗", "AG": "安提瓜和巴布达", "AI": "安圭拉",
    "AL": "阿尔巴尼亚", "AM": "亚美尼亚", "AO": "安哥拉", "AQ": "南极洲", "AR": "阿根廷",
    "AS": "美属萨摩亚", "AT": "奥地利", "AU": "澳大利亚", "AW": "阿鲁巴", "AX": "奥兰群岛",
    "AZ": "阿塞拜疆", "BA": "波黑", "BB": "巴巴多斯", "BD": "孟加拉国", "BE": "比利时",
    "BF": "布基纳法索", "BG": "保加利亚", "BH": "巴林", "BI": "布隆迪", "BJ": "贝宁",
    "BL": "圣巴泰勒米", "BM": "百慕大", "BN": "文莱", "BO": "玻利维亚", "BQ": "荷兰加勒比区",
    "BR": "巴西", "BS": "巴哈马", "BT": "不丹", "BW": "博茨瓦纳", "BY": "白俄罗斯",
    "BZ": "伯利兹", "CA": "加拿大", "CC": "科科斯群岛", "CD": "刚果(金)", "CF": "中非",
    "CG": "刚果(布)", "CH": "瑞士", "CI": "科特迪瓦", "CK": "库克群岛", "CL": "智利",
    "CM": "喀麦隆", "CN": "中国", "CO": "哥伦比亚", "CR": "哥斯达黎加", "CU": "古巴",
    "CV": "佛得角", "CW": "库拉索", "CX": "圣诞岛", "CY": "塞浦路斯", "CZ": "捷克",
    "DE": "德国", "DJ": "吉布提", "DK": "丹麦", "DM": "多米尼克", "DO": "多米尼加",
    "DZ": "阿尔及利亚", "EC": "厄瓜多尔", "EE": "爱沙尼亚", "EG": "埃及", "EH": "西撒哈拉",
    "ER": "厄立特里亚", "ES": "西班牙", "ET": "埃塞俄比亚", "FI": "芬兰", "FJ": "斐济",
    "FK": "福克兰群岛", "FM": "密克罗尼西亚", "FO": "法罗群岛", "FR": "法国", "GA": "加蓬",
    "GB": "英国", "GD": "格林纳达", "GE": "格鲁吉亚", "GF": "法属圭亚那", "GG": "根西",
    "GH": "加纳", "GI": "直布罗陀", "GL": "格陵兰", "GM": "冈比亚", "GN": "几内亚",
    "GP": "瓜德罗普", "GQ": "赤道几内亚", "GR": "希腊", "GT": "危地马拉", "GU": "关岛",
    "GW": "几内亚比绍", "GY": "圭亚那", "HK": "中国香港", "HN": "洪都拉斯", "HR": "克罗地亚",
    "HT": "海地", "HU": "匈牙利", "ID": "印度尼西亚", "IE": "爱尔兰", "IL": "以色列",
    "IM": "马恩岛", "IN": "印度", "IO": "英属印度洋领地", "IQ": "伊拉克", "IR": "伊朗",
    "IS": "冰岛", "IT": "意大利", "JE": "泽西", "JM": "牙买加", "JO": "约旦",
    "JP": "日本", "KE": "肯尼亚", "KG": "吉尔吉斯斯坦", "KH": "柬埔寨", "KI": "基里巴斯",
    "KM": "科摩罗", "KN": "圣基茨和尼维斯", "KP": "朝鲜", "KR": "韩国", "KW": "科威特",
    "KY": "开曼群岛", "KZ": "哈萨克斯坦", "LA": "老挝", "LB": "黎巴嫩", "LC": "圣卢西亚",
    "LI": "列支敦士登", "LK": "斯里兰卡", "LR": "利比里亚", "LS": "莱索托", "LT": "立陶宛",
    "LU": "卢森堡", "LV": "拉脱维亚", "LY": "利比亚", "MA": "摩洛哥", "MC": "摩纳哥",
    "MD": "摩尔多瓦", "ME": "黑山", "MF": "法属圣马丁", "MG": "马达加斯加", "MH": "马绍尔群岛",
    "MK": "北马其顿", "ML": "马里", "MM": "缅甸", "MN": "蒙古", "MO": "中国澳门",
    "MP": "北马里亚纳群岛", "MQ": "马提尼克", "MR": "毛里塔尼亚", "MS": "蒙特塞拉特",
    "MT": "马耳他", "MU": "毛里求斯", "MV": "马尔代夫", "MW": "马拉维", "MX": "墨西哥",
    "MY": "马来西亚", "MZ": "莫桑比克", "NA": "纳米比亚", "NC": "新喀里多尼亚", "NE": "尼日尔",
    "NF": "诺福克岛", "NG": "尼日利亚", "NI": "尼加拉瓜", "NL": "荷兰", "NO": "挪威",
    "NP": "尼泊尔", "NR": "瑙鲁", "NU": "纽埃", "NZ": "新西兰", "OM": "阿曼",
    "PA": "巴拿马", "PE": "秘鲁", "PF": "法属波利尼西亚", "PG": "巴布亚新几内亚",
    "PH": "菲律宾", "PK": "巴基斯坦", "PL": "波兰", "PM": "圣皮埃尔和密克隆",
    "PR": "波多黎各", "PS": "巴勒斯坦", "PT": "葡萄牙", "PW": "帕劳", "PY": "巴拉圭",
    "QA": "卡塔尔", "RE": "留尼汪", "RO": "罗马尼亚", "RS": "塞尔维亚", "RU": "俄罗斯",
    "RW": "卢旺达", "SA": "沙特阿拉伯", "SB": "所罗门群岛", "SC": "塞舌尔", "SD": "苏丹",
    "SE": "瑞典", "SG": "新加坡", "SH": "圣赫勒拿", "SI": "斯洛文尼亚", "SK": "斯洛伐克",
    "SL": "塞拉利昂", "SM": "圣马力诺", "SN": "塞内加尔", "SO": "索马里", "SR": "苏里南",
    "SS": "南苏丹", "ST": "圣多美和普林西比", "SV": "萨尔瓦多", "SX": "荷属圣马丁",
    "SY": "叙利亚", "SZ": "斯威士兰", "TC": "特克斯和凯科斯群岛", "TD": "乍得", "TG": "多哥",
    "TH": "泰国", "TJ": "塔吉克斯坦", "TK": "托克劳", "TL": "东帝汶", "TM": "土库曼斯坦",
    "TN": "突尼斯", "TO": "汤加", "TR": "土耳其", "TT": "特立尼达和多巴哥", "TV": "图瓦卢",
    "TW": "中国台湾", "TZ": "坦桑尼亚", "UA": "乌克兰", "UG": "乌干达", "US": "美国",
    "UY": "乌拉圭", "UZ": "乌兹别克斯坦", "VA": "梵蒂冈", "VC": "圣文森特和格林纳丁斯",
    "VE": "委内瑞拉", "VG": "英属维尔京群岛", "VI": "美属维尔京群岛", "VN": "越南",
    "VU": "瓦努阿图", "WF": "瓦利斯和富图纳", "WS": "萨摩亚", "YE": "也门", "YT": "马约特",
    "ZA": "南非", "ZM": "赞比亚", "ZW": "津巴布韦",
}


def builtin_token():
    return getattr(core, "DEFAULT_IPINFO_TOKEN", "").strip()


def effective_token(payload):
    return str(payload.get("token") or "").strip() or builtin_token()


# ──────────────────────────── 协议探测 ────────────────────────────

class Socks5AuthError(Exception):
    pass


def _recvn(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionResetError("连接被对方关闭")
        buf += chunk
    return buf


def _geo_from_ipinfo(d):
    """把 ipinfo 的返回整理成 {ip, cn, en, org}(cn 用国家代码表翻译)。"""
    if not isinstance(d, dict) or not d.get("ip"):
        return None
    code = d.get("country") or ""
    en = ", ".join(x for x in (d.get("city"), d.get("region"), code) if x)
    return {"ip": d.get("ip"), "cn": COUNTRY_CN.get(code, code), "en": en,
            "org": d.get("org") or ""}


def _probe_http(px, timeout, ssl_ctx):
    """HTTP 转发模式:经代理请求一个 http:// 地址。"""
    t0 = time.perf_counter()
    url = ("http://ip-api.com/json/?lang=zh-CN"
           "&fields=status,message,country,regionName,city,timezone,isp,query")
    status, reason, body, _ = core.fetch_via_proxy(px, url, timeout, ssl_ctx)
    ms = (time.perf_counter() - t0) * 1000
    if status == 407:
        return {"ok": False, "ms": ms, "error": "代理认证失败(HTTP 407)", "auth": True}
    if 200 <= status < 400:
        geo = None
        try:
            d = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            return {"ok": False, "ms": ms,
                    "error": "代理返回了非预期内容,HTTP 转发可能被劫持"}
        if isinstance(d, dict) and d.get("status") == "success":
            loc = " ".join(str(x) for x in
                           (d.get("country"), d.get("regionName"), d.get("city")) if x)
            geo = {"ip": d.get("query"), "cn": loc, "en": "", "org": d.get("isp") or ""}
        return {"ok": True, "ms": ms, "exit": geo}
    return {"ok": False, "ms": ms, "error": f"HTTP {status} {reason}"}


def _probe_https(px, timeout, ssl_ctx):
    """HTTPS 隧道模式:CONNECT + TLS 请求 ipinfo。"""
    t0 = time.perf_counter()
    status, reason, body, _ = core.fetch_via_proxy(
        px, "https://ipinfo.io/json", timeout, ssl_ctx)
    ms = (time.perf_counter() - t0) * 1000
    if status == 200:
        try:
            geo = _geo_from_ipinfo(json.loads(body.decode("utf-8", "replace")))
        except ValueError:
            geo = None
        return {"ok": True, "ms": ms, "exit": geo}
    if status == 407:
        return {"ok": False, "ms": ms, "error": "代理认证失败(HTTP 407)", "auth": True}
    return {"ok": False, "ms": ms, "error": f"HTTP {status} {reason}"}


def _probe_socks5(px, timeout, ssl_ctx):
    """SOCKS5 模式:手动握手 + 帐密认证 + CONNECT ipinfo.io:443 + TLS 请求。"""
    t0 = time.perf_counter()
    s = socket.create_connection((px.host, px.port), timeout=timeout)
    try:
        s.settimeout(timeout)
        methods = b"\x00\x02" if px.user else b"\x00"
        s.sendall(b"\x05" + bytes([len(methods)]) + methods)
        ver, method = _recvn(s, 2)
        if ver != 5:
            raise ValueError("该端口不提供 SOCKS5 服务")
        if method == 0xFF:
            raise Socks5AuthError("SOCKS5 服务器拒绝了所有认证方式")
        if method == 0x02:
            u = (px.user or "").encode("utf-8")[:255]
            pw = (px.password or "").encode("utf-8")[:255]
            s.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(pw)]) + pw)
            _av, astat = _recvn(s, 2)
            if astat != 0:
                raise Socks5AuthError("SOCKS5 认证失败:用户名或密码不对")
        elif method != 0x00:
            raise ValueError(f"SOCKS5 认证方式不支持(0x{method:02x})")
        host = b"ipinfo.io"
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(host)]) + host
                  + (443).to_bytes(2, "big"))
        rep = _recvn(s, 4)
        if rep[1] != 0x00:
            reasons = {1: "一般性失败", 2: "规则不允许", 3: "网络不可达", 4: "主机不可达",
                       5: "连接被拒绝", 6: "TTL 超时", 7: "命令不支持", 8: "地址类型不支持"}
            raise ValueError("SOCKS5 无法连到目标:"
                             + reasons.get(rep[1], f"错误码 {rep[1]}"))
        atyp = rep[3]
        if atyp == 0x01:
            _recvn(s, 6)
        elif atyp == 0x03:
            _recvn(s, _recvn(s, 1)[0] + 2)
        elif atyp == 0x04:
            _recvn(s, 18)
        tls = ssl_ctx.wrap_socket(s, server_hostname="ipinfo.io")
        s = tls
        tls.sendall(b"GET /json HTTP/1.0\r\nHost: ipinfo.io\r\n"
                    b"User-Agent: proxy-tester/3.0\r\nAccept: application/json\r\n"
                    b"Connection: close\r\n\r\n")
        buf = b""
        while len(buf) < 262144:
            chunk = tls.recv(8192)
            if not chunk:
                break
            buf += chunk
        head, _, body = buf.partition(b"\r\n\r\n")
        first = head.split(b"\r\n", 1)[0].split()
        status = int(first[1]) if len(first) >= 2 and first[1].isdigit() else 0
        ms = (time.perf_counter() - t0) * 1000
        if 200 <= status < 400:
            geo = None
            try:
                geo = _geo_from_ipinfo(json.loads(body.decode("utf-8", "replace")))
            except ValueError:
                pass
            return {"ok": True, "ms": ms, "exit": geo}
        return {"ok": False, "ms": ms, "error": f"隧道建立成功但请求失败 HTTP {status}"}
    finally:
        try:
            s.close()
        except OSError:
            pass


def _run_probe(fn, px, timeout, ssl_ctx):
    t0 = time.perf_counter()
    try:
        return fn(px, timeout, ssl_ctx)
    except Socks5AuthError as e:
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000,
                "error": str(e), "auth": True}
    except Exception as e:
        return {"ok": False, "ms": (time.perf_counter() - t0) * 1000,
                "error": core.explain(e), "auth": "407" in str(e)}


# ──────────────────────────── 代理测试 ────────────────────────────

def run_test(payload):
    """测一条代理:解析 → 连接 → HTTP/HTTPS/SOCKS5 并发探测 →(选填)指定网站。"""
    line = str(payload.get("proxy") or "").strip()
    try:
        timeout = float(payload.get("timeout") or 10)
    except (TypeError, ValueError):
        timeout = 10
    timeout = min(max(timeout, 2), 60)

    targets = []
    dropped = []
    for t in (payload.get("targets") or [])[:10]:
        raw = str(t).strip()
        if not raw:
            continue
        try:
            t2 = raw
            if urllib.parse.urlsplit(t2).scheme not in ("http", "https"):
                t2 = "https://" + t2
            if urllib.parse.urlsplit(t2).hostname:
                targets.append(t2)
            else:
                dropped.append(raw)
        except ValueError:
            dropped.append(raw)

    res = {"input": line, "steps": [], "targets": [], "exit": None,
           "verdict": "fail", "verdict_text": ""}
    t_start = time.perf_counter()

    try:
        px = core.parse_proxy(line)
    except ValueError as e:
        res["verdict"] = "bad-input"
        res["verdict_text"] = f"格式不对:{e}"
        return res
    res["proxy"] = f"{px.host}:{px.port}"
    res["auth_source"] = px.auth_source

    # 1. DNS 解析
    t0 = time.perf_counter()
    try:
        infos = socket.getaddrinfo(px.host, px.port, type=socket.SOCK_STREAM)
        ips = sorted({i[4][0] for i in infos})
        res["steps"].append({"key": "dns", "ok": True,
                             "ms": (time.perf_counter() - t0) * 1000,
                             "info": ips[0] + (" 等" if len(ips) > 1 else "")})
    except Exception as e:
        res["steps"].append({"key": "dns", "ok": False,
                             "ms": (time.perf_counter() - t0) * 1000,
                             "error": core.explain(e)})
        res["verdict_text"] = core.explain(e)
        return res

    # 2. TCP 连接
    t0 = time.perf_counter()
    try:
        s = socket.create_connection((px.host, px.port), timeout=timeout)
        s.close()
        res["steps"].append({"key": "tcp", "ok": True,
                             "ms": (time.perf_counter() - t0) * 1000})
    except Exception as e:
        res["steps"].append({"key": "tcp", "ok": False,
                             "ms": (time.perf_counter() - t0) * 1000,
                             "error": core.explain(e)})
        res["verdict_text"] = core.explain(e)
        return res

    # 3. 三种协议并发探测
    ssl_ctx = ssl.create_default_context()
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [("http", ex.submit(_run_probe, _probe_http, px, timeout, ssl_ctx)),
                ("https", ex.submit(_run_probe, _probe_https, px, timeout, ssl_ctx)),
                ("socks5", ex.submit(_run_probe, _probe_socks5, px, timeout, ssl_ctx))]
        probes = {k: f.result() for k, f in futs}

    ok_list = []
    auth_any = False
    for key in ("http", "https", "socks5"):
        p = probes[key]
        step = {"key": key, "ok": bool(p.get("ok")), "ms": p.get("ms")}
        if p.get("error"):
            step["error"] = p["error"]
        if p.get("auth"):
            step["auth"] = True
        res["steps"].append(step)
        if p.get("ok"):
            ok_list.append(key)
        if p.get("auth"):
            auth_any = True

    # 出口信息:HTTPS > SOCKS5 > HTTP
    for key in ("https", "socks5", "http"):
        if probes[key].get("exit"):
            res["exit"] = probes[key]["exit"]
            break

    # 4. 用户指定的网站(填了才测)
    target_ok = 0
    tested_web = False
    total_targets = len(targets) + len(dropped)
    if total_targets:
        for d in dropped:
            res["targets"].append({"url": d, "ok": False,
                                   "error": "网址格式不对,未测试"})
        if targets and ("http" in ok_list or "https" in ok_list):
            tested_web = True
            for url in targets:
                try:
                    status, reason, body, ms = core.fetch_via_proxy(
                        px, url, timeout, ssl_ctx)
                    good = 200 <= status < 400
                    item = {"url": url, "ok": good, "status": status, "ms": ms}
                    if good:
                        target_ok += 1
                    else:
                        item["error"] = f"HTTP {status} {reason}"
                    res["targets"].append(item)
                except Exception as e:
                    res["targets"].append({"url": url, "ok": False,
                                           "error": core.explain(e)})
            res["steps"].append({"key": "web", "ok": target_ok > 0,
                                 "info": f"{target_ok}/{total_targets}"})
        else:
            for url in targets:
                res["targets"].append({"url": url, "ok": False,
                                       "error": "HTTP/HTTPS 协议不通,未测试"})
            res["steps"].append({"key": "web", "skipped": True, "info": "未测试"})

    # 结论
    proto_name = {"http": "HTTP", "https": "HTTPS", "socks5": "SOCKS5"}
    bad_list = [k for k in ("http", "https", "socks5") if k not in ok_list]
    if auth_any and not ok_list:
        res["verdict"] = "auth-fail"
        res["verdict_text"] = "认证失败,请核对用户名和密码"
    elif len(ok_list) == 3:
        res["verdict"] = "full"
        res["verdict_text"] = "HTTP / HTTPS / SOCKS5 全部可用"
    elif ok_list:
        res["verdict"] = "partial"
        res["verdict_text"] = ("可用:" + "、".join(proto_name[k] for k in ok_list)
                               + ";不通:" + "、".join(proto_name[k] for k in bad_list))
    else:
        first_err = next((s.get("error") for s in res["steps"] if s.get("error")), None)
        res["verdict"] = "fail"
        res["verdict_text"] = "三种协议都不通" + (f" —— {first_err}" if first_err else "")

    if total_targets:
        if tested_web and target_ok == 0 and ok_list:
            res["verdict"] = "exit-blocked"
            res["verdict_text"] += ";填写的网站都访问失败,出口可能被目标站封锁"
        elif tested_web:
            res["verdict_text"] += f";网站访问 {target_ok}/{total_targets}"
        elif not targets:
            res["verdict_text"] += ";指定网站格式不对,未测试"
        else:
            res["verdict_text"] += ";指定网站未测试,HTTP/HTTPS 不通"

    res["total_ms"] = (time.perf_counter() - t_start) * 1000
    return res


# ──────────────────────────── IP 归属地 ────────────────────────────

_IP_CACHE = collections.OrderedDict()
_IP_CACHE_LOCK = threading.Lock()
_IP_CACHE_MAX = 512


def _cache_get(key):
    with _IP_CACHE_LOCK:
        hit = _IP_CACHE.get(key)
        if hit is not None:
            _IP_CACHE.move_to_end(key)
            return dict(hit)
    return None


def _cache_put(key, data):
    with _IP_CACHE_LOCK:
        _IP_CACHE[key] = dict(data)
        _IP_CACHE.move_to_end(key)
        while len(_IP_CACHE) > _IP_CACHE_MAX:
            _IP_CACHE.popitem(last=False)


# ipinfo 直连不可达时的熔断:90 秒内直接走备用源
_IPINFO_DOWN_UNTIL = 0.0

# ip-api 免费档限 45 次/分,主动限速到 40 次/分
_IPAPI_LOCK = threading.Lock()
_IPAPI_TIMES = collections.deque()


def _ipapi_throttle():
    while True:
        with _IPAPI_LOCK:
            now = time.time()
            while _IPAPI_TIMES and now - _IPAPI_TIMES[0] > 60:
                _IPAPI_TIMES.popleft()
            if len(_IPAPI_TIMES) < 40:
                _IPAPI_TIMES.append(now)
                return
            wait = 60 - (now - _IPAPI_TIMES[0]) + 0.1
        time.sleep(min(wait, 5))


def _ip_api_query(ip, timeout):
    """直连 ip-api(中文),返回原始 dict。带限速。"""
    _ipapi_throttle()
    url = ("http://ip-api.com/json/" + urllib.parse.quote(ip)
           + "?lang=zh-CN&fields=status,message,country,regionName,city,timezone,isp,query")
    req = urllib.request.Request(url, headers={
        "User-Agent": "proxy-tester/3.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise ValueError("备用源暂时限流,约 1 分钟后重试")
        raise
    if not isinstance(d, dict):
        raise ValueError("返回数据异常")
    return d


def _ip_api_fallback(ip, timeout):
    """ipinfo 全部失败时的免费备用源。"""
    d = _ip_api_query(ip, timeout)
    if d.get("status") != "success":
        msg = (d.get("message") or "").lower()
        if msg in ("private range", "reserved range"):
            return {"ip": d.get("query") or ip, "bogon": True, "_source": "ip-api"}
        if msg == "invalid query":
            raise ValueError("不是合法的 IP 地址")
        raise ValueError(d.get("message") or "查询失败")
    return {"ip": d.get("query") or ip, "city": d.get("city"),
            "region": d.get("regionName"), "country": d.get("country"),
            "org": d.get("isp"), "timezone": d.get("timezone"), "_source": "ip-api"}


def _enrich_cn(data, timeout):
    """补充中英双语位置:loc_cn / loc_en。中文城市来自 ip-api,失败则只翻译国家。"""
    if not isinstance(data, dict) or data.get("bogon"):
        return data
    src = data.get("_source")
    if src == "ip-api":
        data["loc_cn"] = " ".join(str(x) for x in
                                  (data.get("country"), data.get("region"),
                                   data.get("city")) if x)
        data["loc_en"] = ""
        return data
    if src == "lite":
        code = data.get("country_code") or ""
        data["loc_cn"] = COUNTRY_CN.get(code, code)
        data["loc_en"] = ", ".join(str(x) for x in (data.get("country"), code) if x)
        return data
    # 标准接口:country 是两位代码
    code = data.get("country") or ""
    data["loc_en"] = ", ".join(str(x) for x in
                               (data.get("city"), data.get("region"), code) if x)
    data["loc_cn"] = COUNTRY_CN.get(code, code)
    ip = data.get("ip")
    if ip:
        try:
            z = _ip_api_query(ip, min(timeout, 5))
            if z.get("status") == "success":
                # 国家用内置简体对照表(ip-api 偶尔返回繁体),省市用 ip-api 的中文
                parts = [data["loc_cn"] or z.get("country"),
                         z.get("regionName"), z.get("city")]
                data["loc_cn"] = " ".join(str(x) for x in parts if x)
        except Exception:
            pass
    return data


def lookup_ip(payload):
    """查 IP 归属地:ipinfo 标准 → Lite → 备用源,双语显示,带缓存和熔断。"""
    global _IPINFO_DOWN_UNTIL
    ip = str(payload.get("ip") or "").strip()
    if ip and not re.fullmatch(r"[0-9.]+|[0-9a-fA-F:]+", ip):
        try:  # 代理域名先解析成 IP 再查归属地
            ip = socket.gethostbyname(ip)
        except OSError:
            return {"ip": ip, "error": "域名解析失败"}
    token = effective_token(payload)
    try:
        timeout = min(max(float(payload.get("timeout") or 10), 2), 30)
    except (TypeError, ValueError):
        timeout = 10

    cache_key = (ip, token)
    if ip:
        hit = _cache_get(cache_key)
        if hit is not None:
            hit["_cached"] = True
            return hit

    quoted = urllib.parse.quote(ip)
    attempts = []
    if token:
        qt = urllib.parse.quote(token)
        attempts.append(("standard",
                         f"https://ipinfo.io/{quoted}/json?token={qt}" if ip
                         else f"https://ipinfo.io/json?token={qt}"))
        attempts.append(("lite",
                         f"https://api.ipinfo.io/lite/{quoted or 'me'}?token={qt}"))
    else:
        attempts.append(("standard",
                         f"https://ipinfo.io/{quoted}/json" if ip
                         else "https://ipinfo.io/json"))

    errors = []
    if time.time() < _IPINFO_DOWN_UNTIL:
        attempts = []
        errors.append("ipinfo 暂时不可达,直接使用备用源")
    ipinfo_timeout = min(timeout, 5)
    for src, url in attempts:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "proxy-tester/3.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=ipinfo_timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            if not isinstance(data, dict):
                data = {}
            data["_source"] = src
            if not data.get("ip"):
                data["ip"] = ip
            data = _enrich_cn(data, timeout)
            if ip:
                _cache_put(cache_key, data)
            return data
        except urllib.error.HTTPError as e:
            name = "标准接口" if src == "standard" else "Lite 接口"
            if e.code == 429:
                errors.append(f"{name}:免费额度已用完")
            elif e.code in (401, 403):
                errors.append(f"{name}:token 无效或没有权限")
            elif e.code == 404:
                errors.append(f"{name}:不是合法的 IP 地址")
            else:
                errors.append(f"{name}:HTTP {e.code}")
        except Exception as e:
            name = "标准接口" if src == "standard" else "Lite 接口"
            if (isinstance(e, (socket.timeout, TimeoutError))
                    or "timed out" in str(e).lower()):
                _IPINFO_DOWN_UNTIL = time.time() + 90
                errors.append(f"{name}:连接超时")
            elif isinstance(e, urllib.error.URLError):
                _IPINFO_DOWN_UNTIL = time.time() + 90
                errors.append(f"{name}:连不上({e.reason})")
            else:
                errors.append(f"{name}:{core.explain(e)}")

    # ipinfo 所有途径都失败:换免费备用源
    try:
        data = _enrich_cn(_ip_api_fallback(ip, timeout), timeout)
        if ip:
            _cache_put(cache_key, data)
        return data
    except Exception as e:
        if (isinstance(e, (socket.timeout, TimeoutError))
                or "timed out" in str(e).lower()):
            errors.append("备用源 ip-api:连接超时")
        else:
            errors.append(f"备用源 ip-api:{core.explain(e)}")
    return {"ip": ip, "error": ";".join(errors) or "查询失败"}


# ──────────────────────────── HTTP 服务 ────────────────────────────

# 团队版(--server):要登录;本机版:不用登录,数据记在本机账号下
TEAM = {"on": False}
LOCAL_USER = {"id": 0, "username": "本机", "is_admin": 1}
COOKIE = "pt_session"


def _public_host(host):
    """团队版里只允许连公网地址,防止有人借工具探测公司内网。"""
    import ipaddress
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True  # 解析不了交给后面的步骤报错
    for i in infos:
        ip = ipaddress.ip_address(i[4][0].split("%")[0])
        if ip in ipaddress.ip_network("198.18.0.0/15"):
            continue  # Clash / 小火箭的 fake-ip 段,不是真实内网
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def _check_targets(payload):
    if not TEAM["on"]:
        return None
    hosts = []
    if payload.get("proxy"):
        try:
            hosts.append(core.parse_proxy(str(payload["proxy"])).host)
        except ValueError:
            pass
    for t in payload.get("targets") or []:
        t = str(t).strip()
        if t:
            hosts.append(urllib.parse.urlsplit(t if "://" in t else "https://" + t).hostname or "")
    if payload.get("url"):
        u = str(payload["url"])
        hosts.append(urllib.parse.urlsplit(u if "://" in u else "https://" + u).hostname or "")
    bad = [h for h in hosts if h and not _public_host(h)]
    return f"不允许访问内网地址:{'、'.join(bad)}" if bad else None


class Handler(BaseHTTPRequestHandler):
    server_version = "ProxyTester/4.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _host_ok(self):
        if TEAM["on"]:
            return True
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in ("127.0.0.1", "localhost", "[::1]", "::1")

    def _send(self, body, ctype, status=200, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200, headers=()):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", status, headers)

    def _token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return ""

    def _user(self):
        if not TEAM["on"]:
            return LOCAL_USER
        return team.user_by_token(self._token())

    def _client_ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def _cookie(self, value, max_age):
        secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return ("Set-Cookie", f"{COOKIE}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}")

    def do_GET(self):
        if not self._host_ok():
            self._json({"error": "forbidden"}, 403)
            return
        _PING["t"] = time.monotonic()  # 任何请求都算存活证据
        u = urllib.parse.urlsplit(self.path)
        path, qs = u.path, urllib.parse.parse_qs(u.query)
        user = self._user()
        if path == "/":
            page = HTML if user else LOGIN_HTML
            self._send(page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/ping":
            _PING["t"] = time.monotonic()
            self._json({"ok": True})
            return
        if not user:
            self._json({"error": "请先登录", "login": True}, 401)
            return
        try:
            if path == "/api/me":
                self._json({"user": user, "team": TEAM["on"]})
            elif path == "/api/unlock/sites":
                self._json({"sites": unlock_check.site_list(),
                            "kinds": [{"label": v[0], "reason": v[1], "advice": v[2]}
                                      for k, v in unlock_check.FAIL_KINDS.items() if k != "other"]})
            elif path == "/api/history":
                self._json({"items": team.list_history(user["id"])})
            elif path == "/api/history/get":
                h = team.get_history(user["id"], int((qs.get("id") or ["0"])[0]))
                self._json(h or {"error": "记录不存在"}, 200 if h else 404)
            elif path == "/api/admin/users":
                if not user["is_admin"]:
                    raise PermissionError
                self._json({"users": team.list_users()})
            else:
                self._json({"error": "not found"}, 404)
        except PermissionError:
            self._json({"error": "需要管理员权限"}, 403)

    def do_POST(self):
        if not self._host_ok():
            self._json({"error": "forbidden"}, 403)
            return
        _PING["t"] = time.monotonic()  # 任何请求都算存活证据
        path = urllib.parse.urlsplit(self.path).path
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            self._json({"error": "需要 JSON 请求"}, 415)  # 顺带挡掉跨站表单提交
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 60_000_000:
                raise ValueError
            raw = self.rfile.read(n) if n else b""
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError
        except Exception:
            self._json({"error": "请求体不是合法 JSON"}, 400)
            return

        if path == "/api/login":
            token, err = team.login(payload.get("username"), payload.get("password"), self._client_ip())
            if err:
                self._json({"error": err}, 401)
            else:
                self._json({"ok": True}, headers=[self._cookie(token, team.SESSION_DAYS * 86400)])
            return
        if path == "/api/logout":
            team.logout(self._token())
            self._json({"ok": True}, headers=[self._cookie("", 0)])
            return
        user = self._user()
        if not user:
            self._json({"error": "请先登录", "login": True}, 401)
            return
        bad = _check_targets(payload)
        if bad:
            self._json({"error": bad}, 400)
            return
        try:
            self._json(self._route(path, payload, user))
        except PermissionError:
            self._json({"error": "需要管理员权限"}, 403)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except LookupError:
            self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": f"服务器内部错误:{e}"}, 500)

    def _route(self, path, p, user):
        admin = bool(user["is_admin"])
        if path == "/api/test":
            return run_test(p)
        if path == "/api/ipinfo":
            return lookup_ip(p)
        if path == "/api/unlock/prepare":
            return unlock_check.prepare(p)
        if path == "/api/unlock/site":
            return unlock_check.run_site(p)
        if path == "/api/sites/add":
            return {"id": team.add_custom_site(p.get("url"), p.get("name"), p.get("group"), user["username"])}
        if path == "/api/sites/delete":
            team.delete_custom_site(str(p.get("id")), user)
            return {"ok": True}
        if path == "/api/history/save":
            return {"id": team.save_history(user["id"], p.get("title"), p.get("summary"), p.get("data"))}
        if path == "/api/history/update":
            team.update_history(user["id"], int(p.get("id") or 0), p.get("summary"), p.get("data"))
            return {"ok": True}
        if path == "/api/history/delete":
            team.delete_history(user["id"], int(p.get("id") or 0))
            return {"ok": True}
        if path == "/api/me/password":
            if TEAM["on"]:
                u = team.q("select pw_hash from users where id=?", (user["id"],), one=True)
                if not team._check_pw(p.get("old") or "", u["pw_hash"]):
                    raise ValueError("原密码不对")
                team.set_password(user["id"], p.get("new") or "")
            return {"ok": True, "relogin": TEAM["on"]}
        if not admin:
            raise PermissionError
        if path == "/api/admin/users/create":
            return {"id": team.create_user(p.get("username"), p.get("password"), bool(p.get("is_admin")))}
        if path == "/api/admin/users/password":
            team.set_password(int(p.get("id") or 0), p.get("password") or "")
            return {"ok": True}
        if path == "/api/admin/users/delete":
            if int(p.get("id") or 0) == user["id"]:
                raise ValueError("不能删除自己")
            team.delete_user(int(p.get("id") or 0))
            return {"ok": True}
        raise LookupError


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    # 默认排队只有 5 个连接(Windows 上很容易满):页面同时测 9 个站点时会被拒,前面的 HTTPS 网关就回空页
    request_queue_size = 128
    # Windows 上 SO_REUSEADDR 会允许绑到正被占用的端口,必须关掉才能正确触发端口顺延
    allow_reuse_address = (os.name != "nt")


# ── 独立窗口模式:页面每 3 秒发一次心跳,窗口关掉后服务器自动退出 ──
_PING = {"t": None}


def _watchdog():
    # 130 秒阈值:浏览器把后台页面的定时器节流到约 1 次/分钟时也不会误杀
    start = time.monotonic()
    prev = start
    while True:
        time.sleep(5)
        now = time.monotonic()
        slept = (now - prev) > 20  # 系统刚从睡眠中恢复
        prev = now
        lp = _PING["t"]
        if lp is None:
            if now - start > 300:  # 窗口一直没打开
                os._exit(0)
        elif slept:
            _PING["t"] = now  # 醒来后重新计时,给浏览器恢复心跳的机会
        elif now - lp > 130:
            os._exit(0)


def _find_app_browser():
    """找一个支持 --app 独立窗口模式的浏览器(Edge / Chrome)。"""
    cands = []
    if os.name == "nt":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            basep = os.environ.get(env)
            if basep:
                cands.append(os.path.join(basep, "Microsoft", "Edge",
                                          "Application", "msedge.exe"))
                cands.append(os.path.join(basep, "Google", "Chrome",
                                          "Application", "chrome.exe"))
    elif sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    else:
        cands = ["/usr/bin/google-chrome", "/usr/bin/microsoft-edge",
                 "/usr/bin/chromium-browser", "/usr/bin/chromium"]
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def _open_window(url, app_mode):
    if app_mode:
        browser = _find_app_browser()
        if browser:
            try:
                subprocess.Popen([browser, f"--app={url}", "--window-size=1080,800"],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return
            except OSError:
                pass
    webbrowser.open(url)


def main():
    ap = argparse.ArgumentParser(description="代理测试台(本地网页版)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--app", action="store_true",
                    help="以独立窗口打开,关掉窗口即退出")
    ap.add_argument("--server", action="store_true",
                    help="团队版:需要登录,监听所有网卡(建议放在 HTTPS 反向代理后面)")
    ap.add_argument("--host", default=None, help="监听地址(团队版默认 0.0.0.0)")
    args = ap.parse_args()
    if args.server:
        TEAM["on"] = True
        if team.user_count() == 0:
            print("还没有账号,先运行:python3 team.py adduser 用户名 --admin")
            return 1
        httpd = LocalServer((args.host or "0.0.0.0", args.port), Handler)
        print(f"  代理测试台(团队版)已启动:http://{args.host or '0.0.0.0'}:{args.port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0

    httpd = None
    port = args.port
    for offset in range(20):
        try:
            httpd = LocalServer(("127.0.0.1", args.port + offset), Handler)
            port = args.port + offset
            break
        except OSError:
            continue
    if httpd is None:
        print(f"端口 {args.port}~{args.port + 19} 都被占用,请用 --port 换一个")
        return 1

    url = f"http://127.0.0.1:{port}/"
    print()
    print(f"  代理测试台已启动: {url}")
    print("  关闭本窗口(或按 Ctrl+C)即停止服务")
    print()
    if not args.no_browser:
        threading.Timer(0.4, _open_window, args=(url, args.app)).start()
    if args.app:
        threading.Thread(target=_watchdog, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


# ──────────────────────────── 页面 ────────────────────────────

HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>代理测试台</title>
<link rel="icon" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMDI0IDEwMjQiPjxkZWZzPjxsaW5lYXJHcmFkaWVudCBpZD0iYmciIHgxPSIwIiB5MT0iMCIgeDI9IjEiIHkyPSIxIj48c3RvcCBvZmZzZXQ9IjAiIHN0b3AtY29sb3I9IiNGRkZGRkYiLz48c3RvcCBvZmZzZXQ9Ii41NSIgc3RvcC1jb2xvcj0iI0YwRURGRiIvPjxzdG9wIG9mZnNldD0iMSIgc3RvcC1jb2xvcj0iI0NEQzVGRiIvPjwvbGluZWFyR3JhZGllbnQ+PGxpbmVhckdyYWRpZW50IGlkPSJjIiB4MT0iMCIgeTE9IjAiIHgyPSIxIiB5Mj0iMSI+PHN0b3Agb2Zmc2V0PSIwIiBzdG9wLWNvbG9yPSIjOTQ1QkZEIi8+PHN0b3Agb2Zmc2V0PSIxIiBzdG9wLWNvbG9yPSIjNDUyOEQwIi8+PC9saW5lYXJHcmFkaWVudD48L2RlZnM+PHJlY3QgeD0iMTAwIiB5PSIxMDAiIHdpZHRoPSI4MjQiIGhlaWdodD0iODI0IiByeD0iMTg2IiBmaWxsPSJ1cmwoI2JnKSIgc3Ryb2tlPSIjRENEM0ZGIiBzdHJva2Utd2lkdGg9IjQiLz48Y2lyY2xlIGN4PSI1MTIiIGN5PSI1MTIiIHI9IjMzMCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjOTQ1QkZEIiBzdHJva2Utd2lkdGg9IjEwIiBvcGFjaXR5PSIuMjIiLz48Y2lyY2xlIGN4PSI1MTIiIGN5PSI1MTIiIHI9IjI2OCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjOTQ1QkZEIiBzdHJva2Utd2lkdGg9IjE0IiBvcGFjaXR5PSIuNDIiLz48Y2lyY2xlIGN4PSI1MTIiIGN5PSI1MTIiIHI9IjIwMCIgZmlsbD0idXJsKCNjKSIvPjxwYXRoIGQ9Ik0zOTIgNTIwaDU2bDM2LTk2IDU2IDE5MiAzNi05Nmg1NiIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjZmZmIiBzdHJva2Utd2lkdGg9IjM0IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz48Y2lyY2xlIGN4PSI3NDUiIGN5PSIzMDAiIHI9IjMwIiBmaWxsPSIjQzIxQkJBIi8+PC9zdmc+">
<style>
:root{
  --ink:#1C1C1C; --ink2:#565656; --ink3:#8F8C9C; --line:#ECE8F6; --bg:#FAF9FE; --card:#fff;
  --p1:#945BFD; --p2:#613EFB; --p3:#4528A4; --pl:#F5EEFF; --pl2:#ECE5FF; --mag:#C21BBA;
  --ok:#16A34A; --okbg:#EAF8EF; --warn:#D97706; --warnbg:#FEF4E6; --bad:#E5484D; --badbg:#FDEDEE;
  --fail:#6B6880; --failbg:#F1F0F5;
  --grad:linear-gradient(90deg,#945BFD,#613EFB);
  --mono:"SF Mono",ui-monospace,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font:14px/1.6 "Hanken Grotesk",-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
button{font:inherit;cursor:pointer}
input,textarea,select{font:inherit;color:var(--ink)}
[hidden]{display:none!important}
:focus-visible{outline:2px solid var(--p1);outline-offset:2px}

/* ── 顶部导航 ── */
.nav{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.92);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.nav-in{max-width:1320px;margin:0 auto;padding:0 40px;height:68px;display:flex;align-items:center;gap:36px}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:18px;letter-spacing:.2px;white-space:nowrap}
.brand img{width:40px;height:40px;margin:-4px}
.brand small{font-weight:500;color:var(--ink3);font-size:12px;border:1px solid var(--line);border-radius:6px;padding:1px 7px;margin-left:2px}
.tabs{display:flex;gap:6px;align-self:stretch}
.tab{border:0;background:none;color:var(--ink2);font-size:15px;padding:0 16px;position:relative;display:flex;align-items:center;gap:8px;white-space:nowrap}
.tab:hover{color:var(--ink)}
.tab.on{color:var(--p2);font-weight:600}
.tab.on:after{content:"";position:absolute;left:14px;right:14px;bottom:-1px;height:3px;border-radius:3px;background:var(--grad)}
.tab .cnt{font-size:11px;background:var(--pl2);color:var(--p3);border-radius:10px;padding:0 7px;font-weight:600}
.nav-r{margin-left:auto;display:flex;align-items:center;gap:18px;font-size:14px;white-space:nowrap}
.nav-r button.nl{border:0;background:none;color:var(--ink2);padding:0}
.nav-r button.nl:hover{color:var(--p2)}
.user{display:flex;align-items:center;gap:8px;color:var(--ink)}
.avatar{width:30px;height:30px;border-radius:50%;background:var(--grad);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px}

/* ── 主体 ── */
main{max-width:1320px;margin:0 auto;padding:36px 40px 72px}
.hero h1{margin:0;font-size:30px;font-weight:700;line-height:1.3;color:var(--ink)}
.hero p{margin:8px 0 24px;color:var(--ink2);font-size:15px}

/* 输入区:两个页面共用 */
.input{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:24px 28px;display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr) 220px;gap:24px;align-items:start;box-shadow:0 1px 2px rgba(25,18,40,.03)}
.fld label,.act .lbl{display:block;font-size:13px;color:var(--ink);margin:0 0 10px;font-weight:500;line-height:20px;white-space:nowrap}
.fld textarea{display:block;width:100%;height:104px;border:1px solid var(--line);background:#FCFBFF;border-radius:10px;padding:12px 14px;font:13px/1.65 var(--mono);color:var(--ink);resize:vertical}
.fld textarea:focus,.opt input:focus,.opt select:focus,.mform input:focus,.mform select:focus{outline:none;border-color:var(--p1);box-shadow:0 0 0 3px rgba(148,91,253,.15)}
.lbl-row{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px}
.lbl-row label{margin:0}
.act{display:flex;flex-direction:column;gap:12px}
.act .opt{height:20px;margin-bottom:-2px}
.btn{border:0;border-radius:10px;height:46px;padding:0 22px;font-weight:600;font-size:15px;white-space:nowrap;display:inline-flex;align-items:center;justify-content:center}
.act .btn{width:100%}
.btn:disabled{opacity:.5;cursor:default}
.btn.pri{background:var(--grad);color:#fff;box-shadow:0 6px 16px rgba(97,62,251,.24)}
.btn.pri:hover{filter:brightness(1.06)}
.btn.sec{background:var(--pl);color:var(--p3)}
.btn.sec:hover{background:var(--pl2)}
.btn.sm{height:34px;padding:0 16px;font-size:13px;border-radius:8px}
.opt{display:flex;gap:8px;align-items:center;font-size:13px;color:var(--ink2);white-space:nowrap}
.opt select,.opt input{height:34px;border:1px solid var(--line);border-radius:8px;background:#fff;padding:0 10px;font-size:13px}
.act .opt input{height:28px;width:64px}
.link{border:0;background:none;color:var(--p2);font-weight:500;font-size:13px;padding:0;white-space:nowrap}
.link:hover{text-decoration:underline}

/* 面板 / 表格 */
.panel{background:var(--card);border:1px solid var(--line);border-radius:16px;margin-top:24px;overflow:hidden}
.ph{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:18px 24px;border-bottom:1px solid var(--line)}
.ph h2{margin:0;font-size:17px;font-weight:600;color:var(--ink)}
.ph .meta{color:var(--ink2);font-size:13px;display:flex;gap:16px;align-items:center;white-space:nowrap}
table{width:100%;border-collapse:collapse}
th{font-size:12.5px;color:var(--ink3);font-weight:500;text-align:left;padding:12px 20px;background:#FCFBFF;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:16px 20px;border-bottom:1px solid var(--line);vertical-align:middle;color:var(--ink)}
tbody tr:last-child td{border-bottom:0}
.ct{table-layout:fixed}
.ct td div{white-space:normal;overflow-wrap:anywhere;line-height:1.55;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ct td div.proto{display:flex;-webkit-line-clamp:unset}
.ct td.mono{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mono{font-family:var(--mono);font-size:13px}
.sub{color:var(--ink3);font-size:12.5px}
.empty{padding:40px 20px;text-align:center;color:var(--ink3)}
.tag{white-space:nowrap;display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:600;border-radius:999px;height:26px;padding:0 11px;line-height:1}
.t-ok{background:var(--okbg);color:var(--ok)} .t-warn{background:var(--warnbg);color:var(--warn)}
.t-no,.t-bad{background:var(--badbg);color:var(--bad)} .t-fail{background:var(--failbg);color:var(--fail)}
.t-p{background:var(--pl);color:var(--p3)} .t-bl{background:#FCEBFA;color:var(--mag)} .t-g{background:#F6F5FA;color:var(--ink2)} .t-pend{background:var(--pl);color:var(--p2)}
.proto{display:flex;gap:6px;flex-wrap:nowrap}
.proto span{white-space:nowrap;font-size:12px;border-radius:7px;height:26px;display:inline-flex;align-items:center;padding:0 8px;border:1px solid var(--line);color:var(--ink3);font-family:var(--mono)}
.proto .y{border-color:#CDEFD9;background:var(--okbg);color:var(--ok)}
.proto .n{border-color:#F8D3D5;background:var(--badbg);color:var(--bad)}
tr.pending td{color:var(--ink3)}
@keyframes pulse{50%{opacity:.35}}
.busy-dot{animation:pulse 1.1s ease-in-out infinite}
tr.dt td{background:#FCFBFF;padding:14px 24px 18px}
.dl{margin:0;padding:0;list-style:none;font-size:13px}
.dl li{display:flex;gap:16px;padding:4px 0;align-items:baseline}
.dl .k{color:var(--ink3);min-width:120px;font-family:var(--mono);overflow-wrap:anywhere}
.ok-t{color:var(--ok)} .fail-t{color:var(--bad)}

/* ── 网站解锁 ── */
.exit{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 20px;margin-top:24px;display:flex;align-items:center;gap:24px;font-size:13.5px;color:var(--ink)}
#ul-exit{display:flex;align-items:center;gap:28px;flex-wrap:wrap;min-width:0;flex:1}
#ul-exit>span{display:inline-flex;align-items:center;gap:8px;white-space:nowrap}
.exit b{color:var(--ink);font-family:var(--mono);font-weight:600}
.exit .k{color:var(--ink3);font-size:12.5px}
.exit .err{color:var(--bad);white-space:normal!important}
.exit .opt{margin-left:auto;flex:none}
.exit select#ul-proxy{max-width:240px;font-family:var(--mono)}
.toolbar{display:flex;align-items:center;justify-content:space-between;gap:24px;margin:24px 0 16px}
.chips{display:flex;gap:8px;flex-wrap:wrap;align-items:center;min-width:0}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;height:34px;padding:0 16px;font-size:13px;color:var(--ink2);white-space:nowrap}
.chip:hover{border-color:#DCD3FF;color:var(--ink)}
.chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.sum{display:flex;gap:8px;align-items:center;flex:none}
.sum button.tag{border:1px solid transparent;height:34px;padding:0 14px;font-size:13px;cursor:pointer}
.sum button.tag:hover{border-color:currentColor}
.sum button.tag:disabled{cursor:default;opacity:.55}
.sum button.tag:disabled:hover{border-color:transparent}
.sum .sep{width:1px;height:20px;background:var(--line);margin:0 6px}
.info-btn{border:0;background:none;color:var(--ink2);font-size:13px;display:inline-flex;align-items:center;gap:6px;padding:0 4px;white-space:nowrap;height:34px}
.info-btn:hover{color:var(--p2)}
.info-btn svg{width:16px;height:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-left:3px solid #DDD9E8;border-radius:14px;padding:18px 20px 16px;height:196px;display:flex;flex-direction:column;position:relative;transition:box-shadow .15s,border-color .15s;scroll-margin-top:96px}
.card:hover{box-shadow:0 8px 24px rgba(69,40,164,.10)}
.card.s-ok{border-left-color:var(--ok)} .card.s-warn{border-left-color:var(--warn)}
.card.s-no{border-left-color:var(--bad)} .card.s-fail{border-left-color:#B9B6C6} .card.s-busy{border-left-color:var(--p1)}
@keyframes flash{0%,100%{box-shadow:0 0 0 0 rgba(148,91,253,0)}30%{box-shadow:0 0 0 4px rgba(148,91,253,.35)}}
.card.hl{animation:flash 1.6s ease-out 1}
.c-top{display:flex;align-items:center;gap:12px}
.fav{width:34px;height:34px;border-radius:9px;background:var(--pl);display:flex;align-items:center;justify-content:center;font-weight:700;color:var(--p3);font-size:14px;flex:none}
.c-ttl{min-width:0;flex:1}
.c-name{font-weight:600;font-size:15px;line-height:1.35;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.c-grp{font-size:12px;line-height:1.4;color:var(--ink3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:flex;align-items:center;gap:6px}
.bl{flex:none;font-size:11px;font-weight:600;color:var(--mag);background:#FCEBFA;border-radius:5px;padding:0 6px;line-height:18px}
.redo{width:30px;height:30px;border-radius:8px;border:1px solid var(--line);background:#fff;color:var(--ink3);display:flex;align-items:center;justify-content:center;padding:0;flex:none}
.redo:hover{color:var(--p2);border-color:#DCD3FF}
.redo:disabled{opacity:.4;cursor:default}
.redo svg{width:14px;height:14px}
.s-busy .redo svg{animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.c-mid{display:flex;gap:6px;margin-top:16px;align-items:center;flex-wrap:wrap;max-height:26px;overflow:hidden}
.c-why{margin-top:12px;font-size:13px;color:var(--ink2);line-height:1.6;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.c-foot{margin-top:auto;display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--ink3);gap:8px;height:20px}

/* 详情抽屉 */
.drawer{position:fixed;top:68px;right:0;bottom:0;width:460px;max-width:100vw;background:#fff;border-left:1px solid var(--line);box-shadow:-12px 0 32px rgba(25,18,40,.08);padding:28px 28px 36px;overflow:auto;z-index:15}
.drawer h3{margin:0 0 4px;font-size:18px;display:flex;align-items:center;gap:10px}
.drawer .x{position:absolute;top:16px;right:16px;border:0;background:none;color:var(--ink3);font-size:20px;line-height:1}
.dsec{margin-top:18px}
.dsec h4{margin:0 0 8px;font-size:13px;color:var(--ink3);font-weight:500}
.kv{display:grid;grid-template-columns:96px 1fr;gap:8px 12px;font-size:13px;margin-top:16px}
.kv .k{color:var(--ink3)}
.dbox{background:#FCFBFF;border:1px solid var(--line);border-radius:12px;padding:14px 16px;font-size:13.5px;line-height:1.7;color:var(--ink);overflow-wrap:anywhere}
.dbox.adv{background:var(--pl);border-color:var(--pl2);color:var(--p3)}
.dbox.bln{background:#FCEBFA;border-color:#F6D3F2;color:#8A1384}
.dbox.tech{font-family:var(--mono);font-size:11.5px;color:var(--ink3)}
.step{display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px dashed var(--line);font-size:13px}
.step:last-child{border-bottom:0}
.step .tag{flex:none}
.dact{display:flex;gap:10px;margin-top:22px}

/* 弹窗:历史 / 管理 / 改密码 / 说明 */
.modal{position:fixed;inset:0;background:rgba(25,18,40,.32);display:flex;align-items:flex-start;justify-content:center;z-index:50;padding:70px 16px}
.modal-box{background:#fff;border-radius:18px;width:min(780px,100%);max-height:82vh;overflow:auto;padding:24px 28px 28px;box-shadow:0 16px 48px rgba(25,18,40,.2)}
.modal-box h3{font-size:14px;margin:18px 0 6px}
.modal-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;font-size:19px}
.hsec{margin-top:22px}
.hsec:first-child{margin-top:0}
.hsec h4{margin:0 0 10px;font-size:13px;font-weight:500;color:var(--ink3)}
.hlist{border:1px solid var(--line);border-radius:14px;overflow:hidden}
.hrow{display:grid;grid-template-columns:150px 1fr;gap:20px;padding:16px 20px;border-top:1px solid var(--line);align-items:start}
.hrow:first-child{border-top:0}
.hrow .tag{justify-self:start}
.hrow .d{font-size:13.5px;line-height:1.7;color:var(--ink)}
.hrow .a{margin-top:8px;font-size:13px;line-height:1.65;color:var(--p3);background:var(--pl);border-radius:8px;padding:8px 12px}
.hrow .a b{font-weight:600;margin-right:4px}
.mtable{width:100%;border-collapse:collapse;font-size:13px}
.mtable td,.mtable th{padding:9px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;background:none}
.mtable th{font-size:12px;color:var(--ink3);font-weight:600}
.mtable .adv{color:var(--p3)}
.mform{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
.mform input,.mform select{border:1px solid var(--line);background:#FCFBFF;border-radius:8px;padding:8px 10px;font-size:13px;min-width:0}
.mform input{flex:1 1 140px}
.msg{font-size:12.5px;margin-top:6px;color:var(--ink2)}
.msg.err{color:var(--bad)} .msg.ok{color:var(--ok)}
.hist-item{cursor:pointer} .hist-item:hover td{background:#FCFBFF}

@media (max-width:1100px){
  .input{grid-template-columns:1fr}
  .nav-in,main{padding-left:20px;padding-right:20px}
  .nav-in{gap:18px}
  .brand small{display:none}
}
</style>
</head>
<body>
<nav class="nav"><div class="nav-in">
  <div class="brand"><img src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMDI0IDEwMjQiPjxkZWZzPjxsaW5lYXJHcmFkaWVudCBpZD0iYmciIHgxPSIwIiB5MT0iMCIgeDI9IjEiIHkyPSIxIj48c3RvcCBvZmZzZXQ9IjAiIHN0b3AtY29sb3I9IiNGRkZGRkYiLz48c3RvcCBvZmZzZXQ9Ii41NSIgc3RvcC1jb2xvcj0iI0YwRURGRiIvPjxzdG9wIG9mZnNldD0iMSIgc3RvcC1jb2xvcj0iI0NEQzVGRiIvPjwvbGluZWFyR3JhZGllbnQ+PGxpbmVhckdyYWRpZW50IGlkPSJjIiB4MT0iMCIgeTE9IjAiIHgyPSIxIiB5Mj0iMSI+PHN0b3Agb2Zmc2V0PSIwIiBzdG9wLWNvbG9yPSIjOTQ1QkZEIi8+PHN0b3Agb2Zmc2V0PSIxIiBzdG9wLWNvbG9yPSIjNDUyOEQwIi8+PC9saW5lYXJHcmFkaWVudD48L2RlZnM+PHJlY3QgeD0iMTAwIiB5PSIxMDAiIHdpZHRoPSI4MjQiIGhlaWdodD0iODI0IiByeD0iMTg2IiBmaWxsPSJ1cmwoI2JnKSIgc3Ryb2tlPSIjRENEM0ZGIiBzdHJva2Utd2lkdGg9IjQiLz48Y2lyY2xlIGN4PSI1MTIiIGN5PSI1MTIiIHI9IjMzMCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjOTQ1QkZEIiBzdHJva2Utd2lkdGg9IjEwIiBvcGFjaXR5PSIuMjIiLz48Y2lyY2xlIGN4PSI1MTIiIGN5PSI1MTIiIHI9IjI2OCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjOTQ1QkZEIiBzdHJva2Utd2lkdGg9IjE0IiBvcGFjaXR5PSIuNDIiLz48Y2lyY2xlIGN4PSI1MTIiIGN5PSI1MTIiIHI9IjIwMCIgZmlsbD0idXJsKCNjKSIvPjxwYXRoIGQ9Ik0zOTIgNTIwaDU2bDM2LTk2IDU2IDE5MiAzNi05Nmg1NiIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjZmZmIiBzdHJva2Utd2lkdGg9IjM0IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz48Y2lyY2xlIGN4PSI3NDUiIGN5PSIzMDAiIHI9IjMwIiBmaWxsPSIjQzIxQkJBIi8+PC9zdmc+" alt="">代理测试台</div>
  <div class="tabs">
    <button class="tab on" type="button" data-t="conn">代理检测</button>
    <button class="tab" type="button" data-t="unlock">网站解锁</button>
  </div>
  <div class="nav-r">
    <button class="nl" id="btn-history" type="button">历史记录</button>
    <button class="nl" id="btn-admin" type="button" hidden>管理</button>
    <span class="user" id="me-box" hidden><span class="avatar" id="me-av"></span><span id="me-name"></span></span>
    <button class="nl" id="btn-passwd" type="button" hidden>改密码</button>
    <button class="nl" id="btn-logout" type="button" hidden>退出</button>
  </div>
</div></nav>

<main>
  <div class="hero"><h1 id="h-title">代理检测</h1><p id="h-sub"></p></div>

  <div class="input">
    <div class="fld"><label for="proxy-input">代理 / IP(一行一条,静态 IP 可只填 IP)</label>
      <textarea id="proxy-input" spellcheck="false"
        placeholder="203.0.113.10&#10;gate.example.com:7777:user123:pass12345&#10;http://user123:pass12345@gate.example.com:7777"></textarea></div>
    <div class="fld"><div class="lbl-row"><label for="opt-targets">指定网站(选填,一行一个)</label>
      <button class="link" id="btn-addsite" type="button">+ 加入网站解锁</button></div>
      <textarea id="opt-targets" spellcheck="false" placeholder="https://www.tiktok.com"></textarea></div>
    <div class="act">
      <div class="opt"><label for="opt-timeout" style="color:var(--ink);font-weight:500">超时</label><input id="opt-timeout" type="number" value="10" min="2" max="60"> 秒</div>
      <button class="btn pri" id="btn-test" type="button">开始检测</button>
      <button class="btn sec" id="btn-myip" type="button">查本机出口 IP</button>
    </div>
  </div>

  <!-- ═══ 代理检测:连通性 + 归属地 ═══ -->
  <section id="v-conn">
    <div class="panel">
      <div class="ph"><h2>检测结果</h2><span class="meta"><span id="conn-sum">填好代理后点「开始检测」</span><button class="link" id="btn-copy" type="button" hidden>复制结果</button></span></div>
      <table class="ct">
        <colgroup><col style="width:14%"><col style="width:96px"><col style="width:262px"><col><col style="width:17%"><col style="width:124px"><col style="width:76px"><col style="width:68px"></colgroup>
        <thead><tr><th>代理</th><th>状态</th><th>协议</th><th>出口 IP / 归属地</th><th>运营商 / 时区</th><th>账密来源</th><th>耗时</th><th></th></tr></thead>
        <tbody id="conn-body"><tr><td colspan="8" class="empty">还没有结果</td></tr></tbody>
      </table>
    </div>
    <div class="panel" id="myip-panel" hidden>
      <div class="ph"><h2>本机出口 IP</h2><span class="meta">这台电脑(或测试台服务器)当前的出口</span></div>
      <table><tbody id="myip-body"></tbody></table>
    </div>
  </section>

  <!-- ═══ 网站解锁 ═══ -->
  <section id="v-unlock" hidden>
    <div class="exit">
      <span id="ul-exit">在上方填代理,点「开始解锁测试」。</span>
      <span class="opt">
        <select id="ul-proxy" aria-label="测试哪条代理"></select>
        <select id="ul-mode" aria-label="协议"><option value="auto">自动选协议</option><option value="http">HTTP 隧道</option><option value="socks5">SOCKS5</option></select>
        <button class="btn sec sm" id="ul-run" type="button">重新测试</button>
      </span>
    </div>
    <div class="toolbar"><div class="chips" id="ul-chips"></div><div class="sum" id="ul-sum"></div></div>
    <div class="grid" id="ul-grid"></div>
  </section>
</main>

<aside class="drawer" id="drawer" hidden></aside>

<div id="modal" class="modal" hidden>
  <div class="modal-box">
    <div class="modal-head"><b id="modal-title"></b><button id="modal-close" class="link" type="button">关闭</button></div>
    <div id="modal-body"></div>
  </div>
</div>

<script>
(function () {
"use strict";
var $ = function (id) { return document.getElementById(id); };
var STEP_LABEL = { dns: "解析", tcp: "连接", http: "HTTP", https: "HTTPS", socks5: "SOCKS5", web: "访问" };
var VERDICT = { "full": "可用", "partial": "部分可用", "exit-blocked": "网站不通",
                "auth-fail": "认证失败", "fail": "不可用", "bad-input": "格式错误" };
var VERDICT_CLS = { "full": "t-ok", "partial": "t-warn", "exit-blocked": "t-warn",
                    "auth-fail": "t-bad", "fail": "t-bad", "bad-input": "t-fail" };
var AUTH_TXT = { "默认账密": "默认账密" };
var AUTH_LONG = { "默认账密": "只填了 IP,用的是环境变量里配置的默认端口和账密" };
var TITLES = {
  conn: ["代理检测", "HTTP / HTTPS / SOCKS5 能否连通,以及出口 IP 的国家、城市、运营商", "开始检测"],
  unlock: ["网站解锁", "代理能否打开客户常用网站:能否访问、地区限制、人机验证", "开始解锁测试"]
};

/* ── 小工具 ── */
function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}
function fmtMs(ms) {
  if (ms === null || ms === undefined) return "";
  return ms >= 1000 ? (ms / 1000).toFixed(1) + "s" : Math.round(ms) + "ms";
}
function maskLine(line) {
  if (line.indexOf("://") === -1) {
    var parts = line.split(":");
    if (parts.length >= 4 && /^\d+$/.test(parts[1])) return parts.slice(0, 3).join(":") + ":••••";
  }
  var at = line.lastIndexOf("@");
  if (at > -1) {
    var head = line.slice(0, at);
    var start = head.indexOf("://") > -1 ? head.indexOf("://") + 3 : 0;
    var firstColon = head.indexOf(":", start);
    if (firstColon > -1) return head.slice(0, firstColon + 1) + "••••" + line.slice(at);
  }
  return line;
}
var NOT_JSON = "服务器这次没有返回正常结果";
function api(path, body, _retried) {
  return fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
  }).then(function (r) {
    return r.text().then(function (txt) {
      var data;
      try { data = JSON.parse(txt); } catch (e) { data = null; }
      if (data === null) {
        /* 网关错误页 / 空回复:多半是服务器一下子忙不过来,自动再试一次 */
        if (!_retried) return new Promise(function (ok) { setTimeout(ok, 1500); }).then(function () { return api(path, body, true); });
        throw new Error(NOT_JSON + "(HTTP " + r.status + ")。原因:服务器同时处理的请求太多,或刚好在重启 / 网络抖动,这次结果没传回来。办法:重测一次;一直这样请联系管理员。");
      }
      if (r.status === 401 && data && data.login) { location.reload(); }
      if (!r.ok) throw new Error((data && data.error) || ("HTTP " + r.status));
      return data;
    });
  }, function () {
    throw new Error("连不上测试台服务器。原因:你的网络断了,或服务器没在运行。办法:检查网络后刷新页面;仍打不开请联系管理员。");
  });
}
function getJSON(url) { return fetch(url).then(function (r) { return r.json(); }); }
function pool(items, n, fn) {
  var i = 0;
  function worker() {
    if (i >= items.length) return Promise.resolve();
    var idx = i++;
    return fn(items[idx], idx).then(worker);
  }
  var ws = [];
  for (var k = 0; k < Math.min(n, items.length); k++) ws.push(worker());
  return Promise.all(ws);
}
function flag(code) {
  if (!/^[A-Z]{2}$/.test(code || "") || code === "TW") return "";
  return String.fromCodePoint(0x1F1E6 + code.charCodeAt(0) - 65, 0x1F1E6 + code.charCodeAt(1) - 65) + " ";
}
function copyText(text, btn, label) {
  function flash() { btn.textContent = "已复制"; setTimeout(function () { btn.textContent = label; }, 1500); }
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(flash, flash);
  else { var ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); flash(); }
}
function inputLines() {
  return $("proxy-input").value.split("\n").map(function (s) { return s.trim(); }).filter(Boolean).slice(0, 200);
}
function targetsList() {
  return $("opt-targets").value.split("\n").map(function (s) { return s.trim(); }).filter(Boolean);
}
function hostOf(line) {
  var s = line.trim().replace(/^[a-z0-9]+:\/\//i, "").replace(/\/+$/, "");
  var at = s.lastIndexOf("@");
  if (at > -1) return s.slice(at + 1).split(":")[0];
  return s.split(":")[0];
}

/* ── 导航 ── */
var TAB = "conn";
function showTab(t) {
  TAB = t;
  document.querySelectorAll(".tab").forEach(function (b) { b.classList.toggle("on", b.dataset.t === t); });
  $("v-conn").hidden = t !== "conn";
  $("v-unlock").hidden = t !== "unlock";
  $("h-title").textContent = TITLES[t][0];
  $("h-sub").textContent = TITLES[t][1];
  if (!$("btn-test").disabled) $("btn-test").textContent = TITLES[t][2];
  $("btn-myip").hidden = t !== "conn";
  if (t !== "unlock") closeDrawer();
  if (t === "unlock") { loadUnlockSites().then(function () { syncProxyOptions(); renderUnlock(); }); }
}
document.querySelectorAll(".tab").forEach(function (b) {
  b.addEventListener("click", function () { showTab(b.dataset.t); });
});

/* ══════════ 代理检测 ══════════ */
var CONN = [];   /* 每行:{input, data(连通性结果), geo(归属地), open} */
var IPDATA = []; /* 本机出口 */

function protoCell(data) {
  var box = el("div", "proto");
  ["http", "https", "socks5"].forEach(function (k) {
    var s = (data && data.steps || []).filter(function (x) { return x.key === k; })[0];
    var sp = el("span", s ? (s.ok ? "y" : "n") : "", (s ? (s.ok ? "✓ " : "✕ ") : "· ") + STEP_LABEL[k]);
    if (s) sp.title = s.ok ? fmtMs(s.ms) : (s.error || "不通");
    box.appendChild(sp);
  });
  return box;
}

function geoLines(row) {
  var d = row.data || {}, g = row.geo || {}, ex = d.exit || {};
  var ip = ex.ip || g.ip || "";
  var cn = g.loc_cn || ex.cn || "", en = g.loc_en || ex.en || "";
  var code = g.country || "";
  var out = [];
  if (ip) out.push(["mono", ip]);
  else if (d.verdict) out.push(["mono", hostOf(row.input)]);
  if (cn) out.push(["", flag(code) + cn]);
  if (!ex.ip && d.verdict && d.verdict !== "full" && d.verdict !== "partial") out.push(["sub", "代理服务器所在地(未连通)"]);
  else if (en) out.push(["sub", en]);
  return out;
}

function connRow(row, i) {
  var d = row.data, tr = el("tr", d ? "" : "pending");
  var tdP = el("td", "mono", maskLine(row.input)); tdP.title = maskLine(row.input); tr.appendChild(tdP);
  var tdS = el("td");
  if (d) tdS.appendChild(el("span", "tag " + (VERDICT_CLS[d.verdict] || "t-fail"), "● " + (VERDICT[d.verdict] || d.verdict)));
  else tdS.appendChild(el("span", "tag t-pend busy-dot", "● 检测中"));
  tr.appendChild(tdS);
  var tdPr = el("td"); tdPr.appendChild(protoCell(d)); tr.appendChild(tdPr);
  var tdG = el("td");
  geoLines(row).forEach(function (x) { tdG.appendChild(el("div", x[0], x[1])); });
  if (d && !tdG.childNodes.length) tdG.appendChild(el("div", "sub", "—"));
  tr.appendChild(tdG);
  var tdO = el("td"), g = row.geo || {}, ex = (d && d.exit) || {};
  var org = g.org || g.as_name || g.asn || ex.org || "";
  if (d && !ex.ip && d.verdict !== "full" && d.verdict !== "partial") {
    var w = el("div", "sub", d.verdict_text || ""); w.style.whiteSpace = "normal"; tdO.appendChild(w);
  } else {
    if (org) tdO.appendChild(el("div", null, org));
    if (g.timezone) tdO.appendChild(el("div", "sub", g.timezone));
  }
  tr.appendChild(tdO);
  var tdA = el("td");
  if (d && d.auth_source) tdA.appendChild(el("span", "tag t-p", AUTH_TXT[d.auth_source] || d.auth_source));
  else tdA.textContent = d ? "—" : "";
  tr.appendChild(tdA);
  tr.appendChild(el("td", "mono", d ? fmtMs(d.total_ms) : ""));
  var tdD = el("td");
  if (d) {
    var b = el("button", "link", row.open ? "收起" : "详情"); b.type = "button";
    b.addEventListener("click", function () { row.open = !row.open; renderConn(); });
    tdD.appendChild(b);
  }
  tr.appendChild(tdD);
  return tr;
}

function connDetail(row) {
  var d = row.data, tr = el("tr", "dt"), td = el("td"); td.colSpan = 8;
  var list = el("ul", "dl");
  function li(k, v, cls) { var x = el("li"); x.appendChild(el("span", "k", k)); x.appendChild(el("span", cls || null, v)); list.appendChild(x); }
  (d.steps || []).forEach(function (s) {
    var x = el("li");
    x.appendChild(el("span", "k", STEP_LABEL[s.key] || s.key));
    x.appendChild(el("span", s.skipped ? "sub" : (s.ok ? "ok-t" : "fail-t"), s.skipped ? "未测试" : (s.ok ? "成功" : "失败")));
    if (s.ms !== undefined && s.ms !== null) x.appendChild(el("span", "sub", fmtMs(s.ms)));
    if (s.info) x.appendChild(el("span", null, s.info));
    if (s.error) x.appendChild(el("span", "fail-t", s.error));
    list.appendChild(x);
  });
  (d.targets || []).forEach(function (t) {
    var x = el("li");
    x.appendChild(el("span", "k", t.url));
    x.appendChild(el("span", t.ok ? "ok-t" : "fail-t", t.ok ? "HTTP " + t.status : "失败"));
    if (t.ms !== undefined && t.ms !== null) x.appendChild(el("span", "sub", fmtMs(t.ms)));
    if (t.error) x.appendChild(el("span", "fail-t", t.error));
    list.appendChild(x);
  });
  if (d.auth_source) li("账密来源", (AUTH_LONG[d.auth_source] || d.auth_source) + (d.proxy ? "(" + d.proxy + ")" : ""));
  var g = row.geo || {};
  if (g.loc_cn || g.loc_en) li("归属地", [g.loc_cn, g.loc_en].filter(Boolean).join(" / "));
  if (g.org || g.as_name) li("运营商", g.org || g.as_name);
  li("结论", d.verdict_text || VERDICT[d.verdict] || "");
  td.appendChild(list); tr.appendChild(td);
  return tr;
}

function renderConn() {
  var tb = $("conn-body"); tb.textContent = "";
  if (!CONN.length) { var e = el("tr"), td = el("td", "empty", "还没有结果"); td.colSpan = 8; e.appendChild(td); tb.appendChild(e); }
  CONN.forEach(function (row, i) {
    tb.appendChild(connRow(row, i));
    if (row.open && row.data) tb.appendChild(connDetail(row));
  });
  var done = CONN.filter(function (r) { return r.data; }).length;
  var okN = CONN.filter(function (r) { return r.data && (r.data.verdict === "full" || r.data.verdict === "partial"); }).length;
  $("conn-sum").textContent = !CONN.length ? "填好代理后点「开始检测」"
    : (done < CONN.length ? "已完成 " + done + " / " + CONN.length : "共 " + CONN.length + " 条 · 可用 " + okN + " 条");
  $("btn-copy").hidden = !done;
}

function runConn(lines) {
  CONN = lines.map(function (l) { return { input: l, data: null, geo: null, open: false }; });
  renderConn();
  return pool(CONN, 4, function (row) {
    return api("/api/test", { proxy: row.input, timeout: +$("opt-timeout").value || 10, targets: targetsList() })
      .catch(function (e) {
        return { input: row.input, verdict: "fail", verdict_text: "请求失败:" + ((e && e.message) || e), steps: [], targets: [] };
      })
      .then(function (d) {
        row.data = d; renderConn();
        /* 归属地:有出口 IP 查出口,没连通就查代理服务器本身 */
        var ip = (d.exit && d.exit.ip) || (d.verdict !== "bad-input" ? hostOf(row.input) : "");
        if (!ip) return;
        return api("/api/ipinfo", { ip: ip }).then(function (g) { if (!g.error) { row.geo = g; renderConn(); } }, function () {});
      });
  });
}

$("btn-copy").addEventListener("click", function () {
  var rows = [["代理", "状态", "HTTP", "HTTPS", "SOCKS5", "出口IP", "归属地", "运营商", "时区", "账密来源", "总耗时", "说明"].join("\t")];
  CONN.forEach(function (r) {
    var d = r.data; if (!d) return;
    var p = {}; (d.steps || []).forEach(function (s) { p[s.key] = s.ok ? "通" : "不通"; });
    var g = r.geo || {}, e = d.exit || {};
    rows.push([r.input, VERDICT[d.verdict] || d.verdict, p.http || "", p.https || "", p.socks5 || "", e.ip || "",
      [g.loc_cn || e.cn, g.loc_en || e.en].filter(Boolean).join(" "), g.org || e.org || "", g.timezone || "",
      d.auth_source || "", fmtMs(d.total_ms), d.verdict_text || ""].join("\t"));
  });
  copyText(rows.join("\n"), $("btn-copy"), "复制结果");
});

function renderMyIp() {
  var tb = $("myip-body"); tb.textContent = "";
  $("myip-panel").hidden = !IPDATA.length;
  IPDATA.forEach(function (g) {
    var tr = el("tr");
    if (g === "pending") { var td = el("td", "sub busy-dot", "查询中…"); tr.appendChild(td); tb.appendChild(tr); return; }
    if (g.error) { tr.appendChild(el("td", "fail-t", g.error)); tb.appendChild(tr); return; }
    var a = el("td", "mono", g.ip || ""); a.style.width = "200px"; tr.appendChild(a);
    tr.appendChild(el("td", null, flag(g.country) + (g.loc_cn || "")));
    tr.appendChild(el("td", "sub", g.loc_en || ""));
    tr.appendChild(el("td", null, g.org || g.as_name || ""));
    tr.appendChild(el("td", "sub", g.timezone || ""));
    tb.appendChild(tr);
  });
}
$("btn-myip").addEventListener("click", function () {
  var b = $("btn-myip"); if (b.disabled) return;
  b.disabled = true; IPDATA = ["pending"]; renderMyIp();
  api("/api/ipinfo", { ip: "" }).catch(function (e) { return { error: e.message }; })
    .then(function (g) { IPDATA = [g]; renderMyIp(); b.disabled = false; });
});

/* ══════════ 网站解锁 ══════════ */
var UL = { sites: null, cache: {}, kinds: [], filter: "全部", drawer: null };
var UL_CONCURRENCY = 9;  /* 每个站点同时走 HTTP 和 SOCKS5,再高会把单条代理打满 */
var UL_ICON = { ok: "✓", no: "✕", warn: "!", fail: "?" };
var REDO_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v5h-5"/></svg>';
var COUNTRY_NAME = { US: "美国", GB: "英国", DE: "德国", FR: "法国", JP: "日本", KR: "韩国", SG: "新加坡",
  HK: "香港", TW: "台湾", CN: "中国", IN: "印度", BR: "巴西", CA: "加拿大", AU: "澳大利亚", NL: "荷兰",
  RU: "俄罗斯", ID: "印尼", PH: "菲律宾", VN: "越南", TH: "泰国", MY: "马来西亚", MX: "墨西哥",
  CO: "哥伦比亚", IT: "意大利", ES: "西班牙", TR: "土耳其", AE: "阿联酋", PK: "巴基斯坦", NG: "尼日利亚", BD: "孟加拉国" };

function loadUnlockSites(force) {
  if (UL.sites && !force) return Promise.resolve(UL.sites);
  return getJSON("/api/unlock/sites").then(function (d) {
    UL.sites = d.sites || []; UL.kinds = d.kinds || [];
    return UL.sites;
  });
}
function siteById(id) { return (UL.sites || []).filter(function (s) { return s.id === id; })[0]; }

function curKey() { return $("ul-proxy").value + "|" + $("ul-mode").value; }
function entry(key) {
  if (!UL.cache[key]) {
    var i = key.lastIndexOf("|");
    UL.cache[key] = { proxy: key.slice(0, i), mode: key.slice(i + 1), results: {}, busy: {}, exit: null, exitErr: "" };
  }
  var en = UL.cache[key]; en.busy = en.busy || {};
  return en;
}
function modesFor(mode) { return mode === "auto" ? ["http", "socks5"] : [mode]; }

function syncProxyOptions() {
  var lines = inputLines(), sel = $("ul-proxy"), prev = sel.value;
  var have = Array.prototype.map.call(sel.options, function (o) { return o.value; });
  if (lines.length && lines.join("\n") !== have.join("\n")) {
    sel.textContent = "";
    lines.slice(0, 50).forEach(function (l) { var o = el("option", null, maskLine(l)); o.value = l; sel.appendChild(o); });
    if (prev && lines.indexOf(prev) > -1) sel.value = prev;
  }
}

function renderExit() {
  var box = $("ul-exit"); box.textContent = "";
  if (!$("ul-proxy").value) { box.textContent = "在上方填代理,点「开始解锁测试」。"; return; }
  var en = entry(curKey());
  var a = el("span"); a.appendChild(el("span", "k", "测试代理")); a.appendChild(el("b", null, maskLine(en.proxy))); box.appendChild(a);
  if (en.exitErr) { box.appendChild(el("span", "err", "代理连不上:" + en.exitErr)); return; }
  if (!en.exit) { box.appendChild(el("span", "sub", en.started ? "正在获取出口 IP…" : "这条代理还没测试")); return; }
  var e = en.exit;
  var b = el("span"); b.appendChild(el("span", "k", "出口"));
  b.appendChild(el("span", null, flag(e.country) + [(COUNTRY_NAME[e.country] || e.country || ""), e.city].filter(Boolean).join(" ")));
  box.appendChild(b);
  if (e.org) { var o = el("span"); o.appendChild(el("span", "k", "运营商")); o.appendChild(el("span", null, e.org)); box.appendChild(o); }
  if (en.modes) { var c = el("span"); c.appendChild(el("span", "k", "可用协议")); c.appendChild(el("span", null, en.modes.map(function (m) { return m.toUpperCase(); }).join(" / "))); box.appendChild(c); }
}

function statusOf(r) { return r && r.status ? (r.status === "no" ? "no" : r.status) : ""; }

var INFO_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.6v.4"/></svg>';
function renderChips() {
  var box = $("ul-chips"); box.textContent = "";
  var groups = ["全部"];
  (UL.sites || []).forEach(function (s) { if (groups.indexOf(s.group) < 0) groups.push(s.group); });
  groups.forEach(function (g) {
    var c = el("button", "chip" + (UL.filter === g ? " on" : ""), g);
    c.type = "button";
    c.addEventListener("click", function () { UL.filter = g; renderUnlock(); });
    box.appendChild(c);
  });
  var en = $("ul-proxy").value ? entry(curKey()) : null, cnt = { ok: 0, warn: 0, no: 0, fail: 0 };
  if (en) Object.keys(en.results).forEach(function (k) { var st = statusOf(en.results[k]); if (cnt[st] !== undefined) cnt[st]++; });
  var sum = $("ul-sum"); sum.textContent = "";
  [["ok", "t-ok", "支持"], ["warn", "t-warn", "需验证"], ["no", "t-bad", "不支持"], ["fail", "t-fail", "失败"]].forEach(function (x) {
    var b = el("button", "tag " + x[1], x[2] + " " + cnt[x[0]]); b.type = "button";
    b.disabled = !cnt[x[0]];
    b.title = cnt[x[0]] ? "定位到" + x[2] + "的网站" : "";
    b.addEventListener("click", function () { locateStatus(x[0]); });
    sum.appendChild(b);
  });
  sum.appendChild(el("span", "sep"));
  var hp = el("button", "info-btn"); hp.type = "button"; hp.innerHTML = INFO_SVG; hp.appendChild(document.createTextNode("结果说明"));
  hp.addEventListener("click", showHelp);
  sum.appendChild(hp);
}

/* 点状态数字:切到「全部」,滚到第一个该状态的网站,并让同状态的卡片闪一下 */
function locateStatus(st) {
  if (UL.filter !== "全部") { UL.filter = "全部"; renderUnlock(); }
  var cards = Array.prototype.slice.call(document.querySelectorAll("#ul-grid .card.s-" + st));
  if (!cards.length) return;
  cards[0].scrollIntoView({ behavior: "smooth", block: "start" });
  cards.forEach(function (c) { c.classList.remove("hl"); void c.offsetWidth; c.classList.add("hl"); });
}

function card(s, en) {
  var r = en ? en.results[s.id] : null, busy = en && en.busy[s.id];
  var st = busy ? "busy" : statusOf(r);
  var c = el("div", "card" + (st ? " s-" + st : ""));
  c.dataset.site = s.id;
  var top = el("div", "c-top");
  top.appendChild(el("span", "fav", (s.name || "?").charAt(0).toUpperCase()));
  var nm = el("div", "c-ttl");
  nm.appendChild(el("div", "c-name", s.name));
  var grp = el("div", "c-grp");
  grp.appendChild(el("span", null, s.custom ? "手动添加 · " + (s.added_by || "") : s.group));
  nm.appendChild(grp);
  top.appendChild(nm);
  var redo = el("button", "redo"); redo.type = "button"; redo.title = "重新测试"; redo.innerHTML = REDO_SVG;
  redo.disabled = !!busy || !$("ul-proxy").value;
  redo.addEventListener("click", function () { runSite(curKey(), s.id); });
  top.appendChild(redo);
  c.appendChild(top);

  var mid = el("div", "c-mid");
  var exitCC = en && en.exit && en.exit.country;
  if (busy) mid.appendChild(el("span", "tag t-pend busy-dot", "测试中"));
  else if (!r) mid.appendChild(el("span", "tag t-g", "未测试"));
  else {
    mid.appendChild(el("span", "tag t-" + (st === "no" ? "bad" : st), (UL_ICON[r.status] || "?") + " " + (r.label || "")));
    /* 只有网站识别的地区和出口 IP 国家不一样时才标出来(一样就不重复显示) */
    var rg = normRegion(r.region);
    if (rg && exitCC && rg !== exitCC) { var t = el("span", "tag t-p", "网站识别:" + rg); t.title = "网站认为你在 " + rg + ",出口 IP 在 " + exitCC; mid.appendChild(t); }
  }
  c.appendChild(mid);
  var why = r ? (r.detail || "") : "";
  if (r && r.status === "ok") why = okText(r);
  c.appendChild(el("div", "c-why", why));
  var foot = el("div", "c-foot");
  foot.appendChild(el("span", null, r && !busy ? fmtMs(r.ms) + (r.at ? " · " + r.at.slice(11, 16) : "") : ""));
  /* 成功的不显示「原因与办法」;手动添加的网站(要能删除)才留「详情」 */
  var linkTxt = !r ? (s.custom ? "详情 ›" : "")
              : r.status === "ok" ? (s.custom ? "详情 ›" : "")
              : "原因与办法 ›";
  if (linkTxt) {
    var more = el("button", "link", linkTxt); more.type = "button";
    more.addEventListener("click", function () { openDrawer(s.id); });
    foot.appendChild(more);
  }
  c.appendChild(foot);
  return c;
}
var REGION_ALIAS = { USA: "US", UK: "GB" };
function normRegion(x) { x = String(x || "").toUpperCase(); return REGION_ALIAS[x] || x; }
function okText(r) {
  var d = r.detail || "正常打开";
  if (/^按出口地区判断/.test(d)) return "出口地区在服务范围内" + (r.region ? "(" + normRegion(r.region) + ")" : "");
  return d.replace(/^正常打开\(HTTP 200\)$/, "正常打开");
}

function renderUnlock() {
  if (!UL.sites) return;
  renderExit(); renderChips();
  var grid = $("ul-grid"); grid.textContent = "";
  var en = $("ul-proxy").value ? entry(curKey()) : null;
  UL.sites.forEach(function (s) {
    if (UL.filter !== "全部" && s.group !== UL.filter) return;
    grid.appendChild(card(s, en));
  });
  if (!grid.childNodes.length) grid.appendChild(el("div", "empty", "没有网站"));
  if (UL.drawer) openDrawer(UL.drawer, true);
}

/* 详情抽屉 */
function closeDrawer() { UL.drawer = null; $("drawer").hidden = true; }
function openDrawer(id, keep) {
  var s = siteById(id); if (!s) return closeDrawer();
  UL.drawer = id;
  var en = $("ul-proxy").value ? entry(curKey()) : null, r = en ? en.results[id] : null;
  var d = $("drawer"); d.textContent = ""; d.hidden = false;
  var x = el("button", "x", "×"); x.type = "button"; x.title = "关闭"; x.addEventListener("click", closeDrawer); d.appendChild(x);
  var h = el("h3"); h.appendChild(el("span", "fav", s.name.charAt(0).toUpperCase())); h.appendChild(document.createTextNode(s.name));
  if (r) h.appendChild(el("span", "tag t-" + (r.status === "no" ? "bad" : r.status), r.label || ""));
  d.appendChild(h);
  d.appendChild(el("div", "sub", r ? "代理 " + maskLine(en.proxy) + (r.at ? " · " + r.at : "") + (r.ms ? " · " + fmtMs(r.ms) : "")
                                  : (s.custom ? "手动添加 · " + (s.added_by || "") + " · " : s.group + " · ") + "还没测试"));
  function sec(title, text, cls) {
    if (!text) return;
    var w = el("div", "dsec"); w.appendChild(el("h4", null, title)); w.appendChild(el("div", "dbox" + (cls ? " " + cls : ""), text)); d.appendChild(w);
  }
  if (r) {
    var kv = el("div", "kv");
    function kvRow(k, v) { if (!v) return; kv.appendChild(el("span", "k", k)); kv.appendChild(el("span", null, v)); }
    kvRow("出口 IP 国家", en.exit && en.exit.country ? flag(en.exit.country) + (COUNTRY_NAME[en.exit.country] || en.exit.country) : "");
    kvRow("网站识别地区", r.region ? normRegion(r.region) : "这个网站不返回地区信息");
    if (r.via)
      kvRow("本次协议", r.via.toUpperCase() + (en.mode === "auto" ? "(自动模式:两种协议同时测,用先返回结果的那个)" : ""));
    d.appendChild(kv);
    sec(r.status === "ok" ? "结果" : "原因", r.status === "ok" ? okText(r) : (r.detail || ""));
    sec("办法", r.advice, "adv");
    sec("技术细节", r.tech, "tech");
  }
  var act = el("div", "dact");
  if ($("ul-proxy").value) {
    var b = el("button", "btn sec sm", "重新测试"); b.type = "button";
    b.disabled = !!(en && en.busy[id]);
    b.addEventListener("click", function () { runSite(curKey(), id); });
    act.appendChild(b);
  }
  if (s.custom && ME.user && (ME.user.is_admin || ME.user.username === s.added_by)) {
    var del = el("button", "btn sm", "从常用网站删除"); del.type = "button";
    del.style.background = "var(--badbg)"; del.style.color = "var(--bad)";
    del.addEventListener("click", function () { deleteSite(s); });
    act.appendChild(del);
  }
  if (act.childNodes.length) d.appendChild(act);
}

function runSite(key, id) {
  var en = entry(key);
  en.busy[id] = true;
  if (key === curKey()) renderUnlock();
  return api("/api/unlock/site", { proxy: en.proxy, modes: modesFor(en.mode), site: id, timeout: +$("opt-timeout").value || 10 })
    .catch(function (e) {
      var m = (e && e.message) || String(e), i = m.indexOf("办法:");
      return { site: id, status: "fail", label: "没拿到结果", detail: i > 0 ? m.slice(0, i).replace(/。$/, "") : m, advice: i > 0 ? m.slice(i + 3) : "" };
    })
    .then(function (r) {
      delete en.busy[id];
      en.results[id] = r;
      if (key === curKey()) renderUnlock();
    });
}

function runUnlockAll(key) {
  var en = entry(key);
  en.results = {}; en.busy = {}; en.exit = null; en.exitErr = ""; en.started = true;
  renderUnlock();
  var prep = api("/api/unlock/prepare", { proxy: en.proxy, mode: en.mode }).then(function (d) {
    if (d.ok) { en.exit = d.exit; en.modes = d.modes; } else en.exitErr = d.error || "未知错误";
  }, function (e) { en.exitErr = (e && e.message) || String(e); }).then(function () { if (key === curKey()) renderExit(); });
  return loadUnlockSites().then(function (sites) {
    return Promise.all([prep, pool(sites, UL_CONCURRENCY, function (s) { return runSite(key, s.id); })]);
  });
}

function runUnlockButton() {
  var btn = $("ul-run");
  if (!$("ul-proxy").value || btn.disabled) return Promise.resolve();
  btn.disabled = true; btn.textContent = "测试中";
  return runUnlockAll(curKey()).catch(function () {}).then(function () {
    btn.disabled = false; btn.textContent = "重新测试";
  });
}
$("ul-run").addEventListener("click", function () { runUnlockButton().then(function () { saveHistory(); }); });
$("ul-proxy").addEventListener("change", function () { closeDrawer(); renderUnlock(); });
$("ul-mode").addEventListener("change", function () { closeDrawer(); renderUnlock(); });

function showHelp() {
  var box = el("div");
  function section(title, rows) {
    var w = el("div", "hsec"); w.appendChild(el("h4", null, title));
    var list = el("div", "hlist");
    rows.forEach(function (r) {
      var row = el("div", "hrow");
      row.appendChild(el("span", "tag " + r[0], r[1]));
      var d = el("div"); d.appendChild(el("div", "d", r[2]));
      if (r[3]) { var a = el("div", "a"); a.appendChild(el("b", null, "建议")); a.appendChild(document.createTextNode(r[3])); d.appendChild(a); }
      row.appendChild(d); list.appendChild(row);
    });
    w.appendChild(list); box.appendChild(w);
  }
  section("测试结果", [
    ["t-ok", "✓ 支持", "网站能正常打开。能识别地区的网站,地区也在服务范围内。", ""],
    ["t-warn", "! 需验证", "网站能连上,但风控要求这个 IP 先过人机验证(验证码 / Cloudflare)。客户用浏览器时会弹验证,用脚本或自动化会被卡住。", "换更干净的 IP,可以少弹或不弹验证。"],
    ["t-bad", "✕ 不支持", "网站认出了这个出口 IP 并拒绝访问:IP 被拉黑、被识别为代理 / 机房 IP,或该国家不在服务范围内。HTTP 和 SOCKS5 用的是同一个出口 IP,结果一样。", "换一个 IP 或换一个国家再测。"],
    ["t-fail", "? 失败", "没能拿到网站的响应,一般是代理本身连不上或超时,和网站是否支持无关。", "先到「代理检测」确认代理可用,再重测。"]
  ]);
  var reasons = UL.kinds.map(function (k) { return ["t-g", k.label, k.reason.replace("{t}", "N"), k.advice]; });
  reasons.push(["t-g", "没拿到结果", "测试台服务器这次没把结果传回来:同时测的请求太多、服务器正在重启,或网络抖动。和被测的代理、网站无关。", "重测一次;一直这样请联系管理员。"]);
  section("失败原因", reasons);
  section("标签含义", [
    ["t-p", "网站识别:XX", "网站认定的访问地区和出口 IP 的国家不一样时才显示。一样就不重复显示。只有 Claude、ChatGPT、Gemini、YouTube、X、Netflix 等少数网站会返回地区信息。", ""]
  ]);
  openModal("结果说明", box);
}

/* ── 常用网站:从「指定网站」加入 / 删除(所有人共享) ── */
function reloadSites() { return loadUnlockSites(true).then(renderUnlock); }
$("btn-addsite").addEventListener("click", function () {
  var urls = targetsList();
  if (!urls.length) { $("opt-targets").focus(); alert("先在「指定网站」里填网址(一行一个),再点加入。"); return; }
  var btn = $("btn-addsite"); btn.disabled = true;
  var msgs = [];
  pool(urls, 1, function (u) {
    return api("/api/sites/add", { url: u }).then(function () { msgs.push("✓ " + u); }, function (e) { msgs.push("✗ " + u + ":" + e.message); });
  }).then(function () {
    btn.disabled = false;
    reloadSites();
    alert("加入网站解锁常用网站:\n" + msgs.join("\n") + "\n\n所有人登录后都能看到。到「网站解锁」里点卡片的刷新按钮就能测。");
  });
});
function deleteSite(s) {
  if (!confirm("从常用网站里删掉「" + s.name + "」?所有人都会看不到它。")) return;
  api("/api/sites/delete", { id: s.id }).then(function () { closeDrawer(); reloadSites(); }, function (e) { alert(e.message); });
}

/* ── 开始按钮:按当前页面跑对应的测试 ── */
$("btn-test").addEventListener("click", function () {
  var btn = $("btn-test");
  if (btn.disabled) return;
  var lines = inputLines();
  if (!lines.length) { $("proxy-input").focus(); return; }
  btn.disabled = true; btn.textContent = TAB === "conn" ? "检测中" : "测试中";
  HIST.id = null;
  var job;
  if (TAB === "conn") job = runConn(lines);
  else job = loadUnlockSites().then(function () { syncProxyOptions(); closeDrawer(); return runUnlockButton(); });
  job.catch(function () {}).then(function () {
    btn.disabled = false; btn.textContent = TITLES[TAB][2];
    saveHistory();
  });
});

/* ── 历史记录(每人一份,多台设备同步) ── */
var HIST = { id: null };
var ME = { user: null, team: false };

function snapshot() {
  var unlock = {};
  Object.keys(UL.cache).forEach(function (k) {
    var en = UL.cache[k], res = {};
    Object.keys(en.results).forEach(function (sid) {
      var r = Object.assign({}, en.results[sid]);
      res[sid] = r;
    });
    unlock[k] = { proxy: en.proxy, mode: en.mode, results: res, exit: en.exit, modes: en.modes, exitErr: en.exitErr };
  });
  return { v: 2, tab: TAB, input: $("proxy-input").value, targets: $("opt-targets").value,
           conn: CONN.filter(function (r) { return r.data; }).map(function (r) { return { input: r.input, data: r.data, geo: r.geo }; }),
           unlock: unlock,
           unlockOptions: Array.prototype.map.call($("ul-proxy").options, function (o) { return o.value; }),
           unlockCur: $("ul-proxy").value, unlockMode: $("ul-mode").value };
}

function saveHistory() {
  var d = snapshot();
  var lines = d.input.split("\n").map(function (s) { return s.trim(); }).filter(Boolean);
  if (!lines.length) return;
  var okN = d.conn.filter(function (x) { return x.data.verdict === "full" || x.data.verdict === "partial"; }).length;
  var en = UL.cache[d.unlockCur + "|" + d.unlockMode];
  var parts = [];
  if (d.conn.length) parts.push("代理检测 " + okN + "/" + d.conn.length + " 可用");
  if (en && Object.keys(en.results).length) {
    var rs = Object.keys(en.results).map(function (k) { return en.results[k]; });
    parts.push("网站解锁 " + rs.filter(function (r) { return r.status === "ok"; }).length + "/" + rs.length + " 支持");
  }
  if (!parts.length) return;
  var title = maskLine(lines[0]) + (lines.length > 1 ? " 等 " + lines.length + " 条" : "");
  var body = { title: title, summary: parts.join(" · "), data: d };
  if (HIST.id) { body.id = HIST.id; api("/api/history/update", body).catch(function () {}); }
  else api("/api/history/save", body).then(function (r) { HIST.id = r.id; }).catch(function () {});
}

function restoreHistory(h) {
  var d = h.data || {};
  HIST.id = h.id;
  $("proxy-input").value = d.input || "";
  $("opt-targets").value = d.targets || "";
  if (d.v === 2) {
    CONN = (d.conn || []).map(function (r) { return { input: r.input, data: r.data, geo: r.geo, open: false }; });
  } else {
    /* 旧版记录:连通性和归属地分开存的 */
    var ips = {}; (d.ip || []).forEach(function (g) { if (g && g.ip) ips[g.ip] = g; });
    CONN = (d.proxy || []).map(function (r) {
      var ip = (r.exit && r.exit.ip) || hostOf(r.input || "");
      return { input: r.input || "", data: r, geo: ips[ip] || null, open: false };
    });
  }
  renderConn();
  UL.cache = {};
  Object.keys(d.unlock || {}).forEach(function (k) { UL.cache[k] = Object.assign({ started: true, busy: {} }, d.unlock[k]); });
  var sel = $("ul-proxy"); sel.textContent = "";
  (d.unlockOptions || []).forEach(function (l) { var o = el("option", null, maskLine(l)); o.value = l; sel.appendChild(o); });
  if (d.unlockCur) sel.value = d.unlockCur;
  $("ul-mode").value = d.unlockMode || "auto";
  closeDrawer();
  loadUnlockSites().then(function () { renderUnlock(); });
  if (d.v === 2 && d.tab) showTab(d.tab);
}

function openModal(title, node) {
  $("modal-title").textContent = title;
  var b = $("modal-body"); b.textContent = ""; b.appendChild(node);
  $("modal").hidden = false;
}
function closeModal() { $("modal").hidden = true; }
$("modal-close").addEventListener("click", closeModal);
$("modal").addEventListener("click", function (e) { if (e.target === $("modal")) closeModal(); });
document.addEventListener("keydown", function (e) { if (e.key === "Escape") { closeModal(); closeDrawer(); } });

function fmtTime(ts) {
  var d = new Date(ts * 1000), p = function (n) { return (n < 10 ? "0" : "") + n; };
  return (d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
}

$("btn-history").addEventListener("click", function () {
  getJSON("/api/history").then(function (d) {
    var wrap = el("div");
    if (!(d.items || []).length) {
      wrap.appendChild(el("div", "msg", "还没有记录。每次测试后会自动保存,换电脑登录也能看到。"));
    } else {
      var t = el("table", "mtable");
      var hr = el("tr"); ["时间", "测试内容", "结果", ""].forEach(function (x) { hr.appendChild(el("th", null, x)); }); t.appendChild(hr);
      d.items.forEach(function (it) {
        var tr = el("tr", "hist-item");
        tr.appendChild(el("td", null, fmtTime(it.created_at)));
        tr.appendChild(el("td", null, it.title));
        tr.appendChild(el("td", null, it.summary));
        var td = el("td"), del = el("button", "link", "删除"); del.type = "button";
        del.addEventListener("click", function (ev) {
          ev.stopPropagation();
          api("/api/history/delete", { id: it.id }).then(function () { tr.remove(); });
        });
        td.appendChild(del); tr.appendChild(td);
        tr.addEventListener("click", function () {
          getJSON("/api/history/get?id=" + it.id).then(function (h) { restoreHistory(h); closeModal(); });
        });
        t.appendChild(tr);
      });
      wrap.appendChild(t);
    }
    openModal("历史记录(点一行恢复当时的结果)", wrap);
  });
});

/* ── 账号:改密码 / 退出 / 管理 ── */
function formRow(fields, btnText, onSubmit) {
  var f = el("div", "mform"), inputs = {};
  fields.forEach(function (x) {
    var i;
    if (x.type === "select") {
      i = el("select");
      x.options.forEach(function (o) { var op = el("option", null, o[1]); op.value = o[0]; i.appendChild(op); });
    } else { i = el("input"); i.type = x.type || "text"; i.placeholder = x.ph; if (x.value) i.value = x.value; }
    inputs[x.name] = i; f.appendChild(i);
  });
  var b = el("button", "btn sec sm", btnText); b.type = "button"; f.appendChild(b);
  var msg = el("div", "msg");
  b.addEventListener("click", function () {
    var v = {}; Object.keys(inputs).forEach(function (k) { v[k] = inputs[k].value; });
    b.disabled = true; msg.className = "msg"; msg.textContent = "";
    Promise.resolve().then(function () { return onSubmit(v, msg); })
      .catch(function (e) { msg.className = "msg err"; msg.textContent = e.message; })
      .then(function () { b.disabled = false; });
  });
  var w = el("div"); w.appendChild(f); w.appendChild(msg);
  return w;
}

$("btn-passwd").addEventListener("click", function () {
  openModal("修改密码", formRow([{ name: "old", type: "password", ph: "原密码" },
                                { name: "new", type: "password", ph: "新密码(至少 8 位)" }],
    "确认修改", function (v, msg) {
      return api("/api/me/password", v).then(function () {
        msg.className = "msg ok"; msg.textContent = "已修改,请重新登录。";
        setTimeout(function () { location.reload(); }, 1200);
      });
    }));
});
$("btn-logout").addEventListener("click", function () { api("/api/logout", {}).then(function () { location.reload(); }); });

function adminPanel() {
  var wrap = el("div");
  wrap.appendChild(el("h3", null, "账号"));
  var list = el("div"); wrap.appendChild(list);
  function loadUsers() {
    getJSON("/api/admin/users").then(function (d) {
      list.textContent = "";
      var t = el("table", "mtable");
      var hr = el("tr"); ["用户名", "角色", "最近登录", ""].forEach(function (x) { hr.appendChild(el("th", null, x)); }); t.appendChild(hr);
      (d.users || []).forEach(function (u) {
        var tr = el("tr");
        tr.appendChild(el("td", null, u.username));
        tr.appendChild(el("td", null, u.is_admin ? "管理员" : "成员"));
        tr.appendChild(el("td", null, u.last_login ? fmtTime(u.last_login) : "从未登录"));
        var td = el("td");
        var rp = el("button", "link", "重置密码"); rp.type = "button";
        rp.addEventListener("click", function () {
          var pw = prompt("给 " + u.username + " 设置新密码(至少 8 位):");
          if (pw) api("/api/admin/users/password", { id: u.id, password: pw })
            .then(function () { alert("已重置,对方需要用新密码重新登录。"); }, function (e) { alert(e.message); });
        });
        td.appendChild(rp);
        if (!ME.user || u.id !== ME.user.id) {
          var dl = el("button", "link", "删除"); dl.type = "button"; dl.style.marginLeft = "12px";
          dl.addEventListener("click", function () {
            if (confirm("删除账号 " + u.username + "?他的测试记录也会删掉。"))
              api("/api/admin/users/delete", { id: u.id }).then(loadUsers, function (e) { alert(e.message); });
          });
          td.appendChild(dl);
        }
        tr.appendChild(td); t.appendChild(tr);
      });
      list.appendChild(t);
    });
  }
  loadUsers();
  wrap.appendChild(formRow([{ name: "username", ph: "新用户名" },
                            { name: "password", type: "password", ph: "初始密码(至少 8 位)" },
                            { name: "is_admin", type: "select", options: [["", "成员"], ["1", "管理员"]] }],
    "开账号", function (v, msg) {
      return api("/api/admin/users/create", { username: v.username, password: v.password, is_admin: !!v.is_admin })
        .then(function () {
          msg.className = "msg ok"; msg.textContent = "已创建。把用户名和初始密码发给对方,让他登录后自己改密码。";
          loadUsers();
        });
    }));
  return wrap;
}
$("btn-admin").addEventListener("click", function () { openModal("管理", adminPanel()); });

/* ── 启动 ── */
showTab("conn");
loadUnlockSites();
getJSON("/api/me").then(function (d) {
  ME = d;
  if (d.team) {
    $("me-box").hidden = false;
    $("me-name").textContent = d.user.username;
    $("me-av").textContent = (d.user.username || "?").charAt(0).toUpperCase();
    $("btn-passwd").hidden = false; $("btn-logout").hidden = false;
  }
  $("btn-admin").hidden = !d.user.is_admin;
  /* 登录后自动恢复最近一次的结果(换设备也一样) */
  getJSON("/api/history").then(function (h) {
    var it = (h.items || [])[0];
    if (it && !$("proxy-input").value.trim())
      getJSON("/api/history/get?id=" + it.id).then(restoreHistory);
  });
});

/* 心跳:独立窗口模式下,窗口关闭后服务器自动退出。放进 Web Worker,避免窗口最小化时被节流导致误杀 */
(function () {
  function ping() { fetch("/api/ping").catch(function () {}); }
  var started = false;
  try {
    var src = "var u=" + JSON.stringify(location.origin + "/api/ping") +
              ";setInterval(function(){fetch(u).catch(function(){})},3000);";
    new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" })));
    started = true;
  } catch (e) {}
  if (!started) setInterval(ping, 3000);
  document.addEventListener("visibilitychange", ping);
  ping();
})();
})();
</script>
</body>
</html>
'''
LOGIN_HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>登录 · 代理测试台</title>
<link rel="icon" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMDI0IDEwMjQiPjxkZWZzPjxsaW5lYXJHcmFkaWVudCBpZD0iYmciIHgxPSIwIiB5MT0iMCIgeDI9IjEiIHkyPSIxIj48c3RvcCBvZmZzZXQ9IjAiIHN0b3AtY29sb3I9IiNGRkZGRkYiLz48c3RvcCBvZmZzZXQ9Ii41NSIgc3RvcC1jb2xvcj0iI0YwRURGRiIvPjxzdG9wIG9mZnNldD0iMSIgc3RvcC1jb2xvcj0iI0NEQzVGRiIvPjwvbGluZWFyR3JhZGllbnQ+PGxpbmVhckdyYWRpZW50IGlkPSJjIiB4MT0iMCIgeTE9IjAiIHgyPSIxIiB5Mj0iMSI+PHN0b3Agb2Zmc2V0PSIwIiBzdG9wLWNvbG9yPSIjOTQ1QkZEIi8+PHN0b3Agb2Zmc2V0PSIxIiBzdG9wLWNvbG9yPSIjNDUyOEQwIi8+PC9saW5lYXJHcmFkaWVudD48L2RlZnM+PHJlY3QgeD0iMTAwIiB5PSIxMDAiIHdpZHRoPSI4MjQiIGhlaWdodD0iODI0IiByeD0iMTg2IiBmaWxsPSJ1cmwoI2JnKSIgc3Ryb2tlPSIjRENEM0ZGIiBzdHJva2Utd2lkdGg9IjQiLz48Y2lyY2xlIGN4PSI1MTIiIGN5PSI1MTIiIHI9IjMzMCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjOTQ1QkZEIiBzdHJva2Utd2lkdGg9IjEwIiBvcGFjaXR5PSIuMjIiLz48Y2lyY2xlIGN4PSI1MTIiIGN5PSI1MTIiIHI9IjI2OCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjOTQ1QkZEIiBzdHJva2Utd2lkdGg9IjE0IiBvcGFjaXR5PSIuNDIiLz48Y2lyY2xlIGN4PSI1MTIiIGN5PSI1MTIiIHI9IjIwMCIgZmlsbD0idXJsKCNjKSIvPjxwYXRoIGQ9Ik0zOTIgNTIwaDU2bDM2LTk2IDU2IDE5MiAzNi05Nmg1NiIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjZmZmIiBzdHJva2Utd2lkdGg9IjM0IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz48Y2lyY2xlIGN4PSI3NDUiIGN5PSIzMDAiIHI9IjMwIiBmaWxsPSIjQzIxQkJBIi8+PC9zdmc+">
<style>
body{margin:0;background:#F2F2F7;font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center}
.box{background:#fff;border-radius:16px;padding:30px 28px;width:min(340px,90vw);box-shadow:0 8px 30px rgba(0,0,0,.08)}
h1{font-size:24px;margin:0 0 20px;display:flex;align-items:center;gap:10px}
.logo{width:44px;height:44px;margin:-6px}
input{width:100%;box-sizing:border-box;border:0;background:rgba(118,118,128,.12);border-radius:10px;padding:11px 13px;font-size:14px;margin-bottom:12px}
input:focus{outline:none;box-shadow:0 0 0 2.5px rgba(0,122,255,.35)}
button{width:100%;border:0;border-radius:12px;background:#007AFF;color:#fff;font-size:15px;font-weight:600;padding:11px;cursor:pointer}
button:disabled{opacity:.5}
.err{color:#D70015;font-size:13px;min-height:20px;margin-top:8px}
.tip{color:#6E6E73;font-size:12px;margin-top:10px}
</style></head><body>
<form class="box" id="f">
  <h1><img src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMDI0IDEwMjQiPjxkZWZzPjxsaW5lYXJHcmFkaWVudCBpZD0iYmciIHgxPSIwIiB5MT0iMCIgeDI9IjEiIHkyPSIxIj48c3RvcCBvZmZzZXQ9IjAiIHN0b3AtY29sb3I9IiNGRkZGRkYiLz48c3RvcCBvZmZzZXQ9Ii41NSIgc3RvcC1jb2xvcj0iI0YwRURGRiIvPjxzdG9wIG9mZnNldD0iMSIgc3RvcC1jb2xvcj0iI0NEQzVGRiIvPjwvbGluZWFyR3JhZGllbnQ+PGxpbmVhckdyYWRpZW50IGlkPSJjIiB4MT0iMCIgeTE9IjAiIHgyPSIxIiB5Mj0iMSI+PHN0b3Agb2Zmc2V0PSIwIiBzdG9wLWNvbG9yPSIjOTQ1QkZEIi8+PHN0b3Agb2Zmc2V0PSIxIiBzdG9wLWNvbG9yPSIjNDUyOEQwIi8+PC9saW5lYXJHcmFkaWVudD48L2RlZnM+PHJlY3QgeD0iMTAwIiB5PSIxMDAiIHdpZHRoPSI4MjQiIGhlaWdodD0iODI0IiByeD0iMTg2IiBmaWxsPSJ1cmwoI2JnKSIgc3Ryb2tlPSIjRENEM0ZGIiBzdHJva2Utd2lkdGg9IjQiLz48Y2lyY2xlIGN4PSI1MTIiIGN5PSI1MTIiIHI9IjMzMCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjOTQ1QkZEIiBzdHJva2Utd2lkdGg9IjEwIiBvcGFjaXR5PSIuMjIiLz48Y2lyY2xlIGN4PSI1MTIiIGN5PSI1MTIiIHI9IjI2OCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjOTQ1QkZEIiBzdHJva2Utd2lkdGg9IjE0IiBvcGFjaXR5PSIuNDIiLz48Y2lyY2xlIGN4PSI1MTIiIGN5PSI1MTIiIHI9IjIwMCIgZmlsbD0idXJsKCNjKSIvPjxwYXRoIGQ9Ik0zOTIgNTIwaDU2bDM2LTk2IDU2IDE5MiAzNi05Nmg1NiIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjZmZmIiBzdHJva2Utd2lkdGg9IjM0IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz48Y2lyY2xlIGN4PSI3NDUiIGN5PSIzMDAiIHI9IjMwIiBmaWxsPSIjQzIxQkJBIi8+PC9zdmc+" alt="" class="logo">代理测试台</h1>
  <input id="u" autocomplete="username" placeholder="用户名" required>
  <input id="p" type="password" autocomplete="current-password" placeholder="密码" required>
  <button id="b" type="submit">登录</button>
  <div class="err" id="e"></div>
  <div class="tip">没有账号请找管理员开通。</div>
</form>
<script>
document.getElementById("f").addEventListener("submit", function (ev) {
  ev.preventDefault();
  var b = document.getElementById("b"), e = document.getElementById("e");
  b.disabled = true; e.textContent = "";
  fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: document.getElementById("u").value, password: document.getElementById("p").value }) })
    .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || "登录失败"); }); })
    .then(function () { location.reload(); }, function (err) { e.textContent = err.message; b.disabled = false; });
});
</script></body></html>"""

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
