import logging
from time import monotonic

log = logging.getLogger(__name__)

class ValveLimiter:
    def __init__(self, name, min_on, min_off, clock=monotonic):
        self.name = name
        self.min_on = min_on
        self.min_off = min_off
        self.clock = clock
        self.open = False
        self.age = min_off
        self.stamp = None
        self.balance = 0.0
        self.noted = False

    def elapse(self, dt):
        now = self.clock()
        elapsed = 0.0 if self.stamp is None else now - self.stamp
        self.stamp = now
        self.age += max(dt, elapsed)

    def step(self, demand, calling, dt, pending=0.0, boost=False, cut=False):
        if boost:
            self.bypass()
            return True
        if cut:
            self.cut(dt)
            return False

        self.elapse(dt)
        if not calling:
            self.balance = 0.0

        if self.open:
            self.step_open(demand, dt)
        else:
            self.step_closed(demand, dt, pending)
        return self.open

    def cut(self, dt=0.0):
        self.elapse(dt)
        self.balance = 0.0
        self.noted = False
        if self.open:
            if self.age < self.min_on:
                log.info("zone %s closes the valve before its minimum on time, the call was cut", self.name)
            self.open = False
            self.age = 0.0

    def bypass(self):
        self.stamp = self.clock()
        if not self.open:
            self.open = True
            self.age = 0.0
        self.age = max(self.age, self.min_on)
        self.balance = 0.0
        self.noted = False

    def step_open(self, demand, dt):
        if not demand:
            self.balance = max(0.0, self.balance - dt)
        if demand or self.balance > 0:
            return
        if self.age < self.min_on:
            self.note("holds the valve open for %d more seconds", self.min_on - self.age)
            return
        self.open = False
        self.age = 0.0
        self.noted = False

    def step_closed(self, demand, dt, pending):
        if demand:
            self.balance += dt
        if self.balance + pending < self.min_on:
            if self.balance > 0:
                self.note("accumulates %d of %d seconds of demand", self.balance, self.min_on)
            return
        if self.age < self.min_off:
            self.note("holds a call back for %d more seconds, the valve closed %d seconds ago",
                      self.min_off - self.age, self.age)
            return
        if self.balance > dt:
            log.info("zone %s releases %d seconds of accumulated demand", self.name, self.balance)
        self.open = True
        self.age = 0.0
        self.noted = False

    def note(self, message, *args):
        if self.noted:
            return
        self.noted = True
        log.info("zone %s " + message, self.name, *args)
