# Proxy Tester

A proxy checking tool written with the Python standard library only — no third-party dependencies to install.

- **Proxy check**: tests whether an authenticated proxy can log in and connect over HTTP, HTTPS and SOCKS5, and shows the exit IP's country, city, ISP and time zone.
- **Site unlock test**: opens common websites through the proxy (AI tools, social media, search, payments, e-commerce, streaming, etc.) and reports whether each one loads, is region-restricted, or triggers a human-verification challenge, with a plain-language reason and suggestion when it fails.
- **Web UI**: local mode needs no login; team mode (`--server`) adds user accounts, shared custom sites, and per-user test history.
- **MCP server**: `proxy_mcp.py` exposes three tools — `test_proxy`, `lookup_ip` and `test_unlock` — for AI assistants such as Claude.

> The web UI and result messages are currently in Chinese.

## Usage

```bash
python3 proxy_web.py                          # local mode, opens your browser
python3 proxy_test.py host:port:user:password # command-line check
```

Supported proxy formats: `host:port:user:password`, `user:password@host:port`, or `http://user:password@host:port`.

### Optional environment variables

| Variable | Purpose |
| --- | --- |
| `PROXY_TEST_DEFAULT_PORT` / `PROXY_TEST_DEFAULT_USER` / `PROXY_TEST_DEFAULT_PASS` | Default port and credentials used when only an IP is entered |
| `IPINFO_TOKEN` | ipinfo.io token for a higher geolocation quota (works without it) |
| `PROXY_TESTER_DATA` | Data directory (default `./data`) |
| `PROXY_TEST_NO_BYPASS=1` | Disable connecting to the proxy directly around a local TUN-mode VPN |

## Team mode

```bash
python3 team.py adduser ADMIN_NAME --admin
python3 proxy_web.py --server --host 127.0.0.1 --port 7799
```

Run it behind an HTTPS reverse proxy (Caddy / Nginx). Team mode refuses to test private/internal network addresses.

## Custom site list

Put a `sites.json` file (`{"sites": [...]}`, same format as `DEFAULT_SITES` in `unlock_check.py`) next to the scripts to replace the default list.

## Disclaimer

Only test proxies you own or are authorized to use. Results are based on how each website's public pages respond and are for reference only.

## License

MIT
