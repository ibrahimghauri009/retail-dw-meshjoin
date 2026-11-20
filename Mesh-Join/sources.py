# OnlineThread reads the online csv as a stream,
# PeriodicThread releases one periodic group every simulated hour

import csv
import threading
import time
import traceback

import config
import db
from control import log
from meshjoin import LIVE, Transaction

GROUP_SQL = (
    "SELECT transaction_id, customer_id, product_id, quantity, unit_price, "
    "event_time, sales_mode FROM periodic_sales_data "
    "WHERE release_hour = %s AND released = 0 ORDER BY staging_id")


class OnlineThread(threading.Thread):
    TICK = 0.05   # seconds between two small bursts of the stream

    def __init__(self, online_path, control, stream_buffer):
        super().__init__(name="OnlineThread", daemon=True)
        self.online_path = online_path
        self.control = control
        self.stream_buffer = stream_buffer

    def run(self):
        try:
            self._run()
        except Exception as error:
            self.control.failed = f"OnlineThread: {error}"
            traceback.print_exc()

    def _run(self):
        control = self.control
        with open(self.online_path, newline="", encoding="utf-8") as handle:
            control.online_total = sum(1 for _ in handle) - 1
        log(f"[ONLINE] Stream file holds {control.online_total:,} transactions")

        with open(self.online_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            allowance = 0.0               # transactions we are allowed to send
            last = time.monotonic()
            while not control.stop.is_set():
                now = time.monotonic()
                if control.form_mode == "periodic":      # stream reader paused
                    last = now
                    control.stop.wait(self.TICK)
                    continue
                rate = control.rate()                    # transactions per second
                allowance = min(allowance + rate * (now - last), rate)
                last = now
                to_send = int(allowance)
                allowance -= to_send
                for _ in range(to_send):
                    row = next(reader, None)
                    if row is None:
                        control.online_finished = True
                        log("[ONLINE] End of the stream file reached")
                        return
                    transaction = Transaction(
                        row["transaction_id"], row["customer_id"], row["product_id"],
                        int(row["quantity"]), row["unit_price"], row["event_time"],
                        row["sales_mode"], LIVE)
                    if not self.stream_buffer.put_live(transaction, control.stop):
                        return
                    control.online_sent += 1
                control.stop.wait(self.TICK)


class PeriodicThread(threading.Thread):
    def __init__(self, settings, control, stream_buffer):
        super().__init__(name="PeriodicThread", daemon=True)
        self.settings = settings
        self.control = control
        self.stream_buffer = stream_buffer

    def run(self):
        try:
            self._run()
        except Exception as error:
            self.control.failed = f"PeriodicThread: {error}"
            traceback.print_exc()

    def _run(self):
        control = self.control
        conn = db.connect(self.settings)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT COUNT(DISTINCT release_hour) FROM periodic_sales_data")
        control.groups_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT release_hour) FROM periodic_sales_data "
                    "WHERE released = 1")
        control.groups_released = cur.fetchone()[0]

        next_tick = time.monotonic()      # the first group may go at once
        while not control.stop.is_set():
            if time.monotonic() >= next_tick:
                next_tick += control.hour_seconds
                control.hour += 1
                # results joined during the last hour are loaded now
                control.flush_periodic.set()
                if control.form_mode != "online":
                    self._extract_next_group(cur)
            control.stop.wait(0.1)
        cur.close()
        conn.close()

    def _extract_next_group(self, cur):
        control = self.control
        cur.execute("SELECT MIN(release_hour) FROM periodic_sales_data WHERE released = 0")
        group = cur.fetchone()[0]
        if group is None:
            return                         # all 48 groups are out already
        cur.execute(GROUP_SQL, (group,))
        waiting = [Transaction(r[0], r[1], r[2], r[3], r[4], r[5], r[6], config.PERIODIC)
                   for r in cur.fetchall()]
        cur.execute("UPDATE periodic_sales_data SET released = 1 WHERE release_hour = %s",
                    (group,))
        control.groups_released += 1
        total = len(waiting)
        to_buffer = 0
        to_shed = 0

        # Put the group into the stream buffer. Whatever does not fit is
        # shed in peak time, or waits for room in non-peak time.
        while waiting and not control.stop.is_set():
            accepted = self.stream_buffer.offer_periodic(waiting)
            to_buffer += accepted
            waiting = waiting[accepted:]
            if not waiting:
                break
            if control.peak:
                control.shed_inbox.append((waiting, "peak"))
                to_shed = len(waiting)
                waiting = []
            else:
                self.stream_buffer.wait_for_room(0.2)

        log(f"[PERIODIC] Hour {control.hour}: group {group} extracted "
            f"({total:,} transactions) -> stream buffer {to_buffer:,}, "
            f"shed {to_shed:,}  [{control.arrival_mode()}]")
