# MESHJOIN: stream buffer, hash table H, queue, disk buffer and the join thread
# master data R is read from mysql one partition (500 rows) at a time

import math
import threading
import traceback
from collections import deque
from datetime import datetime

import config
import db
from control import log
from loader import WarehouseLoader

LIVE = "Live"

CUSTOMER_PAGE_SQL = (
    "SELECT customer_id, gender, age_group, occupation, city_category, "
    "stay_in_current_city_years, marital_status "
    "FROM customer_master_data ORDER BY customer_id LIMIT %s OFFSET %s")
PRODUCT_PAGE_SQL = (
    "SELECT product_id, product_name, product_category, supplier_id, supplier_name "
    "FROM product_master_data ORDER BY product_id LIMIT %s OFFSET %s")
SHED_INSERT_SQL = (
    "INSERT INTO shed_table (transaction_id, customer_id, product_id, quantity, "
    "unit_price, event_time, sales_mode, shed_time) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)")
SHED_SELECT_SQL = (
    "SELECT shed_id, transaction_id, customer_id, product_id, quantity, "
    "unit_price, event_time, sales_mode FROM shed_table ORDER BY shed_id LIMIT %s")


class Transaction:
    # one tuple of the stream: one product in one shopping cart

    __slots__ = ("transaction_id", "customer_id", "product_id", "quantity",
                 "unit_price", "event_time", "sales_mode", "processing_mode",
                 "customer", "product")

    def __init__(self, transaction_id, customer_id, product_id, quantity,
                 unit_price, event_time, sales_mode, processing_mode):
        self.transaction_id = transaction_id
        self.customer_id = customer_id
        self.product_id = product_id
        self.quantity = quantity
        self.unit_price = unit_price
        self.event_time = event_time
        self.sales_mode = sales_mode
        self.processing_mode = processing_mode
        self.customer = None   # filled by the customer pass
        self.product = None    # filled by the product pass


class StreamBuffer:
    # bounded waiting area between the two source threads and MESHJOIN

    def __init__(self, limit):
        self.limit = limit
        self.live = deque()
        self.periodic = deque()
        self.changed = threading.Condition()

    def count(self):
        return len(self.live) + len(self.periodic)

    def counts(self):
        return len(self.live), len(self.periodic)

    def put_live(self, transaction, stop):
        # called by the OnlineThread. Waits only while the buffer is full
        with self.changed:
            while self.count() >= self.limit:
                if stop.is_set():
                    return False
                self.changed.wait(0.2)
            self.live.append(transaction)
        return True

    def offer_periodic(self, transactions):
        # take as many periodic transactions as fit; return how many
        with self.changed:
            room = self.limit - self.count()
            accepted = transactions[:room] if room > 0 else []
            self.periodic.extend(accepted)
            return len(accepted)

    def wait_for_room(self, timeout):
        with self.changed:
            if self.count() >= self.limit:
                self.changed.wait(timeout)

    def take_chunk(self, size):
        # up to `size` transactions: Live first, then periodic
        with self.changed:
            chunk = []
            while self.live and len(chunk) < size:
                chunk.append(self.live.popleft())
            while self.periodic and len(chunk) < size:
                chunk.append(self.periodic.popleft())
            self.changed.notify_all()
            return chunk


class HashTable:
    # H: multi-map holding the transactions that are in memory

    def __init__(self):
        self.by_customer = {}
        self.by_product = {}

    @staticmethod
    def _add(index, key, transaction):
        bucket = index.get(key)
        if bucket is None:
            bucket = index[key] = deque()
        bucket.append(transaction)

    @staticmethod
    def _remove_oldest(index, key):
        bucket = index[key]
        bucket.popleft()
        if not bucket:
            del index[key]

    def insert(self, transactions):
        for t in transactions:
            self._add(self.by_customer, t.customer_id, t)
            self._add(self.by_product, t.product_id, t)

    def remove_from_customer_pass(self, transactions):
        for t in transactions:
            self._remove_oldest(self.by_customer, t.customer_id)

    def remove_from_product_pass(self, transactions):
        for t in transactions:
            self._remove_oldest(self.by_product, t.product_id)


class Chunk:
    # one element of the queue: up to w transactions that arrived together

    __slots__ = ("transactions", "passes_left")

    def __init__(self, transactions):
        self.transactions = transactions
        self.passes_left = 2   # customer pass + product pass


class MeshJoinThread(threading.Thread):
    # runs the four MESHJOIN steps in a loop and owns the load shedding

    def __init__(self, settings, control, stream_buffer):
        super().__init__(name="MeshJoinThread", daemon=True)
        self.settings = settings
        self.control = control
        self.stream_buffer = stream_buffer
        self.hash_table = HashTable()
        self.customer_queue = deque()
        self.product_queue = deque()
        self.read_back_run = 0

    def run(self):
        try:
            self._run()
        except Exception as error:   # show the reason instead of dying silently
            self.control.failed = f"MeshJoinThread: {error}"
            traceback.print_exc()
            log("[ERROR] MeshJoinThread stopped. Type quit to close the program.")

    # ------------------------------------------------------------------
    def _count_partitions(self, cur, table):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        tuples = cur.fetchone()[0]
        return tuples, math.ceil(tuples / config.PARTITION_SIZE)

    def _read_partition(self, cur, sql, page):
        # step 1: bring one partition of R from disk into the disk buffer
        cur.execute(sql, (config.PARTITION_SIZE, page * config.PARTITION_SIZE))
        return cur.fetchall()

    # ---------------------------- load shedding -----------------------
    def _write_shed_requests(self, cur):
        # move the periodic transactions that did not fit to the shed table
        control = self.control
        while control.shed_inbox:
            transactions, arrival_mode = control.shed_inbox.popleft()
            now = datetime.now().replace(microsecond=0)
            rows = [(t.transaction_id, t.customer_id, t.product_id, t.quantity,
                     t.unit_price, t.event_time, t.sales_mode, now)
                    for t in transactions]
            for start in range(0, len(rows), 1000):
                cur.executemany(SHED_INSERT_SQL, rows[start:start + 1000])
            control.shed_on_disk += len(rows)
            if arrival_mode == "peak":
                control.shed_in_peak += len(rows)
            else:
                control.shed_in_non_peak += len(rows)
            log(f"[SHED] {len(rows):,} periodic transactions moved to shed_table "
                f"({arrival_mode}); on shed disk now: {control.shed_on_disk:,}")

    def _may_read_shed(self):
        control = self.control
        return (not control.peak and control.form_mode != "online"
                and control.shed_on_disk > 0)

    def _read_back_shed(self, cur, how_many):
        # non-peak only: fill the free part of a chunk from the shed disk
        cur.execute(SHED_SELECT_SQL, (how_many,))
        rows = cur.fetchall()
        if not rows:
            return []
        cur.execute("DELETE FROM shed_table WHERE shed_id <= %s", (rows[-1][0],))
        control = self.control
        control.shed_on_disk -= len(rows)
        control.shed_read_back += len(rows)
        self.read_back_run += len(rows)
        if control.shed_on_disk == 0:
            log(f"[SHED] shed_table is empty again: {self.read_back_run:,} "
                f"transactions read back into MESHJOIN")
            self.read_back_run = 0
        return [Transaction(r[1], r[2], r[3], r[4], r[5], r[6], r[7], config.PERIODIC)
                for r in rows]

    # ------------------------------------------------------------------
    def _run(self):
        control = self.control
        conn = db.connect(self.settings)
        cur = conn.cursor()
        loader = WarehouseLoader(conn, control)
        H = self.hash_table

        customers, customer_pages = self._count_partitions(cur, "customer_master_data")
        products, product_pages = self._count_partitions(cur, "product_master_data")
        control.customer_partitions = customer_pages
        control.product_partitions = product_pages
        log(f"[MESHJOIN] Master Data R: customer = {customers:,} tuples in "
            f"{customer_pages} partitions, product = {products:,} tuples in "
            f"{product_pages} partitions")
        log(f"[MESHJOIN] Queue: {customer_pages} chunks for the customer pass, "
            f"{product_pages} chunks for the product pass")

        customer_page = 0
        product_page = 0

        while not control.stop.is_set():
            self._write_shed_requests(cur)

            # Step 1: next partition of each Master Data table -> disk buffer
            customer_buffer = self._read_partition(cur, CUSTOMER_PAGE_SQL, customer_page)
            product_buffer = self._read_partition(cur, PRODUCT_PAGE_SQL, product_page)
            control.customer_page = customer_page + 1
            control.product_page = product_page + 1
            customer_page = (customer_page + 1) % customer_pages
            product_page = (product_page + 1) % product_pages

            # Step 2: one chunk (up to w) from the stream buffer -> H and queue.
            # Live first, then periodic; shed transactions only fill what is left.
            arrivals = self.stream_buffer.take_chunk(config.CHUNK_SIZE)
            if len(arrivals) < config.CHUNK_SIZE and self._may_read_shed():
                arrivals.extend(self._read_back_shed(cur, config.CHUNK_SIZE - len(arrivals)))
            chunk = Chunk(arrivals)
            H.insert(arrivals)
            self.customer_queue.append(chunk)
            self.product_queue.append(chunk)
            control.h_size += len(arrivals)
            control.queue_length = max(len(self.customer_queue), len(self.product_queue))

            # Step 3: probe H with every Master Data tuple in the disk buffer
            for row in customer_buffer:
                for transaction in H.by_customer.get(row[0], ()):
                    transaction.customer = row
            for row in product_buffer:
                for transaction in H.by_product.get(row[0], ()):
                    transaction.product = row

            # Step 4: the oldest chunk leaves a queue once it has met every
            # partition of that Master Data table; it is finished after both.
            finished = []
            if len(self.product_queue) == product_pages:
                oldest = self.product_queue.popleft()
                H.remove_from_product_pass(oldest.transactions)
                oldest.passes_left -= 1
                if oldest.passes_left == 0:
                    finished.append(oldest)
            if len(self.customer_queue) == customer_pages:
                oldest = self.customer_queue.popleft()
                H.remove_from_customer_pass(oldest.transactions)
                oldest.passes_left -= 1
                if oldest.passes_left == 0:
                    finished.append(oldest)

            # Output: consolidation and load into the DW
            for done in finished:
                control.h_size -= len(done.transactions)
                loader.accept(done.transactions)
            if control.flush_periodic.is_set():
                control.flush_periodic.clear()
                loader.load_waiting_periodic()

            conn.commit()
            control.iterations += 1
            self._report_progress()

            # A full chunk means more work may be waiting, so go straight on.
            if len(arrivals) < config.CHUNK_SIZE:
                control.stop.wait(config.ITERATION_PAUSE)

        loader.load_waiting_periodic()   # do not lose results that are already joined
        conn.commit()
        cur.close()
        conn.close()

    def _report_progress(self):
        # tell the user once when every transaction is in the DW
        control = self.control
        if control.all_done:
            return
        sources_done = (control.online_finished
                        and control.groups_total > 0
                        and control.groups_released == control.groups_total
                        and self.stream_buffer.count() == 0
                        and not control.shed_inbox
                        and control.h_size == 0
                        and control.periodic_waiting == 0)
        if sources_done and control.shed_on_disk == 0:
            control.all_done = True
            log(f"[DONE] All transactional data are reflected in the DW: "
                f"{control.loaded_live + control.loaded_periodic:,} fact tuples "
                f"(Live {control.loaded_live:,}, Periodic {control.loaded_periodic:,}). "
                f"Type quit to close.")
