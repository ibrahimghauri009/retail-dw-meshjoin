# step 2: read and clean the raw file, make the master data,
# write the online file and fill the periodic staging table

import math
import os

import pandas as pd

import config
import db
import rules

COLUMN_MAP = {
    "InvoiceNo": "transaction_id",
    "StockCode": "product_id",
    "Description": "product_name",
    "Quantity": "quantity",
    "InvoiceDate": "event_time",
    "UnitPrice": "unit_price",
    "CustomerID": "customer_id",
    "Country": "country",
}


def read_raw(raw_path):
    # load Online Retail.xlsx and rename the columns to the project names
    print(f"[PREP] Reading {raw_path} (this takes about a minute) ...")
    raw = pd.read_excel(raw_path, dtype={"InvoiceNo": str, "StockCode": str})
    raw = raw.rename(columns=COLUMN_MAP)
    raw["transaction_id"] = raw["transaction_id"].str.strip()
    raw["product_id"] = raw["product_id"].str.strip()
    return raw


def clean(raw):
    # apply the four cleaning tests of Section 3 and print the counts
    before = len(raw)
    bad_quantity = ~(raw["quantity"] > 0)
    bad_price = ~(raw["unit_price"] > 0)
    no_customer = raw["customer_id"].isna()
    cancelled = raw["transaction_id"].str.upper().str.startswith("C")

    cleaned = raw[~(bad_quantity | bad_price | no_customer | cancelled)].copy()
    after = len(cleaned)

    # CustomerID is read as 17850.0; the id used everywhere is the text "17850".
    cleaned["customer_id"] = cleaned["customer_id"].astype("int64").astype(str)
    cleaned["product_name"] = cleaned["product_name"].fillna("").astype(str).str.strip()
    cleaned = cleaned.reset_index(drop=True)

    counts = {
        "before": before,
        "after": after,
        "removed": before - after,
        "quantity_not_positive": int(bad_quantity.sum()),
        "price_not_positive": int(bad_price.sum()),
        "customer_missing": int(no_customer.sum()),
        "cancellations": int(cancelled.sum()),
    }
    print("[CLEAN] Transactions before cleaning :", f"{before:,}")
    print("[CLEAN]   quantity not above zero    :", f"{counts['quantity_not_positive']:,}")
    print("[CLEAN]   unit price not above zero  :", f"{counts['price_not_positive']:,}")
    print("[CLEAN]   customer id missing        :", f"{counts['customer_missing']:,}")
    print("[CLEAN]   cancellations (C invoices) :", f"{counts['cancellations']:,}")
    print("[CLEAN]   (one transaction can fail more than one test)")
    print("[CLEAN] Transactions after cleaning  :", f"{after:,}")
    return cleaned, counts


def split_by_sales_mode(cleaned):
    # mark every shopping cart Online or Periodic with the MD5 rule
    mode_of_cart = {tid: rules.sales_mode_of(tid)
                    for tid in cleaned["transaction_id"].unique()}
    cleaned["sales_mode"] = cleaned["transaction_id"].map(mode_of_cart)
    cleaned["event_time"] = cleaned["event_time"].dt.strftime("%Y-%m-%d %H:%M:%S")

    online = cleaned[cleaned["sales_mode"] == config.ONLINE]
    periodic = cleaned[cleaned["sales_mode"] == config.PERIODIC]
    online = online[config.SALES_COLUMNS].reset_index(drop=True)
    periodic = periodic[config.SALES_COLUMNS].reset_index(drop=True)

    total = len(cleaned)
    print(f"[SPLIT] Online transactions   : {len(online):,} "
          f"({100 * len(online) / total:.2f}%)")
    print(f"[SPLIT] Periodic transactions : {len(periodic):,} "
          f"({100 * len(periodic) / total:.2f}%)")
    return online, periodic


def make_periodic_groups(periodic):
    # sort by event_time and cut the sorted list into 48 groups (0..47)
    periodic = periodic.sort_values("event_time", kind="stable").reset_index(drop=True)
    total = len(periodic)
    base, extra = divmod(total, config.PERIODIC_GROUPS)
    release_hour = []
    for group in range(config.PERIODIC_GROUPS):
        size = base + 1 if group < extra else base   # sizes differ by at most 1
        release_hour.extend([group] * size)
    periodic["release_hour"] = release_hour
    periodic["released"] = 0

    sizes = periodic["release_hour"].value_counts()
    print(f"[PERIODIC] {config.PERIODIC_GROUPS} groups, smallest = {sizes.min():,} "
          f"transactions, largest = {sizes.max():,} transactions")
    return periodic


def build_customer_master(cleaned):
    # one tuple per customer id that survived cleaning
    # country on the first cleaned transaction of each customer
    first_country = cleaned.drop_duplicates("customer_id").set_index("customer_id")["country"]
    rows = [rules.customer_attributes(cid, first_country[cid])
            for cid in sorted(first_country.index)]
    return pd.DataFrame(rows, columns=config.CUSTOMER_MD_COLUMNS)


def build_product_master(cleaned):
    # one tuple per product id; the name is its longest Description
    longest = {}
    for pid, name in zip(cleaned["product_id"], cleaned["product_name"]):
        if pid not in longest or len(name) > len(longest[pid]):
            longest[pid] = name
    rows = [rules.product_attributes(pid, longest[pid] or "UNKNOWN")
            for pid in sorted(longest)]
    return pd.DataFrame(rows, columns=config.PRODUCT_MD_COLUMNS)


def to_tuples(frame):
    # dataframe -> list of tuples (plain python values)
    return list(zip(*[frame[col].tolist() for col in frame.columns]))


def _insert_sql(table, columns):
    marks = ", ".join(["%s"] * len(columns))
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks})"


def load_working_tables(settings, customers, products, periodic):
    # put the Master Data and the 48 periodic groups on disk (MySQL)
    conn = db.connect(settings)
    db.insert_many(conn, _insert_sql("customer_master_data", config.CUSTOMER_MD_COLUMNS),
                   to_tuples(customers))
    db.insert_many(conn, _insert_sql("product_master_data", config.PRODUCT_MD_COLUMNS),
                   to_tuples(products))
    staging_columns = config.SALES_COLUMNS + ["release_hour", "released"]
    db.insert_many(conn, _insert_sql("periodic_sales_data", staging_columns),
                   to_tuples(periodic[staging_columns]))
    conn.close()
    print("[PREP] Master Data and periodic_sales_data loaded into the database.")


def prepare(raw_path, online_path):
    # run the whole preparation in memory and write the three csv files
    raw = read_raw(raw_path)
    cleaned, counts = clean(raw)
    del raw

    customers = build_customer_master(cleaned)
    products = build_product_master(cleaned)
    online, periodic = split_by_sales_mode(cleaned)
    periodic = make_periodic_groups(periodic)

    data_dir = os.path.dirname(os.path.abspath(online_path))
    os.makedirs(data_dir, exist_ok=True)
    online.to_csv(online_path, index=False)
    customers.to_csv(os.path.join(data_dir, "customer_master_data.csv"), index=False)
    products.to_csv(os.path.join(data_dir, "product_master_data.csv"), index=False)

    customer_pages = math.ceil(len(customers) / config.PARTITION_SIZE)
    product_pages = math.ceil(len(products) / config.PARTITION_SIZE)
    print(f"[MD] Customer Master Data : {len(customers):,} tuples = "
          f"{customer_pages} partitions of {config.PARTITION_SIZE}")
    print(f"[MD] Product Master Data  : {len(products):,} tuples = "
          f"{product_pages} partitions of {config.PARTITION_SIZE}")
    print(f"[PREP] Online file written: {online_path}")

    group_sizes = periodic["release_hour"].value_counts()
    summary = dict(counts)
    summary.update({
        "online": len(online),
        "periodic": len(periodic),
        "customers": len(customers),
        "products": len(products),
        "customer_partitions": customer_pages,
        "product_partitions": product_pages,
        "smallest_group": int(group_sizes.min()),
        "largest_group": int(group_sizes.max()),
    })
    return customers, products, online, periodic, summary
