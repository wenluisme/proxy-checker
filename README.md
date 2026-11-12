# 代理测试台 Proxy Tester

一个只用 Python 标准库写的代理检测工具，无需安装任何第三方依赖。

- **代理检测**：测试账密代理在 HTTP / HTTPS / SOCKS5 三种协议下能否认证、能否连通，并显示出口 IP 的国家、城市、运营商和时区。
- **网站解锁**：经代理访问常用网站（AI 工具、社交媒体、搜索、支付、电商、流媒体等），判断能否正常打开、是否有地区限制、是否触发人机验证，失败时给出白话原因和建议。
- **网页界面**：本机模式免登录；团队模式（`--server`）支持账号登录、共享自定义网站、每人一份测试记录。
- **MCP 服务**：`proxy_mcp.py` 提供 `test_proxy` / `lookup_ip` / `test_unlock` 三个工具，可接入 Claude 等 AI 助手。

## 运行

```bash
python3 proxy_web.py                 # 本机模式，自动打开浏览器
python3 proxy_test.py 主机:端口:用户名:密码   # 命令行测试
```

代理格式：`主机:端口:用户名:密码`、`用户名:密码@主机:端口` 或 `http://用户名:密码@主机:端口`。

### 可选环境变量

| 变量 | 作用 |
| --- | --- |
| `PROXY_TEST_DEFAULT_PORT` / `PROXY_TEST_DEFAULT_USER` / `PROXY_TEST_DEFAULT_PASS` | 只填一个 IP 时使用的默认端口和账密 |
| `IPINFO_TOKEN` | ipinfo.io token，提高 IP 归属地查询额度（不设也能用） |
| `PROXY_TESTER_DATA` | 数据目录（默认 `./data`） |
| `PROXY_TEST_NO_BYPASS=1` | 关闭「绕过本机 TUN 模式 VPN 直连代理」 |

## 团队模式

```bash
python3 team.py adduser 管理员用户名 --admin
python3 proxy_web.py --server --host 127.0.0.1 --port 7799
```

请放在 HTTPS 反向代理（Caddy / Nginx）后面使用。团队模式禁止测试内网地址。

## 自定义网站清单

在同目录放一个 `sites.json`（`{"sites": [...]}`，格式同 `unlock_check.py` 里的 `DEFAULT_SITES`）即可替换默认清单。

## 说明

本工具只用于测试你自己拥有或已获授权使用的代理。检测结果基于各网站公开页面的响应，仅供参考。
