# data consolidation (revenue, store, time) and loading into the DW

from datetime import datetime
from decimal import Decimal

import config
import rules
from control import log

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
SEASON_OF_MONTH = {12: "Winter", 1: "Winter", 2: "Winter",
                   3: "Spring", 4: "Spring", 5: "Spring",
                   6: "Summer", 7: "Summer", 8: "Summer",
                   9: "Fall", 10: "Fall", 11: "Fall"}

FACT_SQL = (
    "INSERT INTO fact_sales (transaction_id, customer_key, product_key, "
    "supplier_key, store_key, time_key, quantity, unit_price, revenue, "
    "sales_mode, processing_mode) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
CUSTOMER_SQL = (
    "INSERT INTO dim_customer (customer_id, gender, age_group, occupation, "
    "city_category, stay_in_current_city_years, marital_status) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s)")
PRODUCT_SQL = (
    "INSERT INTO dim_product (product_id, product_name, product_category) "
    "VALUES (%s, %s, %s)")
SUPPLIER_SQL = "INSERT INTO dim_supplier (supplier_id, supplier_name) VALUES (%s, %s)"
STORE_SQL = "INSERT INTO dim_store (store_id, store_name, city) VALUES (%s, %s, %s)"
TIME_SQL = (
    "INSERT INTO dim_time (time_key, sale_date, sale_hour, day_of_month, "
    "month_num, month_name, quarter_num, year_num, day_of_week, day_type, "
    "season, half_year) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")


def time_tuple(moment):
    # all the time parts of one (date, hour) as a dim_time tuple
    time_key = int(moment.strftime("%Y%m%d%H"))
    weekday = moment.weekday()               # Monday = 0
    return (
        time_key,
        moment.date(),
        moment.hour,
        moment.day,
        moment.month,
        MONTH_NAMES[moment.month - 1],
        (moment.month - 1) // 3 + 1,
        moment.year,
        DAY_NAMES[weekday],
        "Weekday" if weekday < 5 else "Weekend",
        SEASON_OF_MONTH[moment.month],
        "H1" if moment.month <= 6 else "H2",
    )


class WarehouseLoader:
    def __init__(self, conn, control):
        self.conn = conn
        self.cur = conn.cursor()
        self.control = control
        # Surrogate keys of the dimension tuples this run has already put in
        # the DW (business id -> key). It only answers "is this dimension
        # value in the DW yet?"; the attributes always come from MESHJOIN.
        self.customer_keys = {}
        self.product_keys = {}
        self.supplier_keys = {}
        self.store_keys = {}
        self.time_keys = set()
        self.waiting_periodic = []

    def _dimension_key(self, known, business_id, sql, values):
        key = known.get(business_id)
        if key is None:
            self.cur.execute(sql, values)
            key = known[business_id] = self.cur.lastrowid
        return key

    def consolidate(self, t):
        # make one fact tuple from one fully enriched transaction
        customer_key = self._dimension_key(
            self.customer_keys, t.customer_id, CUSTOMER_SQL, t.customer)

        product_id, product_name, category, supplier_id, supplier_name = t.product
        product_key = self._dimension_key(
            self.product_keys, product_id, PRODUCT_SQL,
            (product_id, product_name, category))
        supplier_key = self._dimension_key(
            self.supplier_keys, supplier_id, SUPPLIER_SQL,
            (supplier_id, supplier_name))

        store_id = rules.store_id_of(t.transaction_id, t.sales_mode)
        store_name, city = config.STORE_LIST[store_id]
        store_key = self._dimension_key(
            self.store_keys, store_id, STORE_SQL, (store_id, store_name, city))

        moment = t.event_time
        if not isinstance(moment, datetime):
            moment = datetime.fromisoformat(moment)
        time_row = time_tuple(moment)
        time_key = time_row[0]
        if time_key not in self.time_keys:
            self.cur.execute(TIME_SQL, time_row)
            self.time_keys.add(time_key)

        unit_price = Decimal(str(t.unit_price))
        revenue = unit_price * t.quantity          # SALE = QUANTITY x PRICE

        return (t.transaction_id, customer_key, product_key, supplier_key,
                store_key, time_key, t.quantity, unit_price, revenue,
                t.sales_mode, t.processing_mode)

    def accept(self, transactions):
        # take the transactions of a chunk that has left MESHJOIN
        live_rows = []
        for t in transactions:
            if t.customer is None or t.product is None:
                self.control.unmatched += 1      # no Master Data tuple found
                continue
            row = self.consolidate(t)
            if t.processing_mode == "Live":
                live_rows.append(row)
            else:
                self.waiting_periodic.append(row)
        if live_rows:
            self.cur.executemany(FACT_SQL, live_rows)
            self.control.loaded_live += len(live_rows)
        self.control.periodic_waiting = len(self.waiting_periodic)

    def load_waiting_periodic(self):
        # hourly load of the periodic results that have been joined
        rows = self.waiting_periodic
        if not rows:
            return
        for start in range(0, len(rows), 1000):
            self.cur.executemany(FACT_SQL, rows[start:start + 1000])
        self.control.loaded_periodic += len(rows)
        log(f"[DW] Hourly load: {len(rows):,} periodic transactions inserted "
            f"into fact_sales")
        self.waiting_periodic = []
        self.control.periodic_waiting = 0
