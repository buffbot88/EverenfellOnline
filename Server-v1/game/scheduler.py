"""Scheduler mirror: HeartBeatRateUtil, StageScheduleManager, Quartz jobs, token runnables.

Provenance (all from ``dntg_start.jar`` via ``tools/javap.py``):
- ``com.xianling.gamerule.stage.HeartBeatRateUtil.getHeartBeat``: velocity 0
  answers 400, else ``166682 / velocity`` in integer division (the bytecode
  runs ``idiv`` before ``Math.round``) -- e.g. D040011 velocity 450 -> 370ms.
- ``AiFightServiceImpl.calNextOptDelay``: XUNLUO state answers
  ``IAi.XUNLUO_PERIOD`` (10000) + ``Lottery.roll(5000)``, DEAD answers -1,
  otherwise the heartbeat of the truncated move speed (``getYiDongSuDu``).
- ``StageScheduleManager.schedule`` keeps a ``scheduleMap`` keyed by the
  task name and delegates to ``IStageScheduleExportService`` with a
  ``TimeUnit`` delay; ``cancelSchedule``/``clear`` drop entries.
- ``QuartzScheduleExportServiceImpl.schedule`` answers ``'' + nanoTime`` as
  the job id and registers either a one-shot call or a Quartz ``CronTrigger``
  (``KuangZhanQuartz.init`` uses ``'0 */1 * * * ?'`` -> checkKuangZhanStart
  every minute; ``GuaiWuGongChengQuartz`` fans out the configured time
  expressions the same way).
- ``StageTokenRunable``/``BusTokenRunable.run`` redeliver the stored
  module/command/data through the stage/bus inner-token senders; the scoped
  constructors throw on a null roleId/stageId (message included, typo kept).

Approximations: one ``Session.tick`` advances a single 1-second clock for
every fighter (Java staggers per-monster delays off the values above; the
helpers are exposed so future slices can). Cron supports exact, ``*``/``?``
and ``*/n`` fields, which covers every expression recovered so far.
``Lottery.roll(n)`` mirrors as ``randrange(n)``. Quartz jobs with no service
callback are logged and skipped (no event bus, like every other slice).
"""
import logging
import random
import time

log = logging.getLogger(__name__)

# HeartBeatRateUtil: 166682 idiv velocity; 400 when velocity is 0.
HEARTBEAT_NUMERATOR = 166682
HEARTBEAT_IDLE_MS = 400
# IAi.XUNLUO_PERIOD / roll window (AiFightServiceImpl.calNextOptDelay).
XUNLUO_PERIOD_MS = 10000
XUNLUO_ROLL_MS = 5000
# calNextOptDelay answers -1 for DEAD (no reschedule).
DEAD_NO_RESCHEDULE = -1
# KuangZhanQuartz.init registers checkKuangZhanStart on this cron.
KUANGZHAN_CRON = '0 */1 * * * ?'

# java.util.concurrent.TimeUnit subset used by the schedule calls, in ms.
TIME_UNITS = {
    'MILLISECONDS': 1,
    'SECONDS': 1000,
    'MINUTES': 60 * 1000,
    'HOURS': 60 * 60 * 1000,
}


def heart_beat(velocity):
    """HeartBeatRateUtil.getHeartBeat: 0 -> 400, else 166682 idiv velocity."""
    try:
        vel = int(float(velocity))
    except (TypeError, ValueError):
        vel = 0
    if vel == 0:
        return HEARTBEAT_IDLE_MS
    return int(HEARTBEAT_NUMERATOR / vel)  # Java idiv truncates toward zero.


def next_opt_delay(state, velocity=0, roll=None):
    """AiFightServiceImpl.calNextOptDelay in ms (XUNLUO/DEAD/heartbeat)."""
    if state == 'XUNLUO':
        dice = roll if roll is not None else random.randrange(XUNLUO_ROLL_MS)
        return XUNLUO_PERIOD_MS + int(dice)
    if state == 'DEAD':
        return DEAD_NO_RESCHEDULE
    try:
        speed = int(float(velocity))
    except (TypeError, ValueError):
        speed = 0
    return heart_beat(speed)


def _to_ms(delay, unit):
    """Convert a TimeUnit delay to ms (ValueError on unknown units)."""
    try:
        factor = TIME_UNITS[str(unit).upper()]
    except KeyError:
        raise ValueError(f'unsupported TimeUnit: {unit!r}')
    return int(delay) * factor


def _clock_ms(now_ms):
    """Monotonic ms clock, overridable per call for tests."""
    if now_ms is not None:
        return int(now_ms)
    return int(time.monotonic() * 1000)


class StageScheduleManager:
    """StageScheduleManager.scheduleMap: tasks keyed by name, due off a clock."""

    def __init__(self):
        self._tasks = {}

    def schedule(self, key, command, data, delay, unit='SECONDS', now_ms=None):
        """Register (replacing same-key) a one-shot stage task, like schedule()."""
        due = _clock_ms(now_ms) + _to_ms(delay, unit)
        self._tasks[str(key)] = {'key': str(key), 'command': command,
                                 'data': data, 'due_ms': due}
        return str(key)

    def schedule_scoped(self, scope, key, command, data, delay,
                        unit='SECONDS', now_ms=None):
        """Scoped overload: the map key is still the task name (bytecode put)."""
        entry_key = self.schedule(key, command, data, delay, unit, now_ms)
        self._tasks[entry_key]['scope'] = scope
        return entry_key

    def cancel(self, key):
        """cancelSchedule: drop one task, True when one was pending."""
        return self._tasks.pop(str(key), None) is not None

    def clear(self):
        """clear: drop every pending task."""
        self._tasks.clear()

    def pending(self):
        """Pending task keys in due order (test hook)."""
        return [e['key'] for e in
                sorted(self._tasks.values(), key=lambda e: e['due_ms'])]

    def due(self, now_ms=None):
        """Pop and return entries whose delay has elapsed, in due order."""
        now = _clock_ms(now_ms)
        ready = sorted((e for e in self._tasks.values() if e['due_ms'] <= now),
                       key=lambda e: e['due_ms'])
        for entry in ready:
            self._tasks.pop(entry['key'], None)
        return ready


def _cron_field(text):
    """Parse one cron field into ('any',)/('step', n)/('exact', v)."""
    text = str(text).strip()
    if text in ('*', '?'):
        return ('any',)
    if text.startswith('*/'):
        return ('step', int(text[2:]))
    return ('exact', int(text))


def cron_matches(expr, moment=None):
    """Match a Quartz cron (sec min hour dom month dow) against wall time."""
    fields = str(expr).split()
    if len(fields) == 7:  # Quartz year field: only exact/wildcard years match.
        fields = fields[:6] if fields[6] in ('*', '?') else None
        if fields is None:
            return False
    if len(fields) != 6:
        raise ValueError(f'unsupported cron: {expr!r}')
    sec, minute, hour, dom, month, dow = fields
    for text in (dom, month, dow):
        if _cron_field(text) != ('any',):
            raise ValueError(f'unsupported cron field: {expr!r}')
    now = time.localtime(moment) if moment is not None else time.localtime()
    for text, value in ((sec, now.tm_sec), (minute, now.tm_min),
                        (hour, now.tm_hour)):
        kind = _cron_field(text)
        if kind[0] == 'exact' and value != kind[1]:
            return False
        if kind[0] == 'step' and value % kind[1] != 0:
            return False
    return True


class QuartzScheduler:
    """QuartzScheduleExportServiceImpl: one-shot calls plus CronTriggers."""

    def __init__(self):
        self._jobs = {}

    def _new_id(self):
        """Job ids are '' + nanoTime in Java; time_ns is the same shape."""
        return str(time.time_ns())

    def schedule_call(self, target, method, args, delay, unit='SECONDS',
                      now_ms=None):
        """One-shot service call after a TimeUnit delay, answering a job id."""
        job_id = self._new_id()
        self._jobs[job_id] = {'id': job_id, 'kind': 'once', 'target': target,
                              'method': method, 'args': list(args or []),
                              'due_ms': _clock_ms(now_ms) + _to_ms(delay, unit),
                              'expr': None, 'fired': None}
        return job_id

    def schedule_cron(self, target, method, args, expr):
        """CronTrigger service call (e.g. KuangZhanQuartz.init's per-minute)."""
        cron_matches(expr)  # validate eagerly, like the Quartz trigger build.
        job_id = self._new_id()
        self._jobs[job_id] = {'id': job_id, 'kind': 'cron', 'target': target,
                              'method': method, 'args': list(args or []),
                              'due_ms': None, 'expr': str(expr), 'fired': None}
        return job_id

    def cancel(self, job_id):
        """Drop one job, True when one was pending."""
        return self._jobs.pop(str(job_id), None) is not None

    def clear(self):
        """Drop every job."""
        self._jobs.clear()

    def due(self, now_ms=None, moment=None):
        """Fire elapsed one-shots and matching cron slots; returns the jobs."""
        now = _clock_ms(now_ms)
        wall = moment if moment is not None else time.time()
        slot = time.localtime(wall)[:6]
        ready = []
        for job in list(self._jobs.values()):
            if job['kind'] == 'once':
                if job['due_ms'] <= now:
                    ready.append(job)
                    self._jobs.pop(job['id'], None)
            elif cron_matches(job['expr'], wall) and job['fired'] != slot:
                job['fired'] = slot
                ready.append(job)
        for job in ready:
            target, method, args = job['target'], job['method'], job['args']
            if target is None or not hasattr(target, str(method)):
                log.info('scheduler: job %s %s(%r) skipped (no service)',
                         job['id'], method, args)
                continue
            try:
                getattr(target, str(method))(*args)
            except Exception:
                log.warning('scheduler: job %s %s failed', job['id'], method,
                            exc_info=True)
        return ready


class BusTokenRunable:
    """BusTokenRunable: redelivers module/command/data to the bus senders."""

    def __init__(self, module, command, data, role_id=None, token=None,
                 on_role=None, on_system=None):
        self.module = module
        self.command = command
        self.data = data
        self.role_id = role_id
        self.token = token
        self.role_command = role_id is not None
        self._on_role = on_role
        self._on_system = on_system

    @classmethod
    def scoped(cls, module, role_id, command, data, **kwargs):
        """Scoped overload: null roleId throws like the Java constructor."""
        if role_id is None:
            raise ValueError('BusTokenRunable<contructor>:roleId is null')
        return cls(module, command, data, role_id=role_id, **kwargs)

    def run(self):
        """Send via the role or system bus sender (logged/skipped sans bus)."""
        if self.role_command:
            if self._on_role is None:
                log.info('scheduler: bus %s(%r) skipped (no bus)',
                         self.command, self.data)
                return False
            self._on_role(self.role_id, self.command, self.data, self.token)
            return True
        if self._on_system is None:
            log.info('scheduler: bus %s(%r) skipped (no bus)',
                     self.command, self.data)
            return False
        self._on_system(self.module, self.command, self.data, self.token)
        return True


class StageTokenRunable:
    """StageTokenRunable: redelivers role/stage/command/data to stage senders."""

    def __init__(self, module, command, data, role_id=None, stage_id=None,
                 token=None, on_stage=None, on_system=None):
        self.module = module
        self.command = command
        self.data = data
        self.role_id = role_id
        self.stage_id = stage_id
        self.token = token
        self.stage_command = role_id is not None
        self._on_stage = on_stage
        self._on_system = on_system

    @classmethod
    def scoped(cls, module, role_id, stage_id, command, data, **kwargs):
        """Scoped overload: null roleId/stageId throws (typo kept from Java)."""
        if role_id is None:
            raise ValueError(
                'StageTokenRunable<contructor>:roleId is null')
        if stage_id is None:
            raise ValueError(
                'StageTokenRunable<contructor>:stageId is null')
        return cls(module, command, data, role_id=role_id,
                   stage_id=stage_id, **kwargs)

    def run(self):
        """Send via the stage-inner or stage-system sender (else skip)."""
        if self.stage_command:
            if self._on_stage is None:
                log.info('scheduler: stage %s(%r) skipped (no bus)',
                         self.command, self.data)
                return False
            self._on_stage(self.role_id, self.stage_id, self.command,
                           self.data, self.token)
            return True
        if self._on_system is None:
            log.info('scheduler: stage %s(%r) skipped (no bus)',
                     self.command, self.data)
            return False
        self._on_system(self.module, self.command, self.data, self.token)
        return True


def register_stage_quartz(sched, kuangzhan=None, guaiwu_time_exprs=()):
    """Register the stage cron jobs (KuangZhan + GuaiWuGongCheng fan-out)."""
    ids = [sched.schedule_cron(kuangzhan, 'checkKuangZhanStart', [],
                               KUANGZHAN_CRON)]
    for expr in guaiwu_time_exprs or ():
        ids.append(sched.schedule_cron(None, 'guaiWuGongChengSchedule',
                                       [], str(expr)))
    return ids


def tick_sessions(pairs):
    """Run one server tick over (session, send) pairs; returns (ticked, sent)."""
    ticked = sent = 0
    pairs = list(pairs)
    # One round for the shared monster world: the first session to tick runs it.
    for world in {id(getattr(s, '_world', None)): getattr(s, '_world', None)
                  for s, _ in pairs}.values():
        if world is not None:
            world.begin_round()
    for sess, send in pairs:
        lock = getattr(sess, 'send_lock', None)
        try:
            out = sess.tick()  # takes the session state lock itself
        except Exception:
            log.warning('scheduler: tick failed', exc_info=True)
            continue
        ticked += 1
        if not out:
            continue
        frames = list(out) if isinstance(out, tuple) else [out]
        try:
            if lock is not None:
                with lock:
                    send(frames)
            else:
                send(frames)
        except Exception:
            log.warning('scheduler: tick send failed', exc_info=True)
            continue
        sent += len(frames)
    return ticked, sent
