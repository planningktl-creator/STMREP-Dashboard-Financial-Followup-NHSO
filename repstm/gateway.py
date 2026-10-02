"""One gateway schedule per endpoint, with foreground/lease priority.

Connections stay owned by their caller. Up to three calls may await gateway
responses, with only one background batch. Starts share the same rate limit;
an already submitted atomic batch is never interrupted by a later reader.
"""
from contextlib import contextmanager
from threading import Condition, Lock
import time


class Gate:
    def __init__(self, max_concurrent=3):
        self.condition = Condition()
        self.waiters = []
        self.active = 0
        self.background_active = False
        self.max_concurrent = max_concurrent
        self.next_start = 0.0
        self.foreground_streak = 0

    @contextmanager
    def slot(self, priority, interval, deadline=None):
        waiter = (priority, object())
        start = time.monotonic()
        with self.condition:
            self.waiters.append(waiter)
            try:
                while True:
                    now = time.monotonic()
                    if deadline is not None and now >= deadline:
                        raise RuntimeError('REPORT_TIMEOUT')
                    # Readers and leases precede background work. After eight
                    # foreground calls give one waiting batch a turn.
                    eligible=[x for x in self.waiters if x[0]!=2 or not self.background_active]
                    wanted = min((x[0] for x in eligible),default=None)
                    if self.foreground_streak >= 8 and not self.background_active and any(x[0] == 2 for x in self.waiters):
                        wanted = 2
                    chosen = next((x for x in eligible if x[0] == wanted),None)
                    if self.active<self.max_concurrent and chosen == waiter and now >= self.next_start:
                        self.waiters.remove(waiter)
                        self.active += 1
                        if priority==2:self.background_active=True
                        self.next_start = now + max(0, interval)
                        self.foreground_streak = self.foreground_streak + 1 if priority < 2 else 0
                        break
                    delay = max(.001, self.next_start - now) if self.active<self.max_concurrent and eligible else .1
                    self.condition.wait(min(delay, max(.001, deadline-now)) if deadline else delay)
            except BaseException:
                self.waiters.remove(waiter)
                self.condition.notify_all()
                raise
        try:
            yield time.monotonic() - start
        finally:
            with self.condition:
                self.active -= 1
                if priority==2:self.background_active=False
                self.condition.notify_all()


_gates = {}
_lock = Lock()


def gateway_gate(url):
    with _lock:
        return _gates.setdefault(url, Gate())
