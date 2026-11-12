#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代理测试台 MCP 服务器(stdio)—— 让 AI 助手直接调用代理测试和 IP 归属地查询。

一键接入 Claude Desktop:
    python proxy_mcp.py --install-claude      (写入 Claude 配置后重启 Claude 即可)

其他 MCP 客户端(Cursor 等)手动配置:
    command: 本机 python 路径(推荐用本文件夹 runtime-win\\python.exe)
    args:    ["-B", "本文件的绝对路径"]

工具:
    test_proxy  测试帐密代理在 HTTP/HTTPS/SOCKS5 下能否认证连通,含出口归属地
    lookup_ip   查询 IP 归属地(中英双语)
"""

import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import proxy_web  # 复用 run_test / lookup_ip
import unlock_check  # 解锁测试


def _sites():
    """当前解锁测试清单:[(id, 分组, 名称, 备注)]。"""
    return [(s["id"], s["group"], s["name"], "") for s in unlock_check.site_list()]

SERVER_INFO = {"name": "proxy-tester", "version": "3.2"}

TOOLS = [
    {
        "name": "test_proxy",
        "description": (
            "测试帐密代理是否可用:分别检测 HTTP / HTTPS / SOCKS5 三种协议下"
            "这套帐密能否认证、能否连通,并返回出口 IP 与归属地;"
            "可选检测指定网站能否通过该代理访问。"
            "代理格式:主机:端口:用户名:密码,或 用户名:密码@主机:端口,"
            "或 http://用户名:密码@主机:端口。"
            "只传一个 IP 时,使用环境变量 PROXY_TEST_DEFAULT_PORT / USER / PASS 配置的默认端口和帐密。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "proxies": {
                    "type": "array", "items": {"type": "string"}, "maxItems": 10,
                    "description": "要测试的代理,一条一个字符串,最多 10 条",
                },
                "targets": {
                    "type": "array", "items": {"type": "string"}, "maxItems": 3,
                    "description": "可选:要验证能否通过代理访问的网站网址,最多 3 个",
                },
                "timeout": {
                    "type": "number",
                    "description": "每步超时秒数,默认 10,最大 15",
                },
            },
            "required": ["proxies"],
        },
    },
    {
        "name": "lookup_ip",
        "description": (
            "查询 IP 归属地,中英双语返回:中文国家名与省市、英文城市地区、"
            "运营商、时区。数据来自 ipinfo(含自动备用源)。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ips": {
                    "type": "array", "items": {"type": "string"}, "maxItems": 20,
                    "description": "要查询的 IP,最多 20 个;传空字符串表示查本机出口",
                },
            },
            "required": ["ips"],
        },
    },
    {
        "name": "test_unlock",
        "description": (
            "解锁测试:经一条代理访问客户常用网站,判断每个网站是否支持(能正常打开)、"
            "不支持(地区限制 / 拒绝该 IP)、需要人机验证(Cloudflare / 验证码 / 风控),"
            "并给出网站识别到的地区;失败时给出白话原因和建议。"
            "默认测全部站点,当前为:"
            + "、".join(n for _, _, n, _ in _sites()) + "。"
            "可用 sites 只测其中几个(传站点 id 或名称)。"
            "代理格式同 test_proxy。"
            "协议默认自动选择(每个站点同时走 HTTP 隧道和 SOCKS5,哪个先成功用哪个)。"
            "单次调用约 50 秒内返回;没测完的站点会在后台继续测,"
            "按返回文字里的提示用 sites 再调用一次即可拿到结果(10 分钟内的结果会直接复用)。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "proxy": {"type": "string", "description": "要测试的代理,一条"},
                "sites": {
                    "type": "array", "items": {"type": "string"},
                    "description": "可选:只测这些站点。可用 id:"
                                   + ", ".join(i for i, _, _, _ in _sites()),
                },
                "mode": {"type": "string", "enum": ["auto", "http", "socks5"],
                         "description": "协议,默认 auto"},
                "timeout": {"type": "number", "description": "每个网站超时秒数,默认 10,最大 15"},
                "fresh": {"type": "boolean",
                          "description": "true 时忽略 10 分钟内的缓存结果,全部重测"},
            },
            "required": ["proxy"],
        },
    },
]

STEP_NAME = {"dns": "解析", "tcp": "连接", "http": "HTTP",
             "https": "HTTPS", "socks5": "SOCKS5", "web": "网站"}
VERDICT_NAME = {"full": "可用", "partial": "部分可用", "exit-blocked": "网站不通",
                "auth-fail": "认证失败", "fail": "不可用", "bad-input": "格式错误"}


def mask_line(line):
    """展示时把密码打码(与网页版同规则)。"""
    if "://" not in line:
        parts = line.split(":")
        if len(parts) >= 4 and parts[1].isdigit():
            return ":".join(parts[:3]) + ":••••"
    at = line.rfind("@")
    if at > -1:
        head = line[:at]
        start = head.find("://") + 3 if "://" in head else 0
        colon = head.find(":", start)
        if colon > -1:
            return head[:colon + 1] + "••••" + line[at:]
    return line


def fmt_ms(ms):
    if ms is None:
        return ""
    return f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms:.0f}ms"


def fmt_test(r):
    lines = [f"代理 {mask_line(r.get('input', ''))}"]
    if r.get("auth_source"):
        lines.append("账密来源:环境变量里配置的默认端口和账密")
    lines.append(f"结论:{VERDICT_NAME.get(r.get('verdict'), r.get('verdict'))}"
                 f" —— {r.get('verdict_text', '')}")
    protos = []
    for s in r.get("steps", []):
        if s.get("key") not in ("http", "https", "socks5"):
            continue
        if s.get("ok"):
            protos.append(f"{STEP_NAME[s['key']]} ✓ {fmt_ms(s.get('ms'))}")
        else:
            protos.append(f"{STEP_NAME[s['key']]} ✗ {s.get('error', '不通')}")
    if protos:
        lines.append("协议:" + " | ".join(protos))
    e = r.get("exit") or {}
    if e.get("ip"):
        loc = " ".join(x for x in (e.get("cn"), e.get("en")) if x)
        org = f"({e['org']})" if e.get("org") else ""
        lines.append(f"出口:{e['ip']} {loc} {org}".rstrip())
    for t in r.get("targets", []):
        if t.get("ok"):
            lines.append(f"网站 {t['url']} ✓ HTTP {t.get('status')} {fmt_ms(t.get('ms'))}")
        else:
            lines.append(f"网站 {t['url']} ✗ {t.get('error', '失败')}")
    return "\n".join(lines)


def fmt_ip(d):
    ip = d.get("ip") or "本机出口"
    if d.get("error"):
        return f"{ip}:查询失败({d['error']})"
    if d.get("bogon"):
        return f"{ip}:内网 / 保留地址,不是公网 IP"
    loc = " / ".join(x for x in (d.get("loc_cn"), d.get("loc_en")) if x) or "-"
    parts = [loc]
    org = d.get("org") or d.get("as_name") or d.get("asn")
    if org:
        parts.append(str(org))
    if d.get("timezone"):
        parts.append(d["timezone"])
    notes = []
    if d.get("_source") == "lite":
        notes.append("Lite 数据,仅国家级")
    elif d.get("_source") == "ip-api":
        notes.append("备用源")
    if d.get("_cached"):
        notes.append("缓存")
    tail = f"({','.join(notes)})" if notes else ""
    return f"{ip}:{' · '.join(parts)} {tail}".rstrip()


# 单次工具调用的总时间预算:留在 MCP 客户端默认 60 秒超时之内
CALL_BUDGET = 50


def _run_budget(items, worker, fmt_timeout, max_workers):
    """并发执行,超出预算的条目单独标记超时;不等待掉队线程。"""
    ex = ThreadPoolExecutor(max_workers=max_workers)
    futs = [(item, ex.submit(worker, item)) for item in items]
    deadline = time.monotonic() + CALL_BUDGET
    out = []
    for item, f in futs:
        remain = max(0.1, deadline - time.monotonic())
        try:
            out.append(f.result(timeout=remain))
        except FuturesTimeout:
            out.append(fmt_timeout(item))
        except Exception as e:
            out.append(f"{item}:执行出错({e})")
    ex.shutdown(wait=False)
    return out


def call_tool(name, args):
    """返回 (文本, 是否错误)。"""
    if name == "test_proxy":
        if not isinstance(args.get("proxies"), list):
            return "参数 proxies 必须是数组,每条代理一个字符串", True
        if args.get("targets") is not None and not isinstance(args["targets"], list):
            return "参数 targets 必须是数组,每个网址一个字符串", True
        proxies = [str(p).strip() for p in args["proxies"] if str(p).strip()][:10]
        if not proxies:
            return "proxies 里没有可测试的代理", True
        targets = [str(t).strip() for t in (args.get("targets") or [])
                   if str(t).strip()][:3]
        try:
            timeout = min(max(float(args.get("timeout") or 10), 2), 15)
        except (TypeError, ValueError):
            timeout = 10

        def one(p):
            return fmt_test(proxy_web.run_test(
                {"proxy": p, "targets": targets, "timeout": timeout}))

        def timed_out(p):
            return (f"代理 {mask_line(p)}\n"
                    f"结论:测试超时,已中断(超过 {CALL_BUDGET} 秒)")
        texts = _run_budget(proxies, one, timed_out, max_workers=len(proxies))
        return "\n\n".join(texts), False

    if name == "lookup_ip":
        if not isinstance(args.get("ips"), list):
            return "参数 ips 必须是数组,每个 IP 一个字符串", True
        ips = [str(i).strip() for i in args["ips"]][:20]
        if not ips:
            ips = [""]

        def one(ip):
            return fmt_ip(proxy_web.lookup_ip({"ip": ip}))

        def timed_out(ip):
            return f"{ip or '本机出口'}:查询超时,已中断"
        texts = _run_budget(ips, one, timed_out,
                            max_workers=min(8, len(ips)))
        return "\n".join(texts), False

    if name == "test_unlock":
        return _call_unlock(args)

    return f"未知工具:{name}", True


UNLOCK_WORKERS = 9  # 每个站点同时走两种协议;再高会把单条代理打满,反而大面积失败
UNLOCK_CACHE_TTL = 600  # 秒;超时没测完的站点在后台继续测,结果缓存给下一次调用

# (代理, 站点id) -> {"t": 完成时间, "r": 结果} 或 {"pending": Future}
_UL_CACHE = {}
_UL_LOCK = threading.Lock()
_UL_POOL = ThreadPoolExecutor(max_workers=UNLOCK_WORKERS)
UL_MARK = {"ok": "✓", "no": "✗", "warn": "⚠", "fail": "?", "pend": "…"}


def _pick_sites(wanted):
    if not wanted:
        return _sites(), []
    picked, unknown = [], []
    for w in wanted:
        key = str(w).strip().lower()
        if not key:
            continue
        hit = [s for s in _sites()
               if key == s[0] or key == s[2].lower() or key in s[2].lower()]
        if hit:
            picked += [h for h in hit if h not in picked]
        else:
            unknown.append(str(w))
    return picked, unknown


def _call_unlock(args):
    proxy = str(args.get("proxy") or "").strip()
    if not proxy:
        return "参数 proxy 不能为空", True
    if args.get("sites") is not None and not isinstance(args["sites"], list):
        return "参数 sites 必须是数组", True
    sites, unknown = _pick_sites(args.get("sites"))
    if not sites:
        return "没有匹配的站点。可用 id:" + ", ".join(s[0] for s in _sites()), True
    try:
        timeout = min(max(float(args.get("timeout") or 10), 3), 15)
    except (TypeError, ValueError):
        timeout = 10
    mode = args.get("mode") if args.get("mode") in ("http", "socks5") else "auto"

    t0 = time.monotonic()
    # 出口 IP 预检和站点测试并行,不让站点等预检
    prep_ex = ThreadPoolExecutor(max_workers=1)
    prep_f = prep_ex.submit(unlock_check.prepare, {"proxy": proxy, "mode": mode, "timeout": timeout})
    prep_ex.shutdown(wait=False)
    modes = ["http", "socks5"] if mode == "auto" else [mode]

    def job(site):
        r = unlock_check.run_site({"proxy": proxy, "modes": modes,
                                   "site": site[0], "timeout": timeout})
        with _UL_LOCK:
            _UL_CACHE[(proxy, site[0])] = {"t": time.monotonic(), "r": r}
        return r

    # 复用 10 分钟内已测完 / 正在后台测的结果;其余提交到共享线程池(限并发,避免打满代理)
    fresh = bool(args.get("fresh"))
    futs = {}
    with _UL_LOCK:
        for site in sites:
            c = _UL_CACHE.get((proxy, site[0]))
            if c and not fresh and "r" in c and time.monotonic() - c["t"] < UNLOCK_CACHE_TTL:
                continue
            if c and "pending" in c and not c["pending"].done():
                futs[site[0]] = c["pending"]
                continue
            f = _UL_POOL.submit(job, site)
            _UL_CACHE[(proxy, site[0])] = {"pending": f}
            futs[site[0]] = f
    deadline = t0 + CALL_BUDGET
    results, unfinished = {}, []
    for site in sites:
        f = futs.get(site[0])
        if f is None:
            with _UL_LOCK:
                results[site[0]] = _UL_CACHE[(proxy, site[0])]["r"]
            continue
        try:
            results[site[0]] = f.result(timeout=max(0.1, deadline - time.monotonic()))
        except FuturesTimeout:
            unfinished.append(site[0])
            results[site[0]] = {"status": "pend", "label": "还在测试",
                                "detail": "后台继续测试中,稍后再调用一次即可拿到结果"}
        except Exception as ex_:
            results[site[0]] = {"status": "fail", "label": "执行出错", "detail": str(ex_)}

    try:
        prep = prep_f.result(timeout=max(0.1, deadline - time.monotonic()))
    except FuturesTimeout:
        prep = {"ok": False, "error": "获取出口 IP 超时"}
    if not prep.get("ok") and all(results[s[0]]["status"] in ("fail", "pend") for s in sites):
        return f"代理 {mask_line(proxy)}\n代理连不上:{prep.get('error', '')}", False
    e = prep.get("exit") or {}
    loc = " ".join(x for x in (e.get("country"), e.get("city")) if x)
    lines = [f"代理 {mask_line(proxy)}",
             f"出口:{e.get('ip', '?')} {loc} {e.get('org', '')}".rstrip(),
             "可用协议:" + ("、".join(m.upper() for m in prep.get("modes") or []) or "未知")]
    counts = {"ok": 0, "no": 0, "warn": 0, "fail": 0, "pend": 0}
    group = None
    for sid, g, name, _ in sites:
        r = results[sid]
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if g != group:
            group = g
            lines.append(f"\n【{g}】")
        extra = []
        if r.get("region"):
            extra.append(r["region"])
        if r.get("via") and r["status"] not in ("fail", "pend"):
            extra.append(r["via"].upper())
        tag = f"[{' · '.join(extra)}]" if extra else ""
        detail = f" —— {r['detail']}" if r.get("detail") else ""
        lines.append(f"{UL_MARK.get(r['status'], '?')} {name}:{r.get('label', '')}{tag}{detail}")
        if r.get("advice"):
            lines.append(f"    建议:{r['advice']}")
    lines.append(f"\n汇总:支持 {counts['ok']},不支持 {counts['no']},"
                 f"还在测试 {counts['pend']},"
                 f"需验证/受限 {counts['warn']},测试失败 {counts['fail']}"
                 f"(共 {len(sites)} 个,用时 {time.monotonic() - t0:.0f}s)")
    if unfinished:
        lines.append(f"还有 {len(unfinished)} 个站点在后台测试中。请等约 30 秒后用同一个 proxy、"
                     f"sites={json.dumps(unfinished)} 再调用一次 test_unlock 拿到结果。")
    if unknown:
        lines.append("未识别的站点:" + "、".join(unknown))
    return "\n".join(lines), False


# ──────────────────────────── stdio 协议 ────────────────────────────

def serve_stdio():
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    out_lock = threading.Lock()

    def send(obj):
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        with out_lock:
            stdout.write(data)
            stdout.flush()

    def handle_call(mid, params):
        try:
            text, is_err = call_tool(params.get("name"),
                                     params.get("arguments") or {})
        except Exception as e:  # 工具内部异常不拖垮服务
            text, is_err = f"执行出错:{e}", True
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": text}],
            "isError": bool(is_err)}})

    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        mid = msg.get("id")
        method = msg.get("method")

        if method == "initialize":
            client_ver = (msg.get("params") or {}).get("protocolVersion")
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": client_ver or "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
                "instructions": ("用 test_proxy 测帐密代理在 HTTP/HTTPS/SOCKS5 "
                                 "下的连通性,用 lookup_ip 查 IP 归属地,"
                                 "用 test_unlock 测代理能否打开 ChatGPT、TikTok、"
                                 "Netflix 等客户常用网站(解锁测试)。"),
            }})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            # 长任务放到工作线程,保证 ping / 后续请求不被阻塞
            threading.Thread(target=handle_call,
                             args=(mid, msg.get("params") or {}),
                             daemon=True).start()
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32601, "message": f"method not found: {method}"}})
        # 无 id 的通知直接忽略
    os._exit(0)  # 宿主关闭 stdin 即退出,不等未完成的工具线程


# ──────────────────────────── Claude Desktop 一键接入 ────────────────────────────

def install_claude():
    if os.name == "nt":
        cfg_dir = os.path.join(os.environ.get("APPDATA", ""), "Claude")
    elif sys.platform == "darwin":
        cfg_dir = os.path.expanduser("~/Library/Application Support/Claude")
    else:
        cfg_dir = os.path.expanduser("~/.config/Claude")
    cfg_path = os.path.join(cfg_dir, "claude_desktop_config.json")

    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, "proxy_mcp.py")
    bundled = os.path.join(here, "runtime-win", "python.exe")
    cmd = bundled if (os.name == "nt" and os.path.isfile(bundled)) \
        else (sys.executable or "python3")

    data = {}
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except ValueError:
            backup = cfg_path + ".bak-" + time.strftime("%Y%m%d%H%M%S")
            shutil.copyfile(cfg_path, backup)
            print(f"原配置不是合法 JSON,已备份到 {backup},将重建配置")
            data = {}
    data.setdefault("mcpServers", {})["proxy-tester"] = {
        "command": cmd, "args": ["-B", script]}
    os.makedirs(cfg_dir, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("已写入:", cfg_path)
    print("重启 Claude Desktop 后,对话里即可直接让 AI 测代理、查 IP。")
    print("其他 MCP 客户端配置:command =", cmd, ' args = ["-B", "%s"]' % script)


if __name__ == "__main__":
    if "--install-claude" in sys.argv:
        install_claude()
    else:
        serve_stdio()
