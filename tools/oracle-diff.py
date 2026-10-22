#!/usr/bin/env python3
"""Send the same command list to the Java and Python servers and diff the replies.

Each side gets the captured world entry (login, 10003, 20000, 21000), then every
`--cmd`. Java authenticates with the legacy forged socket sign; Python logs in
through its own web API (`gamesession.php`) so no server secret is needed. A
command with no reply within the timeout is reported as a mismatch too.

After world entry it also compares the server-initiated push stream collected in
`--push-window` seconds: command ids present on one side only, and the first
payload of ids that arrive once on each side. Repeated ids are compared by
presence only, because their order and count are timing-dependent. Each command
is compared the same way against the notifications it caused (frames seen
before its reply plus `--notify-window` seconds after it). Known noise is listed
in tools/oracle-baseline.json, with `push` and `reply` sections: ignored ids are
skipped, recorded diffs are reported as baselined, and any new or changed diff
still fails. Triggered-push baseline keys are `<trigger>:<pushed>`; ignore
entries may be a bare pushed id or that composite.

Usage: oracle-diff.py --cmd 58011 [--cmd '41023:["sj0101"]'] [options]

Exit status: 0 all commands and pushes matched, 1 any mismatch, 2 setup failed.
"""
import argparse
import hashlib
import hmac
import http.cookiejar
import json
import os
import socket
import struct
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'Server-v1'))

from game import amf3                      # noqa: E402
from game.cipher import SimpleEncrypt      # noqa: E402
from game.protocol import frame            # noqa: E402

SIGN_SALT = 'xianlingkey'
MAX_FRAME = 48 * 1024 * 1024
DEFAULT_BASELINE = os.path.join(ROOT, 'tools', 'oracle-baseline.json')


class SetupError(Exception):
    """Login or world entry failed for one side."""


def legacy_sign(uid, t):
    """The Java server's socket sign: md5(uid + 'xianlingkey' + t)."""
    return hashlib.md5(f'{uid}{SIGN_SALT}{t}'.encode()).hexdigest()


def hmac_sign(secret, uid, t):
    """The Python server's socket sign when no web API is used."""
    return hmac.new(secret.encode(), f'{uid}|{t}'.encode(),
                    hashlib.sha256).hexdigest()


def web_session(web, user, password):
    """Log in over the Python web API and return its gamesession fields."""
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    body = urllib.parse.urlencode(
        {'Action': 'Login', 'uName': user, 'uPas': password}).encode()
    try:
        reply = opener.open(web.rstrip('/') + '/AjaxRequest/AccountHandler.php',
                            data=body, timeout=15).read().decode('utf-8', 'replace')
    except OSError as exc:
        raise SetupError(f'web login failed: {exc}')
    if '登录成功' not in reply and 'Login successful' not in reply:
        raise SetupError(f'web login rejected: {reply[:80]}')
    try:
        data = json.loads(opener.open(
            web.rstrip('/') + '/gamesession.php', timeout=15).read())
    except (OSError, ValueError) as exc:
        raise SetupError(f'gamesession failed: {exc}')
    if not data.get('ok'):
        raise SetupError(f'gamesession refused: {data}')
    return data


def parse_cmd(text):
    """`58011` or `41023:["sj0101"]` -> (int id, argument list)."""
    cmd, _, payload = text.partition(':')
    try:
        cmd_id = int(cmd)
    except ValueError:
        raise SetupError(f'bad command id: {text!r}')
    if not payload:
        return cmd_id, []
    try:
        args = json.loads(payload)
    except ValueError as exc:
        raise SetupError(f'bad command arguments in {text!r}: {exc}')
    if not isinstance(args, list):
        raise SetupError(f'command arguments must be a JSON list: {text!r}')
    return cmd_id, args


def normalize(value):
    """Comparison form: numbers unified, containers walked, bytes kept raw."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    return value


def first_diff(left, right, path='$'):
    """Describe the first differing field, or None when the values match."""
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left:
                return f'{path}.{key}: java missing, python={right[key]!r}'
            if key not in right:
                return f'{path}.{key}: python missing, java={left[key]!r}'
            found = first_diff(left[key], right[key], f'{path}.{key}')
            if found:
                return found
        return None
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return f'{path}: length java={len(left)} python={len(right)}'
        for index, (litem, ritem) in enumerate(zip(left, right)):
            found = first_diff(litem, ritem, f'{path}[{index}]')
            if found:
                return found
        return None
    if left != right:
        return f'{path}: java={left!r} python={right!r}'
    return None


def compare(left, right):
    """Mismatch description for two replies, or None when they agree."""
    return first_diff(normalize(left), normalize(right))


def truncate(value, width):
    """repr() capped at `width` characters so large replies stay readable."""
    text = repr(value)
    return text if len(text) <= width else text[:width - 3] + '...'


def push_key(cmd_id):
    """Sort numeric command ids before anything non-numeric."""
    try:
        return (0, int(cmd_id), '')
    except (TypeError, ValueError):
        return (1, 0, str(cmd_id))


def summarize_pushes(pushes):
    """Group push payloads by command id, keeping every occurrence."""
    grouped = {}
    for msg in pushes:
        if isinstance(msg, list) and msg:
            grouped.setdefault(str(msg[0]), []).append(msg)
    return grouped


def clip(text, width):
    """Cap a plain string (a diff description) at `width` characters."""
    return text if len(text) <= width else text[:width - 3] + '...'


def compare_pushes(java_pushes, python_pushes, width=300, ignore=None,
                   baseline=None, prefix='', scope=None, tag='PUSH'):
    """(lines, issue count, observed diffs) for two server push streams.

    Ids in `ignore` are skipped entirely; an entry may be a bare pushed id or a
    `<trigger>:<pushed>` key. A diff equal to the one recorded in `baseline` is
    reported as baselined and does not count; a changed diff is still an issue.
    `prefix` scopes the baseline keys (command-triggered pushes use
    `<trigger>:<pushed>`), and `scope` limits the stale-entry check.
    """
    ignore = {str(item) for item in (ignore or ())}
    baseline = baseline or {}

    def is_ignored(key):
        """An entry ignores a pushed id everywhere, or one trigger's frame."""
        if key in ignore:
            return True
        return bool(prefix) and key.startswith(prefix) and \
            key[len(prefix):] in ignore

    java_map = summarize_pushes(java_pushes)
    python_map = summarize_pushes(python_pushes)
    lines = []
    issues = 0
    observed = {}
    for cmd_id in sorted(set(java_map) | set(python_map), key=push_key):
        key = f'{prefix}{cmd_id}'
        if is_ignored(key):
            continue
        left, right = java_map.get(cmd_id), python_map.get(cmd_id)
        if left and not right:
            issues += 1
            lines.append(f'   {tag}-ONLY java {cmd_id} (x{len(left)})')
        elif right and not left:
            issues += 1
            lines.append(f'   {tag}-ONLY python {cmd_id} (x{len(right)})')
        elif len(left) == 1 and len(right) == 1:
            diff = compare(left[0], right[0])
            if diff:
                observed[key] = diff
                if baseline.get(key) == diff:
                    lines.append(f'   {tag}-BASELINED {cmd_id}: '
                                 f'{clip(diff, width)}')
                else:
                    issues += 1
                    lines.append(f'   {tag}-DIFF {cmd_id}: '
                                 f'{clip(diff, width)}')
            else:
                lines.append(f'   {tag}-MATCH {cmd_id}')
        else:
            # Repeated frames are timed pushes: only their presence is stable.
            lines.append(f'   {tag}-BOTH {cmd_id} '
                         f'(x{len(left)}/x{len(right)}, values not compared)')
    known_scope = set(baseline) if scope is None else scope
    stale = [key for key in known_scope - set(observed)
             if not is_ignored(key)]
    for key in sorted(stale, key=push_key):
        lines.append(f'   {tag}-BASELINE-STALE {key} '
                     '(now matches or not pushed)')
    return lines, issues, observed


def diff_reply(java_reply, python_reply):
    """Canonical mismatch text for one command reply, or None when equal."""
    if java_reply is None and python_reply is None:
        return 'no reply from both'
    if java_reply is None:
        return 'no reply from java'
    if python_reply is None:
        return 'no reply from python'
    return compare(java_reply, python_reply)


def _read_baseline_file(path):
    """Load the baseline JSON, or {} when the file does not exist yet."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise SetupError(f'cannot read baseline {path}: {exc}')


def _sections(path):
    """{'push': section, 'reply': section}; a flat file is the push section."""
    data = _read_baseline_file(path)
    if not data:
        return {'push': {}, 'reply': {}}
    if not isinstance(data, dict):
        raise SetupError(f'baseline {path} is not a JSON object')
    if 'push' in data or 'reply' in data:
        sections = {'push': data.get('push', {}),
                    'reply': data.get('reply', {})}
    else:
        sections = {'push': data, 'reply': {}}
    for channel, section in sections.items():
        if not isinstance(section, dict):
            raise SetupError(f'baseline {path}: {channel} must be an object')
    return sections


def _read_section(section, path, channel):
    """(ignored ids, known diffs) from one channel section."""
    ignore = section.get('ignore', [])
    known = section.get('baseline', {})
    if not isinstance(ignore, list) or not all(
            isinstance(item, (str, int)) for item in ignore):
        raise SetupError(f'baseline {path}: {channel}.ignore must be a list '
                         'of ids')
    if not isinstance(known, dict) or not all(
            isinstance(key, str) and isinstance(val, str)
            for key, val in known.items()):
        raise SetupError(f'baseline {path}: {channel}.baseline must map each '
                         'id to a diff string')
    return {str(item) for item in ignore}, dict(known)


def load_baseline(path):
    """{'push': (ignore, diffs), 'reply': (ignore, diffs)} from a JSON file.

    A flat file with top-level `ignore`/`baseline` is read as the push section.
    """
    sections = _sections(path)
    return {channel: _read_section(sections[channel], path, channel)
            for channel in ('push', 'reply')}


def load_push_baseline(path):
    """The push section of a baseline file, for callers that only need it."""
    return load_baseline(path)['push']


def write_baseline(path, updates):
    """Update baseline channels in place.

    `updates` maps a channel to (ignore ids, observed diffs, ids considered).
    Entries for considered ids are replaced or dropped; entries for ids not
    considered this run are kept, and hand-written ignore entries survive.
    """
    sections = _sections(path)
    for channel, (ignore, observed, considered) in updates.items():
        old_ignore, old_known = _read_section(sections[channel], path, channel)
        merged_ignore = old_ignore | {str(item) for item in ignore}
        known = {key: val for key, val in old_known.items()
                 if key not in considered}
        known.update(observed)
        known = {key: val for key, val in known.items()
                 if key not in merged_ignore}
        sections[channel] = {
            'ignore': sorted(merged_ignore, key=push_key),
            'baseline': {key: known[key] for key in sorted(known, key=push_key)},
        }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump({'push': sections['push'], 'reply': sections['reply']},
                  handle, indent=2, ensure_ascii=False)
        handle.write('\n')


def resolve_baseline(args):
    """(push (ignore, known), reply (ignore, known)) for this run."""
    path = getattr(args, 'baseline', '')
    if path:
        base = load_baseline(path)
    else:
        base = {'push': (set(), {}), 'reply': (set(), {})}
    push_ignore = base['push'][0] | {
        str(item) for item in (getattr(args, 'push_ignore', []) or [])}
    reply_ignore = base['reply'][0] | {
        str(item) for item in (getattr(args, 'reply_ignore', []) or [])}
    return (push_ignore, base['push'][1]), (reply_ignore, base['reply'][1])


class Client:
    """One game socket: INITKEY, encrypted login, world entry, commands."""

    def __init__(self, label, host, port, uid, seid, sign, stamp,
                 timeout=4.0, settle=1.5):
        self.label = label
        self.host, self.port = host, port
        self.uid, self.seid, self.sign, self.stamp = uid, seid, sign, stamp
        self.timeout, self.settle = timeout, settle
        self.sock = None
        self.cipher = None
        self.pushes = []


    def _recv_exact(self, size):
        buf = b''
        while len(buf) < size:
            chunk = self.sock.recv(size - len(buf))
            if not chunk:
                raise ConnectionError('server closed the connection')
            buf += chunk
        return buf

    def _recv_raw(self):
        head = self._recv_exact(4)
        length = struct.unpack('>I', head)[0]
        if length == 0 or length > MAX_FRAME:
            return None
        return head + self._recv_exact(length)

    def open(self):
        """TCP connect plus the INITKEY key exchange."""
        self.sock = socket.create_connection((self.host, self.port),
                                             timeout=10)
        self.sock.settimeout(self.timeout)
        self.sock.sendall(frame(amf3.encode('INITKEY')))
        raw = self._recv_raw()
        if raw is None:
            raise SetupError(f'{self.label}: no INITKEY key reply')
        self.cipher = SimpleEncrypt(raw[4:].decode('utf-8', 'replace'))

    def send(self, cmd_id, args):
        """Write one encrypted client command."""
        payload = frame(self.cipher.encode(amf3.encode([cmd_id, *args])))
        self.sock.sendall(payload)

    def read_until(self, cmd_id, timeout=None):
        """Read frames until `cmd_id` answers; returns (reply, other frames)."""
        deadline = time.monotonic() + (self.timeout if timeout is None
                                       else timeout)
        others = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, others
            self.sock.settimeout(remaining)
            try:
                raw = self._recv_raw()
            except socket.timeout:
                return None, others
            except ConnectionError:
                return None, others
            if raw is None:
                return None, others
            try:
                msg = amf3.decode(raw[4:])
            except Exception:
                continue
            if isinstance(msg, list) and msg and str(msg[0]) == str(cmd_id):
                return msg, others
            others.append(msg)
            self.pushes.append(msg)

    def collect(self, seconds):
        """Read frames for `seconds` and return the decoded messages."""
        deadline = time.monotonic() + seconds
        messages = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return messages
            self.sock.settimeout(remaining)
            try:
                raw = self._recv_raw()
            except (socket.timeout, ConnectionError):
                return messages
            if raw is None:
                return messages
            try:
                messages.append(amf3.decode(raw[4:]))
            except Exception:
                continue

    def drain(self, seconds):
        """Collect server pushes for `seconds` into the push buffer."""
        self.pushes.extend(self.collect(seconds))

    def take_pushes(self):
        """Return the collected pushes and clear the buffer."""
        collected, self.pushes = self.pushes, []
        return collected

    def login(self):
        """INITKEY + 10001; raises SetupError with the server's own reply."""
        self.open()
        # The login payload is one nested array (captured client frame shape).
        self.send(10001, [[self.uid, float(self.stamp), self.seid, False,
                           self.sign, False, 0, 0, 0]])
        reply, _ = self.read_until('10001', timeout=10)
        if reply is None:
            raise SetupError(f'{self.label}: no 10001 reply')
        result = reply[1] if len(reply) > 1 else None
        ok = isinstance(result, list) and result and result[0] == 1
        if not ok:
            raise SetupError(
                f'{self.label}: login rejected: {truncate(reply, 200)}')

    def world_entry(self, role):
        """10003 + 20000 + 21000, waiting briefly after each."""
        self.send(10003, [role])
        reply, _ = self.read_until('10003', timeout=10)
        if reply is None:
            raise SetupError(f'{self.label}: role {role!r} not accepted')
        self.send(20000, [[role, '5']])
        self.read_until('20000', timeout=self.settle)
        self.send(21000, [[role, '5']])
        # The push stream comparison starts here: everything after world entry.
        self.pushes = []
        self.read_until('21000', timeout=self.settle)

    def request(self, cmd_id, args, notify_window=0.0):
        """Send one command; return (reply, notifications it caused).

        Notifications are the frames seen before the reply plus, when
        `notify_window` is positive, any that arrive just after it.
        """
        # The client always sends one argument slot; a bare command sends null.
        self.send(cmd_id, args or [None])
        reply, others = self.read_until(cmd_id)
        if notify_window > 0:
            others.extend(self.collect(notify_window))
        return reply, others

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


def split_hostport(text):
    """'127.0.0.1:8008' -> ('127.0.0.1', 8008)."""
    host, _, port = text.rpartition(':')
    if not host or not port.isdigit():
        raise SetupError(f'expected HOST:PORT, got {text!r}')
    return host, int(port)


def build_java(args):
    """Java side: forged legacy sign at the current second."""
    stamp = int(time.time())
    host, port = split_hostport(args.java)
    return Client('java', host, port, args.uid, args.server,
                  legacy_sign(args.uid, stamp), stamp,
                  timeout=args.timeout, settle=args.settle)


def build_python(args):
    """Python side: web session when given, else the shared-sign secret."""
    host, port = split_hostport(args.python)
    if args.python_web:
        session = web_session(args.python_web, args.user, args.password)
        return Client('python', host, port, session['uid'],
                      session.get('seid') or args.server,
                      session['sign'], int(session['t']),
                      timeout=args.timeout, settle=args.settle)
    secret = args.python_secret
    if not secret:
        raise SetupError('no --python-web and no --python-secret/'
                         'MKO_SIGN_SECRET to sign the Python login')
    stamp = int(time.time())
    return Client('python', host, port, args.uid, args.server,
                  hmac_sign(secret, args.uid, stamp), stamp,
                  timeout=args.timeout, settle=args.settle)


def run(args):
    """Play the plan on both sides and return (report lines, mismatch count)."""
    if not args.cmd:
        raise SetupError('no --cmd given')
    (push_ignore, push_known), (reply_ignore, reply_known) = \
        resolve_baseline(args)
    plan = [parse_cmd(text) for text in args.cmd]
    java_role = args.java_role or args.role
    python_role = args.python_role or args.role
    java = build_java(args)
    python = build_python(args)
    lines = [
        f'== java   {args.java}  uid={java.uid} role={java_role}',
        f'== python {args.python}  uid={python.uid} role={python_role}',
    ]
    try:
        for client, role in ((java, java_role), (python, python_role)):
            client.login()
            lines.append(f'   {client.label}: login ok')
            client.world_entry(role)
            lines.append(f'   {client.label}: world entry ok')
        push_issues = 0
        push_seen = set()
        observed_push = {}
        if args.push_window > 0:
            java.drain(args.push_window)
            python.drain(args.push_window)
            java_pushes = java.take_pushes()
            python_pushes = python.take_pushes()
            lines.append(f'-- push stream ({args.push_window:g}s '
                         'after world entry)')
            lines.append(
                f'   java: {len(java_pushes)} frames / '
                f'{len(summarize_pushes(java_pushes))} ids, python: '
                f'{len(python_pushes)} frames / '
                f'{len(summarize_pushes(python_pushes))} ids')
            push_seen = (set(summarize_pushes(java_pushes)) |
                         set(summarize_pushes(python_pushes)))
            if push_ignore:
                lines.append('   ignored ids: ' +
                             ', '.join(sorted(push_ignore, key=push_key)))
            push_lines, push_issues, observed_push = compare_pushes(
                java_pushes, python_pushes, args.width, push_ignore,
                push_known)
            lines.extend(push_lines)
        mismatches = 0
        matched = 0
        baselined = 0
        notify_issues = 0
        observed_reply = {}
        observed_notify = {}
        notify_considered = set()
        ran = set()
        for cmd_id, cmd_args in plan:
            key = str(cmd_id)
            ran.add(key)
            java_reply, java_notify = java.request(
                cmd_id, cmd_args, args.notify_window)
            python_reply, python_notify = python.request(
                cmd_id, cmd_args, args.notify_window)
            lines.append(f'-- {cmd_id} {cmd_args!r}')
            lines.append('   java  : ' + ('(no reply)'
                                          if java_reply is None
                                          else truncate(java_reply,
                                                        args.width)))
            lines.append('   python: ' + ('(no reply)'
                                          if python_reply is None
                                          else truncate(python_reply,
                                                        args.width)))
            prefix = f'{key}:'
            scope = {item for item in push_known if item.startswith(prefix)}
            notify_lines, issues, seen = compare_pushes(
                java_notify, python_notify, args.width, push_ignore,
                push_known, prefix=prefix, scope=scope, tag='NOTIFY')
            notify_issues += issues
            observed_notify.update(seen)
            notify_considered |= {
                prefix + str(item) for item in
                set(summarize_pushes(java_notify)) |
                set(summarize_pushes(python_notify))}
            notify_considered |= scope
            if notify_lines:
                lines.extend(notify_lines)
            else:
                lines.append('   pushes: none')
            if key in reply_ignore:
                lines.append('   IGNORED')
                continue
            diff = diff_reply(java_reply, python_reply)
            if diff is None:
                matched += 1
                lines.append('   MATCH')
                continue
            observed_reply[key] = diff
            waited = '' if not diff.startswith('no reply') \
                else f' (waited {args.timeout:g}s)'
            if reply_known.get(key) == diff:
                baselined += 1
                lines.append(f'   BASELINED: {clip(diff, args.width)}{waited}')
            else:
                mismatches += 1
                lines.append(f'   MISMATCH: {clip(diff, args.width)}{waited}')
        for key in sorted((set(reply_known) & ran) - set(observed_reply)
                          - reply_ignore, key=push_key):
            lines.append(f'   REPLY-BASELINE-STALE {key} (now matches)')
        if args.write_baseline:
            updates = {'reply': (reply_ignore, observed_reply, ran)}
            parts = [f'reply {len(observed_reply)} diffs']
            if args.push_window > 0 or notify_considered:
                merged = dict(observed_push)
                merged.update(observed_notify)
                updates['push'] = (push_ignore, merged,
                                   set(push_seen) | notify_considered)
                parts.insert(0, f'push {len(merged)} diffs')
            write_baseline(args.write_baseline, updates)
            lines.append(f'   baseline written: {args.write_baseline} '
                         f'({", ".join(parts)})')
        lines.append(f'summary: {len(plan)} commands, {matched} matched, '
                     f'{baselined} baselined, {mismatches} mismatched, '
                     f'{push_issues} push issues, '
                     f'{notify_issues} notify issues')
        return lines, mismatches, push_issues, notify_issues
    finally:
        java.close()
        python.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--java', default='127.0.0.1:8008')
    parser.add_argument('--python', default='127.0.0.1:8018')
    parser.add_argument('--python-web', default='http://127.0.0.1:8180',
                        help='Python web API base; "none" forces the secret path')
    parser.add_argument('--python-secret', default=os.environ.get(
        'MKO_SIGN_SECRET', ''),
        help='HMAC sign secret when no web API is used')
    parser.add_argument('--user', default='stress',
                        help='web login name for the Python side')
    parser.add_argument('--password', default=os.environ.get(
        'MKO_DIFF_PASSWORD', ''),
        help='web login password; prefer MKO_DIFF_PASSWORD over argv')
    parser.add_argument('--uid', default='stress',
                        help='Java socket login id')
    parser.add_argument('--server', default='fu1304')
    parser.add_argument('--role', default='fu0UR1-10-0-1',
                        help='role id used by both sides')
    parser.add_argument('--java-role', default='')
    parser.add_argument('--python-role', default='')
    parser.add_argument('--cmd', action='append', default=[],
                        help='ID or ID:JSON-ARGS, repeatable')
    parser.add_argument('--timeout', type=float, default=4.0,
                        help='seconds to wait for each command reply')
    parser.add_argument('--settle', type=float, default=1.5,
                        help='seconds to wait after each world-entry frame')
    parser.add_argument('--push-window', type=float, default=3.0,
                        help='seconds to collect server pushes after world '
                             'entry; 0 disables the push comparison')
    parser.add_argument('--notify-window', type=float, default=1.0,
                        help='seconds after each reply to keep collecting '
                             'the notifications that command caused; 0 '
                             'compares only frames seen before the reply')
    parser.add_argument('--baseline', '--push-baseline',
                        dest='baseline', default=DEFAULT_BASELINE,
                        help='JSON file of ignored ids and known diffs for '
                             'push and reply; pass an empty string to disable')
    parser.add_argument('--push-ignore', action='append', default=[],
                        metavar='ID', help='extra push id to skip, repeatable')
    parser.add_argument('--reply-ignore', action='append', default=[],
                        metavar='ID', help='extra command id to skip, '
                                           'repeatable')
    parser.add_argument('--write-baseline', '--write-push-baseline',
                        dest='write_baseline', default='',
                        help='write observed push and reply diffs as a '
                             'baseline file')
    parser.add_argument('--width', type=int, default=300,
                        help='max characters of a reply printed per side')
    parser.add_argument('--report', default='',
                        help='also write the report to this path')
    args = parser.parse_args()
    if args.python_web.lower() in ('none', '-', ''):
        args.python_web = ''
    if not args.password and args.python_web:
        parser.error('web login needs --password or MKO_DIFF_PASSWORD')
    if not args.user:
        args.user = args.uid
    try:
        lines, mismatches, push_issues, notify_issues = run(args)
    except SetupError as exc:
        print(f'oracle-diff: {exc}', file=sys.stderr)
        return 2
    text = '\n'.join(lines)
    print(text)
    if args.report:
        with open(args.report, 'w', encoding='utf-8') as handle:
            handle.write(text + '\n')
    return 1 if (mismatches or push_issues or notify_issues) else 0


if __name__ == '__main__':
    sys.exit(main())
