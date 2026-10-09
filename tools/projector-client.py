"""Launch the original Flash client in the Adobe projector using a login from the command line or MKO_Client/config.json.

Usage: projector-client.py [<username> <password>] [--dry-run] [--api-base URL] [--movie-base URL] [--game-port PORT]
With no credentials, the dev_account in MKO_Client/config.json is used. Passwords are never printed.
"""
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import http.cookiejar

WEB = "http://127.0.0.1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTOR = os.path.join(ROOT, "MKO_Client", "flash-projector", "flashplayer363.exe")
CONFIG = os.path.join(ROOT, "MKO_Client", "config.json")

sys.path.insert(0, "tools")
import parse_flashvars as pf
import random
import time


def login_legacy(user, password):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    data = urllib.parse.urlencode(
        {"Action": "Login", "uName": user, "uPas": password}
    ).encode()
    req = urllib.request.Request(
        WEB + "/AjaxRequest/AccountHandler.php", data=data, method="POST"
    )
    with opener.open(req, timeout=20) as r:
        print("login says:", r.read().decode("utf-8", "replace").strip()[:60])
    with opener.open(WEB + "/Gamelogin.php", timeout=20) as r:
        html = r.read().decode("utf-8", "replace")
    if "Main.swf" not in html:
        raise SystemExit("Gamelogin gate refused (bad login?)")
    return html


def login_api(api_base, user, password):
    """New stack: Python web API. Returns the gamesession dict."""
    import json

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    data = urllib.parse.urlencode(
        {"Action": "Login", "uName": user, "uPas": password}
    ).encode()
    req = urllib.request.Request(
        api_base + "/AjaxRequest/AccountHandler.php", data=data, method="POST"
    )
    with opener.open(req, timeout=20) as r:
        print("login says:", r.read().decode("utf-8", "replace").strip()[:60])
    with opener.open(api_base + "/gamesession.php", timeout=20) as r:
        sess = json.load(r)
    if not sess.get("ok"):
        raise SystemExit("gamesession refused: %r" % (sess,))
    return sess


def api_flashvars(s):
    """Mirror client/src/flashvars.js toFlashVars exactly."""
    lcid = format(int(time.time() * 1000), "x") + format(
        random.randint(0, 999), "x"
    )
    esc = urllib.parse.quote
    base = "http://127.0.0.1/"
    return {
        "lcid": lcid,
        "pay": esc(base),
        "cm": esc(base),
        "uid": s["uid"],
        "pid": s["pid"],
        "t": str(s["t"]),
        "seid": s["seid"],
        "sport": str(s["sport"]),
        "ip": s["ip"],
        "who": "",
        "sign": s["sign"],
        "cminfo": "null",
        "bbsurl": esc(base),
        "homeurl": esc(base),
        "infourl": esc(base),
        "shownav": esc("0"),
        "bugurl": esc(base),
        "suggesturl": esc(base),
        "saveUrl": esc(base),
        "pl": "null",
        "client": "null",
        "microClientURL": esc(base),
        "gmpanel": "0",
        "server": "null",
        "gameid": "null",
    }


def flashvars_of(html):
    m = pf.SRC_PAT.search(html)
    if not m:
        raise SystemExit("flashvars block not found")
    out = {}
    for key, squote, dquote in pf.PAIR_PAT.findall(m.group(1)):
        out[key] = (squote or dquote).replace("\\'", "'")
    # lcid is JS-generated in the original page; replicate it
    out["lcid"] = format(int(time.time() * 1000), "x") + format(
        random.randint(0, 999), "x"
    )
    return out


def load_dev_account(path=CONFIG):
    """Return (username, password) from the dev_account block of the config file."""
    import json

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise SystemExit("config not found: %s (pass <username> <password> instead)" % path)
    except json.JSONDecodeError as e:
        raise SystemExit("config is not valid JSON: %s (line %d)" % (path, e.lineno))
    acct = data.get("dev_account") if isinstance(data, dict) else None
    if not isinstance(acct, dict) or not acct.get("username") or not acct.get("password"):
        raise SystemExit("config needs dev_account.username and dev_account.password: %s" % path)
    return acct["username"], acct["password"]


def credentials(argv=None, path=CONFIG):
    """Return the positional credentials if given, else the dev account."""
    argv = sys.argv if argv is None else argv
    if len(argv) >= 3 and not argv[1].startswith("--") and not argv[2].startswith("--"):
        return argv[1], argv[2]
    return load_dev_account(path)


def apply_game_port(fv, argv):
    """Point the game socket at --game-port (e.g. the recorder) instead of the server's sport."""
    if '--game-port' in argv:
        i = argv.index('--game-port')
        fv['sport'] = str(int(argv[i + 1]))
    return fv


def argval(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
    return default


def build_movie_url(user, password, api_base=None, movie_base=None, argv=None):
    """Log in and return the Main.swf URL with signed flashvars; raises SystemExit on refusal."""
    argv = sys.argv if argv is None else argv
    if api_base:
        sess = login_api(api_base, user, password)
        fv = apply_game_port(api_flashvars(sess), argv)
        return (movie_base or WEB + "/res") + "/Main.swf?" + urllib.parse.urlencode(fv)
    html = login_legacy(user, password)
    fv = apply_game_port(flashvars_of(html), argv)
    return (movie_base or WEB + "/res") + "/Main.swf?" + urllib.parse.urlencode(fv)


def launch_projector(url):
    """Start the Flash projector on the movie URL."""
    subprocess.Popen([PROJECTOR, url])


def main():
    user, password = credentials()
    url = build_movie_url(user, password, argval("--api-base"), argval("--movie-base"))
    if "--dry-run" in sys.argv:
        print("movie URL ready (not launching)")
        return
    print("launching projector...")
    launch_projector(url)


if __name__ == "__main__":
    main()
