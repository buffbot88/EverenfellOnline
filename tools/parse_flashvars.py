"""Extract the flashvars object from a saved Gamelogin.php page.

Usage: parse-flashvars.py <gamelogin.html> <out.args>
Writes one `-Pkey=value` line per flashvar (for `ruffle -P`), plus a
fresh client-side `lcid` replicating the original page's JavaScript.
"""
import random
import re
import sys
import time

SRC_PAT = re.compile(r"var flashvars\s*=\s*\{(.*?)\};", re.S)
PAIR_PAT = re.compile(r"(\w+)\s*:\s*(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\")")


def main(html_path, out_path):
    html = open(html_path, encoding="utf-8", errors="replace").read()
    m = SRC_PAT.search(html)
    if not m:
        raise SystemExit("flashvars block not found")
    # newline="\n": the args file is consumed line-wise (mapfile); a Windows
    # CRLF would append \r to the last value (e.g. ip=127.0.0.1\r breaks DNS).
    with open(out_path, "w", encoding="utf-8", newline="\n") as out:
        for key, squote, dquote in PAIR_PAT.findall(m.group(1)):
            out.write("-P%s=%s\n" % (key, (squote or dquote).replace("\\'", "'")))
        lcid = format(int(time.time() * 1000), "x") + format(random.randint(0, 999), "x")
        out.write("-Plcid=%s\n" % lcid)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
