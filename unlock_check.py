"""解锁测试:经代理访问客户常用网站,判断能否正常打开 / 是否被地区限制 / 是否触发人机验证。

内置一份常用网站清单(AI、社媒、Google、支付、电商等),也可以用同目录的 sites.json 覆盖。
每个站点一个检测函数,返回 {status, label, region, detail, ms}:
  status: ok=支持 / no=不支持(地区限制或明确拒绝) / warn=能打开但触发验证或限流 / fail=测试失败
"""

import http.client
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.parse
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed

import proxy_test as core

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
MAX_BODY = 2 * 1024 * 1024
CONNECT_TIMEOUT = 7  # 建隧道 + TLS 握手的上限;慢代理连不上时尽快失败,别干等

# OpenAI / Anthropic 不提供服务的地区(以官方支持列表为准,这里只列明确不支持的)
OPENAI_BLOCKED = {"CN", "HK", "MO", "RU", "BY", "IR", "KP", "SY", "CU", "VE", "AF"}
CLAUDE_BLOCKED = {"CN", "HK", "MO", "RU", "BY", "IR", "KP", "SY", "CU", "AF"}
GEMINI_BLOCKED = {"CHN", "HKG", "MAC", "RUS", "BLR", "IRN", "PRK", "SYR", "CUB"}


class TunnelError(Exception):
    """经代理连网站失败。kind 指出断在哪一步,见 FAIL_KINDS。"""

    def __init__(self, msg, auth=False, kind="other"):
        super().__init__(msg)
        self.auth = auth
        self.kind = "auth" if auth else kind


# 失败原因:kind -> (短标签, 白话原因, 建议)。{t} 会替换成超时秒数
FAIL_KINDS = {
    "proxy_down": ("连不上代理",
                   "连不上代理服务器本身:代理地址或端口不对、代理已过期,或者本机网络到代理不通。",
                   "先看上面「代理连通性」这条代理是否可用;不可用就是代理本身的问题,跟网站无关。"),
    "auth": ("代理认证失败",
             "代理账号或密码不对,或者账号已过期 / 流量用完。",
             "核对账密和账户余额。"),
    "proxy_reset": ("代理断开连接",
                    "代理服务器在替我们连这个网站时,直接把连接断开了。常见两种情况:"
                    "① 代理服务商对这个网站有限制;② 代理出口节点这一下不稳定。",
                    "先点重测。如果反复出现、而别的网站正常,基本是代理侧对这个网站有限制,"
                    "可找代理服务商确认;如果很多网站都这样,就是这条 IP 不稳定,换 IP。"),
    "proxy_refused": ("代理拒绝访问",
                      "代理明确拒绝访问这个网站,说明这个网站在代理侧被限制。",
                      "找代理服务商确认这个网站是否被限制。"),
    "target_unreachable": ("网站连不上",
                           "代理收到了请求,但代理的出口节点连不上这个网站:"
                           "网站在出口所在国家 / 地区打不开,或者出口节点网络有问题。",
                           "换一个其他国家 / 地区的 IP 再试。"),
    "tunnel_timeout": ("代理无响应",
                       "代理收到请求后 {t} 秒内一直没回应:出口节点太慢或卡住了,"
                       "也可能出口那边连这个网站连不上。",
                       "重测一次;仍然超时就换 IP。"),
    "tls_cut": ("连接被切断",
                "代理已经把通道接通了,但在和网站建立加密连接(或传数据)时被切断。"
                "多数是代理出口这边拦截了这个网站,少数是网站自己拒绝了这个 IP。",
                "先点重测;反复出现就找代理服务商确认或换 IP。"),
    "tls_timeout": ("握手超时",
                    "通道接通了,但和网站的加密握手 {t} 秒内没完成:出口节点到网站的网络很慢或丢包。",
                    "重测或换 IP。"),
    "page_timeout": ("网页加载超时",
                     "网站已经开始响应,但页面太慢,{t} 秒内没加载完。",
                     "把超时调大一点再测,或换速度更快的 IP。"),
    "tls_cert": ("证书异常",
                 "网站返回的证书不对,连接可能被中间设备劫持。",
                 "把情况发给技术排查。"),
    "other": ("测试失败", "", "重测;仍然失败就联系技术。"),
}
# 两种协议都失败时,用哪个原因做主结论(越靠前越能说明问题)
_KIND_ORDER = ["auth", "proxy_down", "proxy_refused", "target_unreachable", "proxy_reset",
               "tls_cut", "tunnel_timeout", "tls_timeout", "page_timeout", "tls_cert", "other"]


# ──────────────────────────── 经代理建隧道 ────────────────────────────

def _recvn(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionResetError("连接被对方关闭")
        buf += chunk
    return buf


def _connect_proxy(px, timeout):
    try:
        return socket.create_connection((px.host, px.port), timeout=timeout)
    except OSError as e:
        raise TunnelError(f"连不上代理服务器:{core.explain(e)}", kind="proxy_down")


def _tunnel_http(px, host, port, timeout):
    s = _connect_proxy(px, timeout)
    try:
        req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
        if px.auth_header:
            req += f"Proxy-Authorization: {px.auth_header}\r\n"
        s.sendall((req + "\r\n").encode("latin-1"))
        buf = b""
        while b"\r\n\r\n" not in buf:
            try:
                chunk = s.recv(4096)
            except ConnectionResetError:
                raise TunnelError("HTTP CONNECT 时代理重置了连接", kind="proxy_reset")
            except socket.timeout:
                raise TunnelError("HTTP CONNECT 后代理一直没回应", kind="tunnel_timeout")
            if not chunk:
                raise TunnelError("HTTP CONNECT 后代理没回应就关闭了连接", kind="target_unreachable")
            buf += chunk
            if len(buf) > 65536:
                raise TunnelError("代理返回了异常的隧道响应")
        first = buf.split(b"\r\n", 1)[0].decode("latin-1", "replace")
        parts = first.split()
        code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        if code == 407:
            raise TunnelError("代理认证失败(407)", auth=True)
        if code != 200:
            kind = "target_unreachable" if code in (502, 503, 504) else "proxy_refused"
            raise TunnelError(f"HTTP CONNECT 返回 {first[9:].strip() or code}", kind=kind)
        return s
    except BaseException:
        s.close()
        raise


_SOCKS_REASON = {1: "一般性失败", 2: "规则不允许", 3: "网络不可达", 4: "主机不可达",
                 5: "目标拒绝连接", 6: "TTL 超时", 7: "命令不支持", 8: "地址类型不支持"}


_SOCKS_KIND = {2: "proxy_refused", 3: "target_unreachable", 4: "target_unreachable",
               5: "target_unreachable", 6: "tunnel_timeout"}


def _tunnel_socks5(px, host, port, timeout):
    s = _connect_proxy(px, timeout)
    try:
        return _socks5_handshake(s, px, host, port)
    except ConnectionResetError:
        s.close()
        raise TunnelError("SOCKS5 握手时代理重置了连接", kind="proxy_reset")
    except socket.timeout:
        s.close()
        raise TunnelError("SOCKS5 握手后代理一直没回应", kind="tunnel_timeout")
    except BaseException:
        s.close()
        raise


def _socks5_handshake(s, px, host, port):
    methods = b"\x00\x02" if px.user else b"\x00"
    s.sendall(b"\x05" + bytes([len(methods)]) + methods)
    ver, method = _recvn(s, 2)
    if ver != 5:
        raise TunnelError("该端口不提供 SOCKS5 服务")
    if method == 0xFF:
        raise TunnelError("SOCKS5 服务器拒绝了所有认证方式", auth=True)
    if method == 0x02:
        u = (px.user or "").encode("utf-8")[:255]
        pw = (px.password or "").encode("utf-8")[:255]
        s.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(pw)]) + pw)
        if _recvn(s, 2)[1] != 0:
            raise TunnelError("SOCKS5 认证失败", auth=True)
    hb = host.encode("idna")
    s.sendall(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + port.to_bytes(2, "big"))
    rep = _recvn(s, 4)
    if rep[1] != 0:
        raise TunnelError("SOCKS5 回复:" + _SOCKS_REASON.get(rep[1], f"错误码 {rep[1]}"),
                          kind=_SOCKS_KIND.get(rep[1], "other"))
    atyp = rep[3]
    if atyp == 1:
        _recvn(s, 6)
    elif atyp == 3:
        _recvn(s, _recvn(s, 1)[0] + 2)
    elif atyp == 4:
        _recvn(s, 18)
    return s


class _ProxiedHTTPS(http.client.HTTPSConnection):
    """HTTPSConnection,但 TCP 层先经代理(HTTP CONNECT 或 SOCKS5)打通到目标。"""

    def __init__(self, host, port, px, mode, timeout, ctx):
        super().__init__(host, port, timeout=timeout, context=ctx)
        self._px, self._mode = px, mode

    def connect(self):
        if self.sock is not None:
            return
        fn = _tunnel_socks5 if self._mode == "socks5" else _tunnel_http
        raw = fn(self._px, self.host, self.port, min(self.timeout, CONNECT_TIMEOUT))
        try:
            raw.settimeout(min(self.timeout, CONNECT_TIMEOUT))
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
            self.sock.settimeout(self.timeout)
        except ssl.SSLCertVerificationError as e:
            raw.close()
            raise TunnelError(f"TLS 证书校验失败:{e.verify_message}", kind="tls_cert")
        except (ConnectionResetError, ssl.SSLEOFError, ssl.SSLError) as e:
            raw.close()
            raise TunnelError(f"TLS 握手时连接被切断({type(e).__name__})", kind="tls_cut")
        except socket.timeout:
            raw.close()
            raise TunnelError("TLS 握手超时", kind="tls_timeout")


class Resp:
    def __init__(self, status, headers, body, url, history):
        self.status, self.headers, self.body = status, headers, body
        self.url, self.history = url, history

    def h(self, name):
        return self.headers.get(name.lower(), "")

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")




def fetch(px, mode, url, timeout, headers=None, follow=5, ctx=None):
    """经代理 GET 一个 https 地址,跟随最多 follow 次跳转。"""
    ctx = ctx or ssl.create_default_context()
    history = []
    for _ in range(follow + 1):
        u = urllib.parse.urlsplit(url)
        path = (u.path or "/") + ("?" + u.query if u.query else "")
        hdr = {"User-Agent": UA, "Accept-Encoding": "gzip",
               "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9", "Connection": "close",
               "Upgrade-Insecure-Requests": "1", "Sec-Fetch-Mode": "navigate",
               "Sec-Fetch-Site": "none", "Sec-Fetch-Dest": "document", "Sec-Fetch-User": "?1",
               "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
               "Sec-Ch-Ua-Mobile": "?0", "Sec-Ch-Ua-Platform": '"macOS"'}
        hdr.update(headers or {})
        conn = _ProxiedHTTPS(u.hostname, u.port or 443, px, mode, timeout, ctx)
        try:
            conn.connect()
            try:
                conn.request("GET", path, headers=hdr)
                r = conn.getresponse()
            except socket.timeout:
                raise TunnelError("等网页返回超时", kind="page_timeout")
            except (ConnectionResetError, http.client.RemoteDisconnected, ssl.SSLError) as e:
                raise TunnelError(f"接收网页时连接被切断({type(e).__name__})", kind="tls_cut")
            hs = {k.lower(): v for k, v in r.getheaders()}
            try:
                raw = r.read(MAX_BODY)
            except http.client.IncompleteRead as e:  # 代理中途断流,已收到的部分照样用
                raw = e.partial
        finally:
            conn.close()
        if "gzip" in hs.get("content-encoding", "").lower():
            try:
                raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw, MAX_BODY * 4)
            except zlib.error:
                pass
        loc = hs.get("location")
        if r.status in (301, 302, 303, 307, 308) and loc and len(history) < follow:
            history.append((r.status, url))
            url = urllib.parse.urljoin(url, loc)
            continue
        return Resp(r.status, hs, raw, url, history)
    return Resp(r.status, hs, raw, url, history)


# ──────────────────────────── 通用判断 ────────────────────────────

def _cf_trace(px, mode, host, timeout):
    """Cloudflare 站点的 /cdn-cgi/trace,返回 loc 国家代码(拿不到返回空)。"""
    try:
        r = fetch(px, mode, f"https://{host}/cdn-cgi/trace", timeout, follow=0)
        m = re.search(r"^loc=([A-Z]{2})", r.text, re.M)
        return m.group(1) if m else ""
    except Exception:
        return ""


_BLOCK_URL = re.compile(r"unavailable|unsupported|not[-_]?available|blocked|restricted|/sorry/", re.I)


def classify(r):
    """把一次访问结果归类成 (status, label, detail)。"""
    body = r.body[:300000]
    low = body.lower()
    if r.h("cf-mitigated") == "challenge" or b"challenges.cloudflare.com/turnstile" in low \
            or b"<title>just a moment" in low or b"cf-chl-" in low:
        return "warn", "Cloudflare 验证", (f"网站能连上,但 Cloudflare 要求这个 IP 先做人机验证(HTTP {r.status})。"
                                           "客户用浏览器访问时通常要点一下验证;IP 越干净越少弹,可换 IP 对比。")
    captcha_tip = "网站能连上,但风控要求这个 IP 先过验证码({})。客户用浏览器时可能频繁弹验证码,可换更干净的 IP。"
    if r.h("x-amzn-waf-action") in ("challenge", "captcha"):
        return "warn", "人机验证", captcha_tip.format("亚马逊 AWS 风控")
    if b"captcha-delivery.com" in low:
        return "warn", "人机验证", captcha_tip.format("DataDome 风控")
    if b"px-captcha" in low or b"perimeterx" in low:
        return "warn", "人机验证", captcha_tip.format("PerimeterX 风控")
    if "/sorry/" in r.url or (b"captcha" in low and r.status in (403, 429, 503)):
        return "warn", "人机验证", captcha_tip.format(f"HTTP {r.status}")
    if _BLOCK_URL.search(urllib.parse.urlsplit(r.url).path):
        return "no", "不支持", f"网站把这个 IP 跳转到了「不支持 / 不可用」页面({r.url}),通常是地区不支持。换其他国家的 IP。"
    s = r.status
    if 200 <= s < 400:
        return "ok", "支持", f"正常打开(HTTP {s})"
    if s == 451:
        return "no", "地区限制", "网站因法律 / 地区原因不对这个国家提供服务(HTTP 451)。换其他国家的 IP。"
    if s == 429:
        return "warn", "限流", "网站说这个 IP 请求太多了(HTTP 429),暂时限制访问。过一会儿再测,或换 IP。"
    if s == 999:
        return "warn", "风控拦截", "LinkedIn 把这个 IP 识别为异常访问(HTTP 999)。换更干净的 IP 再试。"
    if s == 403:
        return "no", "拒绝访问", ("网站拒绝了这个出口 IP(HTTP 403):这个 IP 被网站拉黑,或被识别成代理 / 机房 IP。"
                                 "HTTP 和 SOCKS5 用的是同一个出口 IP,换协议没用,需要换一个 IP 再测。")
    if s in (500, 502, 503, 504):
        return "warn", "网站出错", f"网站返回服务器错误(HTTP {s}),可能是网站临时故障,也可能是在拦截这个 IP。重测一次看看。"
    if 400 <= s < 500:
        return "warn", f"HTTP {s}", (f"网站拒绝了这次访问(HTTP {s}),常见于网站识别出是自动化访问或这个 IP 有风险。"
                                    "用浏览器实际打开看看;打不开就换 IP,或用网页解锁器。")
    return "warn", f"HTTP {s}", f"网站返回了少见的状态码 HTTP {s},建议用浏览器实际打开确认。"


def _generic(url, region_host=None):
    def check(px, mode, timeout):
        r = fetch(px, mode, url, timeout)
        st, label, detail = classify(r)
        region = _cf_trace(px, mode, region_host, timeout) if region_host and st == "ok" else ""
        return {"status": st, "label": label, "detail": detail, "region": region}
    return check


# ──────────────────────────── 专项检测 ────────────────────────────

def check_chatgpt(px, mode, timeout):
    loc = _cf_trace(px, mode, "chatgpt.com", timeout)
    if loc in OPENAI_BLOCKED:
        return {"status": "no", "label": "不支持", "region": loc,
                "detail": f"出口地区 {loc} 不在 OpenAI 服务范围"}
    st, label, detail = classify(fetch(px, mode, "https://chatgpt.com/", timeout))
    if st == "ok":
        return {"status": "ok", "label": "支持", "region": loc, "detail": detail}
    return {"status": st, "label": label, "region": loc, "detail": detail}


def check_claude(px, mode, timeout):
    # claude.ai 的页面对任何脚本请求都弹 Cloudflare 验证(干净 IP 也一样),
    # 所以只按 /cdn-cgi/trace 拿到的出口地区判断是否在服务范围内
    r = fetch(px, mode, "https://claude.ai/cdn-cgi/trace", timeout, follow=0)
    m = re.search(r"^loc=([A-Z]{2})", r.text, re.M)
    if not m:
        st, label, detail = classify(r)
        return {"status": "fail" if st == "ok" else st, "label": "测试失败" if st == "ok" else label,
                "region": "", "detail": "拿不到地区信息;" + detail}
    loc = m.group(1)
    if loc in CLAUDE_BLOCKED:
        return {"status": "no", "label": "不支持", "region": loc,
                "detail": f"出口地区 {loc} 不在 Claude 服务范围"}
    return {"status": "ok", "label": "支持", "region": loc, "detail": "按出口地区判断"}


def check_gemini(px, mode, timeout):
    r = fetch(px, mode, "https://gemini.google.com/", timeout)
    st, label, detail = classify(r)
    if st != "ok":
        return {"status": st, "label": label, "region": "", "detail": detail}
    m = re.search(r',2,1,200,"([A-Z]{3})"', r.text)
    region = m.group(1) if m else ""
    if region in GEMINI_BLOCKED or re.search(r"(?:isn.t|not) (?:currently )?(?:supported|available) in your (?:country|region)", r.text):
        return {"status": "no", "label": "不支持", "region": region,
                "detail": "该地区不能使用 Gemini"}
    if not region:
        return {"status": "warn", "label": "未知", "region": "", "detail": "页面能打开,但识别不出地区"}
    return {"status": "ok", "label": "支持", "region": region, "detail": detail}


def check_youtube(px, mode, timeout):
    r = fetch(px, mode, "https://www.youtube.com/premium", timeout,
              headers={"Cookie": "CONSENT=YES+1"})
    st, label, detail = classify(r)
    if st != "ok":
        return {"status": st, "label": label, "region": "", "detail": detail}
    t = r.text
    m = re.search(r'"INNERTUBE_CONTEXT_GL":"([A-Z]{2})"', t) or re.search(r'"countryCode":"([A-Z]{2})"', t)
    region = m.group(1) if m else ""
    if "www.google.cn" in t:
        return {"status": "no", "label": "不支持", "region": "CN", "detail": "被跳转到 google.cn"}
    if "Premium is not available in your country" in t:
        return {"status": "no", "label": "Premium 不支持", "region": region,
                "detail": "YouTube 可访问,但该地区不能开通 Premium"}
    return {"status": "ok", "label": "支持", "region": region, "detail": detail}


def check_tiktok(px, mode, timeout):
    r = fetch(px, mode, "https://www.tiktok.com/explore", timeout)
    st, label, detail = classify(r)
    m = re.search(r'"region":"([A-Z]{2})"', r.text)
    region = m.group(1) if m else ""
    if st == "ok" and region in ("CN", "HK", "MO"):
        return {"status": "no", "label": "不支持", "region": region,
                "detail": f"TikTok 不在 {region} 提供服务"}
    return {"status": st, "label": label, "region": "", "detail": detail}


def check_google(px, mode, timeout):
    r = fetch(px, mode, "https://www.google.com/search?q=weather&hl=en", timeout)
    st, label, detail = classify(r)
    if st == "ok" and "google.cn" in urllib.parse.urlsplit(r.url).hostname:
        return {"status": "no", "label": "不支持", "region": "CN", "detail": "被跳转到 google.cn"}
    m = re.search(r'"gl":"([A-Z]{2})"', r.text) or re.search(r'[?&]gl=([A-Z]{2})', r.text)
    region = m.group(1) if m else ""
    if st == "warn" and label == "人机验证":
        detail = "Google 搜索弹出验证码,该 IP 已被 Google 标记"
    return {"status": st, "label": label, "region": region, "detail": detail}


def check_netflix(px, mode, timeout):
    # 81280792 = 自制剧(全区都有);70143836 = 非自制剧(仅完整解锁地区可看)
    r1 = fetch(px, mode, "https://www.netflix.com/title/81280792", timeout)
    if r1.status == 403:
        return {"status": "no", "label": "不支持", "region": "",
                "detail": "Netflix 拒绝了这个出口 IP(HTTP 403),通常是被识别成代理 / 机房 IP。换 IP 再测。"}
    m = re.search(r'"(?:requestCountry|currentCountry)":\{?"?(?:id"?:"?)?([A-Z]{2})"', r1.text) \
        or re.search(r"netflix\.com/([a-z]{2})(?:-[a-z]{2})?/", r1.url)
    region = m.group(1).upper() if m else ""
    st, label, detail = classify(r1)
    if st != "ok":
        return {"status": st, "label": label, "region": region, "detail": detail}
    r2 = fetch(px, mode, "https://www.netflix.com/title/70143836", timeout)
    if r2.status == 404:
        return {"status": "warn", "label": "仅自制剧", "region": region,
                "detail": "只能看 Netflix 自制内容"}
    return {"status": "ok", "label": "支持", "region": region, "detail": "完整解锁"}


# ──────────────────────────── 站点清单 ────────────────────────────
# 同目录放一个 sites.json({"sites": [...]},格式同 DEFAULT_SITES)可以替换默认清单。

HERE = os.path.dirname(os.path.abspath(__file__))
SITES_FILE = os.path.join(HERE, "sites.json")

# 有专项检测(看地区 / 会员是否可用)的站点;其余站点只看能不能正常打开
SPECIAL_CHECKS = {
    "chatgpt": check_chatgpt, "claude": check_claude, "gemini": check_gemini,
    "tiktok": check_tiktok, "youtube": check_youtube, "google": check_google,
    "netflix": check_netflix,
}

DEFAULT_SITES = [
    {"id": "chatgpt", "group": "AI 工具", "name": "ChatGPT", "domains": ["chatgpt.com", "openai.com"]},
    {"id": "claude", "group": "AI 工具", "name": "Claude", "domains": ["claude.ai", "anthropic.com"]},
    {"id": "gemini", "group": "AI 工具", "name": "Gemini", "domains": ["gemini.google.com"]},
    {"id": "tiktok", "group": "社交媒体", "name": "TikTok", "domains": ["tiktok.com"]},
    {"id": "youtube", "group": "社交媒体", "name": "YouTube Premium", "domains": ["youtube.com"]},
    {"id": "facebook", "group": "社交媒体", "name": "Facebook", "url": "https://www.facebook.com/", "domains": ["facebook.com"]},
    {"id": "instagram", "group": "社交媒体", "name": "Instagram", "url": "https://www.instagram.com/", "domains": ["instagram.com"]},
    {"id": "x", "group": "社交媒体", "name": "X (Twitter)", "url": "https://x.com/", "region_host": "x.com", "domains": ["x.com", "twitter.com"]},
    {"id": "linkedin", "group": "社交媒体", "name": "LinkedIn", "url": "https://www.linkedin.com/", "domains": ["linkedin.com"]},
    {"id": "reddit", "group": "社交媒体", "name": "Reddit", "url": "https://www.reddit.com/", "domains": ["reddit.com"]},
    {"id": "telegram", "group": "通讯", "name": "Telegram Web", "url": "https://web.telegram.org/a/", "domains": ["telegram.org", "web.telegram.org"]},
    {"id": "whatsapp", "group": "通讯", "name": "WhatsApp Web", "url": "https://web.whatsapp.com/", "domains": ["whatsapp.com", "web.whatsapp.com"]},
    {"id": "discord", "group": "通讯", "name": "Discord", "url": "https://discord.com/", "region_host": "discord.com", "domains": ["discord.com"]},
    {"id": "google", "group": "搜索与办公", "name": "Google 搜索", "domains": ["google.com"]},
    {"id": "microsoft", "group": "搜索与办公", "name": "Outlook / Microsoft", "url": "https://login.microsoftonline.com/",
     "domains": ["microsoftonline.com", "outlook.com", "live.com", "hotmail.com", "microsoft.com"]},
    {"id": "paypal", "group": "支付", "name": "PayPal", "url": "https://www.paypal.com/", "domains": ["paypal.com"]},
    {"id": "stripe", "group": "支付", "name": "Stripe", "url": "https://checkout.stripe.com/", "domains": ["stripe.com"]},
    {"id": "amazon", "group": "电商", "name": "Amazon", "url": "https://www.amazon.com/", "domains": ["amazon.com"]},
    {"id": "ebay", "group": "电商", "name": "eBay", "url": "https://www.ebay.com/", "domains": ["ebay.com"]},
    {"id": "etsy", "group": "电商", "name": "Etsy", "url": "https://www.etsy.com/", "domains": ["etsy.com"]},
    {"id": "walmart", "group": "电商", "name": "Walmart", "url": "https://www.walmart.com/", "domains": ["walmart.com"]},
    {"id": "irctc", "group": "其他", "name": "IRCTC 印度铁路", "url": "https://www.irctc.co.in/nget/train-search", "domains": ["irctc.co.in"]},
    {"id": "netflix", "group": "流媒体", "name": "Netflix", "domains": ["netflix.com"]},
]


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


_CACHE = {"mtime": None, "sites": [], "by_id": {}}

# 团队版把共享的自定义网站挂到这里:返回 [{id, group, name, url, domains, ...}]
EXTRA_SITES = None


def _registry():
    """读 sites.json;文件改了自动重新加载,不用重启。"""
    mt = tuple(os.path.getmtime(f) if os.path.exists(f) else 0
               for f in (SITES_FILE,))
    if mt == _CACHE["mtime"]:
        return _with_extra(_CACHE)
    data = _load_json(SITES_FILE, {})
    sites = data.get("sites") if isinstance(data, dict) else None
    sites = sites or DEFAULT_SITES
    by_id = {}
    for s in sites:
        fn = SPECIAL_CHECKS.get(s["id"]) or (_generic(s["url"], s.get("region_host")) if s.get("url") else None)
        if fn:
            by_id[s["id"]] = dict(s, check=fn)
    _CACHE.update(mtime=mt, sites=[s for s in sites if s["id"] in by_id], by_id=by_id)
    return _with_extra(_CACHE)


def _with_extra(base):
    """叠加团队共享的自定义网站(每次现取,别人刚加的马上能看到)。"""
    if not EXTRA_SITES:
        return base
    extra = [dict(s, check=_generic(s["url"])) for s in EXTRA_SITES() if s.get("url")]
    if not extra:
        return base
    reg = dict(base)
    reg["sites"] = base["sites"] + extra
    reg["by_id"] = dict(base["by_id"], **{s["id"]: s for s in extra})
    return reg


def site_list():
    out = []
    for s in _registry()["sites"]:
        out.append({"id": s["id"], "group": s["group"], "name": s["name"],
                    "custom": bool(s.get("custom")),
                    "added_by": s.get("added_by", ""), "url": s.get("url", "")})
    return out


def _parse(payload):
    line = str(payload.get("proxy") or "").strip()
    px = core.parse_proxy(line)
    try:
        timeout = float(payload.get("timeout") or 12)
    except (TypeError, ValueError):
        timeout = 12
    return px, min(max(timeout, 3), 60)


def _probe_mode(px, mode, timeout):
    t0 = time.perf_counter()
    try:
        r = fetch(px, mode, "https://ipinfo.io/json", timeout, follow=0,
                  headers={"Accept": "application/json"})
        d = json.loads(r.text) if r.status == 200 else {}
        return {"ok": True, "mode": mode, "ms": (time.perf_counter() - t0) * 1000,
                "exit": {"ip": d.get("ip", ""), "country": d.get("country", ""),
                         "city": d.get("city", ""), "org": d.get("org", "")}}
    except TunnelError as e:
        return {"ok": False, "mode": mode, "error": str(e), "auth": e.auth}
    except Exception as e:
        return {"ok": False, "mode": mode, "error": core.explain(e)}


def prepare(payload):
    """探测 HTTP 隧道 / SOCKS5 哪些可用(auto 时两种都测),顺便拿出口 IP。"""
    try:
        px, timeout = _parse(payload)
    except ValueError as e:
        return {"ok": False, "error": f"代理格式不对:{e}"}
    want = payload.get("mode") or "auto"
    modes = ["http", "socks5"] if want == "auto" else [want]
    with ThreadPoolExecutor(len(modes)) as ex:
        probes = list(ex.map(lambda m: _probe_mode(px, m, timeout), modes))
    good = [p for p in probes if p["ok"]]
    if not good:
        return {"ok": False, "error": ";".join(
            f"{p['mode'].upper()}:{p['error']}" for p in probes)}
    return {"ok": True, "modes": [p["mode"] for p in good], "exit": good[0]["exit"],
            "proxy": f"{px.host}:{px.port}",
            "failed": {p["mode"]: p["error"] for p in probes if not p["ok"]}}


def _fail(kind, tech, timeout):
    label, reason, advice = FAIL_KINDS.get(kind, FAIL_KINDS["other"])
    t = f"{min(timeout, CONNECT_TIMEOUT) if kind in ('tunnel_timeout', 'tls_timeout') else timeout:g}"
    return {"status": "fail", "kind": kind, "label": label,
            "detail": (reason or tech).replace("{t}", t), "advice": advice.replace("{t}", t),
            "tech": tech}


def _run_once(fn, px, mode, timeout):
    try:
        return fn(px, mode, timeout)
    except TunnelError as e:
        return _fail(e.kind, str(e), timeout)
    except ssl.SSLError as e:
        return _fail("tls_cut", f"TLS 错误:{e}", timeout)
    except socket.timeout:
        return _fail("page_timeout", "超时", timeout)
    except Exception as e:
        return _fail("other", core.explain(e), timeout)


def _run_mode(fn, px, mode, timeout):
    t1 = time.perf_counter()
    res = _run_once(fn, px, mode, timeout)
    if res["status"] == "fail" and time.perf_counter() - t1 < 3:
        res = _run_once(fn, px, mode, timeout)  # 很快就断的多半是偶发,重试一次
    res["via"] = mode
    return res


_RACE_POOL = ThreadPoolExecutor(max_workers=32)


def run_site(payload):
    """测一个站点。modes 有两种协议时同时测,先拿到非失败结果的为准;都失败才报失败。"""
    sid = str(payload.get("site") or "")
    site = _registry()["by_id"].get(sid)
    if not site:
        return {"site": sid, "status": "fail", "label": "未知站点", "detail": ""}
    try:
        px, timeout = _parse(payload)
    except ValueError as e:
        return {"site": sid, "status": "fail", "label": "格式错误", "detail": str(e)}
    modes = [m for m in (payload.get("modes") or ["http", "socks5"])
             if m in ("http", "socks5")] or ["http", "socks5"]
    t0 = time.perf_counter()
    futs = [_RACE_POOL.submit(_run_mode, site["check"], px, m, timeout) for m in modes]
    res, fails = None, []
    for f in as_completed(futs):
        r = f.result()
        if r["status"] != "fail":
            res = r
            break
        fails.append(r)
    if res is None:
        # 两种协议都失败:挑最能说明问题的原因做结论,两边的技术细节都留着
        fails.sort(key=lambda r: _KIND_ORDER.index(r.get("kind", "other")))
        res = dict(fails[0])
        res["tech"] = ";".join(f"{r['via'].upper()}:{r.get('tech', '')}" for r in
                               sorted(fails, key=lambda r: modes.index(r["via"])))
        kinds = {r.get("kind") for r in fails}
        if len(fails) > 1 and len(kinds) > 1:
            res["detail"] += "(" + ";".join(
                f"{r['via'].upper()}:{r['label']}" for r in sorted(fails, key=lambda r: modes.index(r["via"]))) + ")"
    res.setdefault("region", "")
    res.update({"site": sid, "ms": (time.perf_counter() - t0) * 1000,
                "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    return res
