#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代理连通性测试工具 —— 只用 Python 标准库,无需安装任何依赖。

用法:
    python3 proxy_test.py 主机:端口:用户名:密码
    python3 proxy_test.py http://用户名:密码@主机:端口
    python3 proxy_test.py 代理串 -t https://www.baidu.com   # 额外加测某个网站(可重复)
    python3 proxy_test.py 代理串 --timeout 20               # 每步超时秒数(默认 15)
    python3 proxy_test.py 代理串 -k                         # 跳过 HTTPS 证书校验(仅排查用)
"""

import argparse
import base64
import http.client
import json
import os
import socket
import re
import ssl
import sys
import time
import urllib.parse

# Windows 自带的证书库缺不少中间证书(Python 不会像浏览器那样自动补),有 certifi 就一起信任
if os.name == "nt" and not os.environ.get("SSL_CERT_FILE"):
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass

# ──────── 绕过本机 TUN 模式 VPN,直连代理服务器 ────────
# 本机开着 Shadowrocket / Clash 等 TUN 模式时,它会嗅探发往代理的 HTTP 请求,
# 把流量改道直接发给目标网站,导致 HTTP/HTTPS 测试误报 403。
# 这里只对「代理服务器本身」的连接绑定物理网卡(macOS IP_BOUND_IF),
# 其他请求(查归属地等)照常走系统网络。设环境变量 PROXY_TEST_NO_BYPASS=1 可关闭。
_PROXY_HOSTS = set()
_PHYS_IF = None


def _physical_ifindex():
    global _PHYS_IF
    if _PHYS_IF is not None:
        return _PHYS_IF
    _PHYS_IF = 0
    if sys.platform != "darwin" or os.environ.get("PROXY_TEST_NO_BYPASS"):
        return 0
    try:
        import subprocess
        names = [n for _, n in socket.if_nameindex() if n.startswith("en")]
        names.sort(key=lambda n: int(n[2:]) if n[2:].isdigit() else 99)
        for name in names:
            out = subprocess.run(["/sbin/ifconfig", name], capture_output=True,
                                 text=True, timeout=3).stdout
            if "status: active" in out and "\tinet " in out:
                _PHYS_IF = socket.if_nametoindex(name)
                break
    except Exception:
        _PHYS_IF = 0
    return _PHYS_IF


_orig_create_connection = socket.create_connection


def _create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                       source_address=None, *args, **kwargs):
    host, port = address[0], address[1]
    idx = _physical_ifindex() if host in _PROXY_HOSTS else 0
    if not idx:
        return _orig_create_connection(address, timeout, source_address, *args, **kwargs)
    err = None
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    # TUN 模式 VPN 的 fake-ip(198.18.0.0/15)只在 VPN 里有效,绑物理网卡会连不上、白等超时
    if all(i[4][0].startswith(("198.18.", "198.19.")) for i in infos):
        return _orig_create_connection(address, timeout, source_address, *args, **kwargs)
    for fam, typ, proto, _, sa in infos:
        s = None
        try:
            s = socket.socket(fam, typ, proto)
            if fam == socket.AF_INET6:
                s.setsockopt(socket.IPPROTO_IPV6, 125, idx)  # IPV6_BOUND_IF
            else:
                s.setsockopt(socket.IPPROTO_IP, 25, idx)     # IP_BOUND_IF
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                s.settimeout(timeout)
            if source_address:
                s.bind(source_address)
            s.connect(sa)
            return s
        except OSError as e:
            err = e
            if s:
                s.close()
    # 物理网卡连不上(如代理只能经 VPN 访问)就退回系统路由
    return _orig_create_connection(address, timeout, source_address, *args, **kwargs)


socket.create_connection = _create_connection

# ipinfo token(可选):设置环境变量 IPINFO_TOKEN 可提高 IP 归属地查询额度,不设也能用(匿名额度)
DEFAULT_IPINFO_TOKEN = os.environ.get("IPINFO_TOKEN", "")

# 只填一个 IP 时使用的默认端口和账密(可选,通过环境变量设置;不设则必须填完整代理串)
STATIC_DEFAULT_PORT = int(os.environ.get("PROXY_TEST_DEFAULT_PORT") or 0) or None
STATIC_DEFAULT_USER = os.environ.get("PROXY_TEST_DEFAULT_USER") or None
STATIC_DEFAULT_PASS = os.environ.get("PROXY_TEST_DEFAULT_PASS") or None

# 默认测试的目标网站
DEFAULT_TARGETS = [
    "https://www.google.com/generate_204",
    "https://www.example.com/",
    "http://ip-api.com/json/?lang=zh-CN",
]

# 查出口 IP 用的服务(依次尝试)
IP_SERVICES = [
    "https://ipinfo.io/json",
    "https://api.ipify.org/?format=json",
]

# pythonw(无控制台)下 sys.stdout 为 None,跳过终端相关设置
if os.name == "nt" and sys.stdout is not None:
    os.system("")  # 让 Windows 终端支持 ANSI 颜色
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
try:
    if sys.stdout is not None:
        # 终端编码打不出某些字符时显示 ? 而不是崩溃(如 GBK 环境)
        sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

USE_COLOR = (sys.stdout is not None and sys.stdout.isatty())

# 老式 Windows 控制台(cmd)字体常缺 ✓/✗,退回 GBK 字体里有的 √/×
_LEGACY_WIN = (os.name == "nt" and not os.environ.get("WT_SESSION"))
MARK_OK = "√" if _LEGACY_WIN else "✓"
MARK_BAD = "×" if _LEGACY_WIN else "✗"


def _c(text, code):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else str(text)


def ok(t=None):
    return _c(MARK_OK if t is None else t, "32")


def bad(t=None):
    return _c(MARK_BAD if t is None else t, "31")


def warn(t="△"):
    return _c(t, "33")


def dim(t):
    return _c(t, "2")


def bold(t):
    return _c(t, "1")


def mask(p):
    """密码打码显示,避免截图泄露"""
    if not p:
        return "(无)"
    if len(p) <= 4:
        return "*" * len(p)
    return p[:2] + "*" * (len(p) - 4) + p[-2:]


class Proxy:
    def __init__(self, host, port, user=None, password=None):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.auth_source = ""  # 只填 IP 时为「默认账密」

    @property
    def auth_header(self):
        if not self.user:
            return None
        raw = f"{self.user}:{self.password or ''}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")


def _valid_port(port_s):
    try:
        port = int(port_s)
    except (TypeError, ValueError):
        return None
    return port if 0 < port < 65536 else None


def _try_colon_form(s):
    """主机:端口 或 主机:端口:用户:密码(密码里允许出现 : 和 @)"""
    parts = s.split(":", 3)
    if len(parts) == 2:
        host, port_s = parts
        user = password = None
    elif len(parts) == 4:
        host, port_s, user, password = parts
    else:
        return None
    port = _valid_port(port_s)
    if not host or "@" in host or port is None:
        return None
    return Proxy(host, port, user, password)


def _try_at_form(s):
    """用户:密码@主机:端口(以最后一个 @ 为分界)"""
    if "@" not in s:
        return None
    cred, hostport = s.rsplit("@", 1)
    user, _, password = cred.partition(":")
    host, _, port_s = hostport.partition(":")
    port = _valid_port(port_s)
    if not host or port is None:
        return None
    return Proxy(host, port,
                 urllib.parse.unquote(user) or None,
                 urllib.parse.unquote(password) or None)


def parse_proxy(text):
    px = _parse_proxy(text)
    _PROXY_HOSTS.add(px.host)
    return px


def _parse_proxy(text):
    """支持三种写法:主机:端口:用户:密码 / 用户:密码@主机:端口 / http://用户:密码@主机:端口"""
    s = text.strip()
    had_scheme = "://" in s
    if had_scheme:
        s = s.split("://", 1)[1]
    s = s.rstrip("/")
    # 只填了一个 IPv4:套用环境变量里配置的默认端口与账密
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", s):
        if not STATIC_DEFAULT_PORT:
            raise ValueError("只填了 IP,但没有配置默认端口和账密(环境变量 PROXY_TEST_DEFAULT_PORT / "
                             "PROXY_TEST_DEFAULT_USER / PROXY_TEST_DEFAULT_PASS),请填完整代理串")
        px = Proxy(s, STATIC_DEFAULT_PORT, STATIC_DEFAULT_USER, STATIC_DEFAULT_PASS)
        px.auth_source = "默认账密"
        return px
    # 带 scheme 的按 URL 惯例优先认 @ 形式;裸字符串优先按文档写法的冒号形式
    order = (_try_at_form, _try_colon_form) if had_scheme else (_try_colon_form, _try_at_form)
    for attempt in order:
        px = attempt(s)
        if px:
            return px
    raise ValueError(
        "无法识别,应为 主机:端口:用户名:密码(端口必须是数字)"
        "或 http://用户名:密码@主机:端口")


def explain(exc):
    """把底层异常翻译成人话"""
    if isinstance(exc, socket.gaierror):
        return "DNS 解析失败:代理域名无法解析(检查地址拼写 / 本机网络)"
    if isinstance(exc, ConnectionRefusedError):
        return "连接被拒绝:端口写错了,或代理服务没有运行"
    if isinstance(exc, ConnectionResetError):
        return "连接被对方重置:代理主动断开(常见于认证失败,或该端口不是 HTTP 代理)"
    if isinstance(exc, http.client.BadStatusLine):
        return (f"代理返回了非 HTTP 响应({str(exc).strip()!r}):"
                "该端口可能不是 HTTP 代理(如 SSH/SOCKS 端口)")
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "超时:代理没有响应(可能被所在网络/防火墙拦截,或代理已失效)"
    if isinstance(exc, ssl.SSLCertVerificationError):
        detail = getattr(exc, "verify_message", None) or str(exc)
        return f"HTTPS 证书校验失败({detail}),可加 -k 跳过校验再试"
    if isinstance(exc, ssl.SSLError):
        return f"TLS 握手失败:{exc}"
    msg = str(exc)
    if "407" in msg:
        return "代理认证失败(HTTP 407):用户名或密码不对,或账号过期 / 流量用尽"
    if "Tunnel connection failed" in msg:
        detail = msg.split("Tunnel connection failed:", 1)[-1].strip()
        return f"代理拒绝建立隧道:{detail}"
    return msg or exc.__class__.__name__


def fetch_via_proxy(px, url, timeout, ssl_ctx):
    """通过代理 GET 一个 URL,返回 (状态码, 原因, 响应体前 64KB, 耗时毫秒)"""
    u = urllib.parse.urlsplit(url)
    host = u.hostname
    https = (u.scheme == "https")
    port = u.port or (443 if https else 80)
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    default_port = 443 if https else 80
    headers = {
        "Host": host if port == default_port else f"{host}:{port}",
        "User-Agent": "Mozilla/5.0 (proxy-connectivity-test/1.0)",
        "Accept": "*/*",
        "Connection": "close",
    }
    conn = None
    t0 = time.perf_counter()
    try:
        if https:
            conn = http.client.HTTPSConnection(
                px.host, px.port, timeout=timeout, context=ssl_ctx)
            tunnel_headers = {}
            if px.auth_header:
                tunnel_headers["Proxy-Authorization"] = px.auth_header
            conn.set_tunnel(host, port, headers=tunnel_headers)
            conn.request("GET", path, headers=headers)
        else:
            conn = http.client.HTTPConnection(px.host, px.port, timeout=timeout)
            if px.auth_header:
                headers["Proxy-Authorization"] = px.auth_header
            # HTTP 走代理转发,请求行必须用绝对 URI
            conn.request("GET", url, headers=headers)
        resp = conn.getresponse()
        body = resp.read(65536)
        elapsed = (time.perf_counter() - t0) * 1000
        return resp.status, resp.reason, body, elapsed
    finally:
        if conn is not None:
            conn.close()


def step(label):
    print(f"  {label} ", end="", flush=True)


def main():
    ap = argparse.ArgumentParser(description="HTTP 代理连通性测试工具(帐密认证)")
    ap.add_argument("proxy",
                    help="代理,格式 主机:端口:用户名:密码")
    ap.add_argument("-t", "--target", action="append", metavar="URL",
                    help="要通过代理访问的网站,可多次指定(默认测 Google 等 3 个)")
    ap.add_argument("--timeout", type=float, default=15, metavar="秒",
                    help="每一步的超时时间,默认 15 秒")
    ap.add_argument("-k", "--insecure", action="store_true",
                    help="跳过 HTTPS 证书校验(仅排查问题时用)")
    args = ap.parse_args()

    try:
        px = parse_proxy(args.proxy)
    except ValueError as e:
        print(bad(f"代理地址格式不对:{e}"))
        return 2

    targets = []
    for url in (args.target or DEFAULT_TARGETS):
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https"):
            url = "https://" + url  # 没写协议时默认按 https 访问
            u = urllib.parse.urlsplit(url)
        if not u.hostname:
            print(bad(f"目标网址不合法:{url}"))
            return 2
        targets.append(url)
    ssl_ctx = (ssl._create_unverified_context() if args.insecure
               else ssl.create_default_context())

    print()
    print(bold("  ═══════════ 代理连通性测试 ═══════════"))
    print(f"  代理服务器 : {px.host}:{px.port}")
    print(f"  用户名     : {px.user or '(无认证)'}")
    if px.user:
        print(f"  密码       : {mask(px.password)}")
    print()

    fail_reason = None

    # ── 1. DNS 解析 ──
    step("[1/4] 解析代理域名 ...")
    try:
        t0 = time.perf_counter()
        infos = socket.getaddrinfo(px.host, px.port, type=socket.SOCK_STREAM)
        ms = (time.perf_counter() - t0) * 1000
        ips = sorted({i[4][0] for i in infos})
        shown = ", ".join(ips[:3]) + (" …" if len(ips) > 3 else "")
        print(f"{ok()} {shown}  {dim(f'{ms:.0f} ms')}")
    except Exception as e:
        fail_reason = explain(e)
        print(f"{bad()} {bad(fail_reason)}")
        print(f"\n  结论: {bad(MARK_BAD + ' 代理不可用')} —— {fail_reason}\n")
        return 1

    # ── 2. TCP 连接 ──
    step("[2/4] TCP 连接代理端口 ...")
    try:
        t0 = time.perf_counter()
        s = socket.create_connection((px.host, px.port), timeout=args.timeout)
        ms = (time.perf_counter() - t0) * 1000
        s.close()
        print(f"{ok()} 已连通  {dim(f'{ms:.0f} ms')}")
    except Exception as e:
        fail_reason = explain(e)
        print(f"{bad()} {bad(fail_reason)}")
        print(f"\n  结论: {bad(MARK_BAD + ' 代理不可用')} —— {fail_reason}\n")
        return 1

    # ── 3. 认证 + 出口 IP ──
    step("[3/4] 代理认证并获取出口 IP ...")
    exit_ip_ok = False
    auth_failed = False
    for svc in IP_SERVICES:
        try:
            status, reason, body, ms = fetch_via_proxy(px, svc, args.timeout, ssl_ctx)
            if status == 200:
                try:
                    data = json.loads(body.decode("utf-8", "replace"))
                except ValueError:
                    data = {}
                ip = data.get("ip") or data.get("query") or "?"
                print(f"{ok()} 出口 IP: {bold(ip)}  {dim(f'{ms:.0f} ms')}")
                loc = ", ".join(str(x) for x in
                                (data.get("city"), data.get("region"),
                                 data.get("country")) if x)
                extra = []
                if loc:
                    extra.append(f"位置: {loc}")
                if data.get("org"):
                    extra.append(f"运营商: {data['org']}")
                if extra:
                    print("        " + dim("  ".join(extra)))
                exit_ip_ok = True
                break
            fail_reason = f"HTTP {status} {reason}"
            if status == 407:
                auth_failed = True
                break
        except Exception as e:
            fail_reason = explain(e)
            if "407" in str(e):
                auth_failed = True
                break
    if not exit_ip_ok:
        print(f"{bad()} {bad(fail_reason or '未知错误')}")

    # 认证都过不了,后面没必要测了
    if auth_failed:
        print(f"\n  结论: {bad(MARK_BAD + ' 代理不可用 —— 认证失败,请核对用户名和密码')}\n")
        return 1

    # ── 4. 逐个访问测试网站 ──
    print("  [4/4] 通过代理访问测试网站:")
    target_ok = 0
    for url in targets:
        disp = url if len(url) <= 42 else url[:39] + "..."
        print(f"    {disp:<44}", end="", flush=True)
        try:
            status, reason, body, ms = fetch_via_proxy(px, url, args.timeout, ssl_ctx)
            good = 200 <= status < 400
            mark = ok() if good else warn()
            print(f"{mark} HTTP {status}  {dim(f'{ms:.0f} ms')}")
            if good:
                target_ok += 1
                if "ip-api.com" in url and status == 200:
                    try:
                        d = json.loads(body.decode("utf-8", "replace"))
                        loc = " ".join(str(x) for x in
                                       (d.get("country"), d.get("regionName"),
                                        d.get("city")) if x)
                        if loc:
                            print("      " + dim(f"└ 出口位置: {loc}  "
                                                 f"ISP: {d.get('isp', '?')}"))
                    except ValueError:
                        pass
            else:
                fail_reason = f"HTTP {status} {reason}"
                if status == 407:
                    auth_failed = True
        except Exception as e:
            fail_reason = explain(e)
            print(f"{bad()} {bad(fail_reason)}")
            if "407" in str(e):
                auth_failed = True

    # ── 汇总 ──
    print()
    print(dim("  " + "─" * 44))
    if auth_failed:
        print(f"  结论: {bad(MARK_BAD + ' 代理不可用 —— 认证失败,请核对用户名和密码')}\n")
        return 1
    if exit_ip_ok and target_ok == len(targets):
        print(f"  结论: {ok(MARK_OK + ' 代理完全可用')},"
              f"{len(targets)} 个网站全部访问成功\n")
        return 0
    if target_ok > 0:
        print(f"  结论: {warn('△ 代理基本可用')},"
              f"{target_ok}/{len(targets)} 个测试网站访问成功\n")
        return 0
    if exit_ip_ok:
        print(f"  结论: {warn('△ 代理能认证并出网,但所有测试网站都访问失败')}"
              f"(出口 IP 可能被目标网站封锁)\n")
        return 1
    print(f"  结论: {bad(MARK_BAD + ' 代理不可用')} —— "
          f"{fail_reason or '所有请求都失败了'}\n")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
