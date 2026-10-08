"""Launch the ORIGINAL client in genuine Adobe Flash projector (pre-killswitch).

Logs in via the supplied Apache/PHP pages, then opens
  http://127.0.0.1/res/Main.swf?<flashvars as query string>
in flashplayer 32.0.0.363. Flash parses SWF-URL query params into
loaderInfo.parameters, which is how the game gets uid/t/sign/seid/sport/ip.
Native TCP sockets go straight to Java :8008 (no bridge). Relative loads
(PlatformLoader.swf, assets/tg.swf) resolve against /res/ automatically.

Usage: projector-client.py <username> <password> [--dry-run]
       [--api-base URL] [--movie-base URL]
  dry-run prints the URL without launching (password never logged).
  Defaults target the ORIGINAL stack (Apache :80 + Java :8008).
  For the NEW stack: --api-base http://127.0.0.1:8080
    --movie-base http://localhost:5173/res  (Vite serves /res, Python :8008)
"""
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import http.cookiejar

WEB = "http://127.0.0.1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTOR = os.path.join(ROOT, "output", "flash-projector", "flashplayer363.exe")

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


def argval(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
    return default


def main():
    user, password = sys.argv[1], sys.argv[2]
    dry = "--dry-run" in sys.argv
    api_base = argval("--api-base")
    movie_base = argval("--movie-base")
    if api_base:
        sess = login_api(api_base, user, password)
        fv = api_flashvars(sess)
        url = (movie_base or WEB + "/res") + "/Main.swf?" + urllib.parse.urlencode(fv)
    else:
        html = login_legacy(user, password)
        fv = flashvars_of(html)
        url = WEB + "/res/Main.swf?" + urllib.parse.urlencode(fv)
    if dry:
        print("movie URL ready (not launching)")
        return
    print("launching projector...")
    subprocess.Popen([PROJECTOR, url])


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("usage: projector-client.py <username> <password> [--dry-run]")
    main()
