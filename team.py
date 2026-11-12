"""团队版数据:账号、登录会话、共享的自定义解锁网站、个人测试记录、系统设置。

数据库默认在同目录 data/app.db(可用环境变量 PROXY_TESTER_DATA 指定目录)。

命令行(在服务器上开第一个管理员账号):
  python3 team.py adduser 用户名 --admin     # 会提示输入密码
  python3 team.py passwd 用户名              # 重置密码
  python3 team.py users                      # 列出账号
"""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("PROXY_TESTER_DATA") or os.path.join(HERE, "data")
DB_PATH = os.path.join(DATA_DIR, "app.db")

SESSION_DAYS = 30
HISTORY_KEEP = 100     # 每人保留最近多少条测试记录
PBKDF2_ROUNDS = 200_000

_LOCK = threading.Lock()
_CONN = None

SCHEMA = """
create table if not exists users(
  id integer primary key, username text unique not null collate nocase,
  pw_hash text not null, is_admin integer not null default 0,
  created_at integer not null, last_login integer);
create table if not exists sessions(
  token_hash text primary key, user_id integer not null, created_at integer not null,
  expires_at integer not null);
create table if not exists custom_sites(
  id integer primary key, name text not null, url text not null, grp text not null,
  added_by text not null, created_at integer not null);
create table if not exists history(
  id integer primary key, user_id integer not null, created_at integer not null,
  title text not null, summary text not null, data text not null);
create index if not exists history_user on history(user_id, id desc);
create table if not exists settings(key text primary key, value text not null);
"""


def db():
    global _CONN
    if _CONN is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _CONN = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        _CONN.row_factory = sqlite3.Row
        _CONN.executescript(SCHEMA)
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            pass
    return _CONN


def q(sql, args=(), one=False):
    with _LOCK:
        cur = db().execute(sql, args)
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def ex(sql, args=()):
    with _LOCK:
        cur = db().execute(sql, args)
        return cur.lastrowid


# ──────────────────────────── 账号 ────────────────────────────

def _hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return f"pbkdf2${PBKDF2_ROUNDS}${salt}${h}"


def _check_pw(pw, stored):
    try:
        _, rounds, salt, h = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(got, h)
    except (ValueError, TypeError):
        return False


def validate_new_password(pw):
    if len(pw or "") < 8:
        return "密码至少 8 位"
    return None


def create_user(username, password, admin=False):
    username = (username or "").strip()
    if not username or len(username) > 40 or any(c.isspace() for c in username):
        raise ValueError("用户名不能为空、不能有空格,最多 40 个字符")
    err = validate_new_password(password)
    if err:
        raise ValueError(err)
    if q("select 1 from users where username=?", (username,), one=True):
        raise ValueError("这个用户名已经存在")
    return ex("insert into users(username,pw_hash,is_admin,created_at) values(?,?,?,?)",
              (username, _hash_pw(password), 1 if admin else 0, int(time.time())))


def set_password(user_id, password):
    err = validate_new_password(password)
    if err:
        raise ValueError(err)
    ex("update users set pw_hash=? where id=?", (_hash_pw(password), user_id))
    ex("delete from sessions where user_id=?", (user_id,))  # 改密码后其他设备要重新登录


def delete_user(user_id):
    ex("delete from sessions where user_id=?", (user_id,))
    ex("delete from history where user_id=?", (user_id,))
    ex("delete from users where id=?", (user_id,))


def list_users():
    return [dict(r) for r in q("select id,username,is_admin,created_at,last_login from users order by id")]


def user_count():
    return q("select count(*) c from users", one=True)["c"]


# 登录失败限速:同一 IP 或同一用户名 10 分钟内失败 8 次就暂时锁住
_FAILS = {}


def _fail_key_blocked(key):
    now = time.time()
    lst = [t for t in _FAILS.get(key, []) if now - t < 600]
    _FAILS[key] = lst
    return len(lst) >= 8


def login(username, password, ip):
    keys = (f"ip:{ip}", f"u:{(username or '').lower()}")
    if any(_fail_key_blocked(k) for k in keys):
        return None, "失败次数太多,请 10 分钟后再试"
    u = q("select * from users where username=?", ((username or "").strip(),), one=True)
    if not u or not _check_pw(password or "", u["pw_hash"]):
        for k in keys:
            _FAILS.setdefault(k, []).append(time.time())
        time.sleep(0.5)
        return None, "用户名或密码不对"
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    ex("insert into sessions(token_hash,user_id,created_at,expires_at) values(?,?,?,?)",
       (hashlib.sha256(token.encode()).hexdigest(), u["id"], now, now + SESSION_DAYS * 86400))
    ex("update users set last_login=? where id=?", (now, u["id"]))
    ex("delete from sessions where expires_at<?", (now,))
    return token, None


def user_by_token(token):
    if not token:
        return None
    r = q("select u.id,u.username,u.is_admin from sessions s join users u on u.id=s.user_id "
          "where s.token_hash=? and s.expires_at>?",
          (hashlib.sha256(token.encode()).hexdigest(), int(time.time())), one=True)
    return dict(r) if r else None


def logout(token):
    ex("delete from sessions where token_hash=?", (hashlib.sha256((token or "").encode()).hexdigest(),))


# ──────────────────────────── 共享的自定义网站 ────────────────────────────

def custom_sites():
    """[{id, group, name, url, domains, custom, added_by}],给解锁测试用。"""
    out = []
    for r in q("select * from custom_sites order by id"):
        host = (urllib.parse.urlsplit(r["url"]).hostname or "").lower()
        out.append({"id": f"c{r['id']}", "group": r["grp"], "name": r["name"], "url": r["url"],
                    "domains": [host] if host else [], "custom": True, "added_by": r["added_by"]})
    return out


def normalize_url(url):
    url = (url or "").strip()
    if not url:
        raise ValueError("网址不能为空")
    if "://" not in url:
        url = "https://" + url
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname or "." not in u.hostname:
        raise ValueError("网址格式不对")
    # 解锁测试统一走 HTTPS
    return urllib.parse.urlunsplit(("https", u.netloc, u.path or "/", u.query, ""))


def add_custom_site(url, name, group, username):
    url = normalize_url(url)
    host = urllib.parse.urlsplit(url).hostname
    for r in q("select url,name from custom_sites"):
        if urllib.parse.urlsplit(r["url"]).hostname == host:
            raise ValueError(f"「{r['name']}」已经在常用网站里了")
    name = (name or "").strip() or host.replace("www.", "")
    group = (group or "").strip() or "自定义"
    rid = ex("insert into custom_sites(name,url,grp,added_by,created_at) values(?,?,?,?,?)",
             (name[:40], url, group[:20], username, int(time.time())))
    return f"c{rid}"


def delete_custom_site(sid, user):
    if not str(sid).startswith("c") or not str(sid)[1:].isdigit():
        raise ValueError("只有手动添加的网站可以删除")
    r = q("select added_by from custom_sites where id=?", (int(sid[1:]),), one=True)
    if not r:
        raise ValueError("网站不存在")
    if not user.get("is_admin") and r["added_by"] != user["username"]:
        raise ValueError("只有添加人或管理员可以删除")
    ex("delete from custom_sites where id=?", (int(sid[1:]),))


# ──────────────────────────── 个人测试记录 ────────────────────────────

def save_history(user_id, title, summary, data):
    blob = json.dumps(data, ensure_ascii=False)
    if len(blob) > 2_000_000:
        raise ValueError("记录太大")
    hid = ex("insert into history(user_id,created_at,title,summary,data) values(?,?,?,?,?)",
             (user_id, int(time.time()), (title or "")[:200], (summary or "")[:300], blob))
    ex("delete from history where user_id=? and id not in "
       "(select id from history where user_id=? order by id desc limit ?)", (user_id, user_id, HISTORY_KEEP))
    return hid


def update_history(user_id, hid, summary, data):
    ex("update history set summary=?, data=? where id=? and user_id=?",
       ((summary or "")[:300], json.dumps(data, ensure_ascii=False), hid, user_id))


def list_history(user_id, limit=50):
    return [dict(r) for r in q("select id,created_at,title,summary from history where user_id=? "
                               "order by id desc limit ?", (user_id, limit))]


def get_history(user_id, hid):
    r = q("select * from history where id=? and user_id=?", (hid, user_id), one=True)
    if not r:
        return None
    d = dict(r)
    d["data"] = json.loads(d["data"])
    return d


def delete_history(user_id, hid):
    ex("delete from history where id=? and user_id=?", (hid, user_id))


# ──────────────────────────── 设置 ────────────────────────────

def get_setting(key, default=None):
    r = q("select value from settings where key=?", (key,), one=True)
    return json.loads(r["value"]) if r else default


def set_setting(key, value):
    ex("insert into settings(key,value) values(?,?) on conflict(key) do update set value=excluded.value",
       (key, json.dumps(value, ensure_ascii=False)))


# ──────────────────────────── 命令行 ────────────────────────────

def _cli(argv):
    import getpass
    if len(argv) < 2 or argv[1] not in ("adduser", "passwd", "users"):
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "users":
        for u in list_users():
            print(f"{u['id']:>3}  {u['username']:20s} {'管理员' if u['is_admin'] else '成员'}")
        return 0
    if len(argv) < 3:
        print("缺少用户名")
        return 2
    pw = getpass.getpass("密码:")
    if pw != getpass.getpass("再输一次:"):
        print("两次密码不一致")
        return 1
    try:
        if cmd == "adduser":
            create_user(argv[2], pw, admin="--admin" in argv)
            print("已创建")
        else:
            u = q("select id from users where username=?", (argv[2],), one=True)
            if not u:
                print("没有这个用户")
                return 1
            set_password(u["id"], pw)
            print("已重置,该用户其他设备需要重新登录")
    except ValueError as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
