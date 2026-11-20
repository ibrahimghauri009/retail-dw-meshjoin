# shared state between the threads and the command loop

import threading
from collections import deque


class Control:
    def __init__(self, peak_rate, non_peak_rate, hour_seconds):
        self.stop = threading.Event()            # set by the quit command
        self.flush_periodic = threading.Event()  # set on every hour tick

        # switches changed by the commands
        self.form_mode = "both"      # both / online / periodic
        self.peak = True             # True = peak, False = non-peak
        self.peak_rate = peak_rate
        self.non_peak_rate = non_peak_rate
        self.hour_seconds = hour_seconds

        # periodic transactions handed to the MeshJoinThread for shedding;
        # every entry is (list of transactions, arrival mode when shed)
        self.shed_inbox = deque()

        # OnlineThread
        self.online_total = 0
        self.online_sent = 0
        self.online_finished = False

        # PeriodicThread
        self.hour = 0
        self.groups_total = 0
        self.groups_released = 0

        # MeshJoinThread
        self.iterations = 0
        self.h_size = 0
        self.customer_partitions = 0
        self.product_partitions = 0
        self.customer_page = 0
        self.product_page = 0
        self.queue_length = 0
        self.shed_on_disk = 0
        self.shed_in_peak = 0
        self.shed_in_non_peak = 0
        self.shed_read_back = 0
        self.loaded_live = 0
        self.loaded_periodic = 0
        self.periodic_waiting = 0    # joined, waiting for the hour to load
        self.unmatched = 0
        self.all_done = False
        self.failed = None

    def arrival_mode(self):
        return "peak" if self.peak else "non-peak"

    def rate(self):
        return self.peak_rate if self.peak else self.non_peak_rate


def log(message):
    print(message, flush=True)
