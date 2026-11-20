# small helper functions for mysql

import mysql.connector


def connect(settings, use_database=True):
    # open a new connection. Each thread opens its own
    args = {
        "host": settings["host"],
        "port": settings["port"],
        "user": settings["user"],
        "password": settings["password"],
    }
    if use_database:
        args["database"] = settings["database"]
    return mysql.connector.connect(**args)


def read_statements(script_path):
    # split a .sql file into single statements, without the comments
    lines = []
    with open(script_path, encoding="utf-8") as handle:
        for line in handle:
            code = line.split("--", 1)[0].rstrip()
            if code:
                lines.append(code)
    statements = " ".join(lines).split(";")
    return [s.strip() for s in statements if s.strip()]


def create_schema(settings, script_path):
    # step 1: drop the old objects and create the working tables and the DW
    conn = connect(settings, use_database=False)
    cur = conn.cursor()
    name = settings["database"].replace("`", "")
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}`")
    cur.execute(f"USE `{name}`")
    for statement in read_statements(script_path):
        first_word = statement.split()[0].upper()
        if first_word == "USE" or statement.upper().startswith("CREATE DATABASE"):
            continue
        cur.execute(statement)
    conn.commit()
    cur.close()
    conn.close()


def insert_many(conn, sql, rows, batch_size=5000):
    # insert a long list of tuples in batches
    cur = conn.cursor()
    for start in range(0, len(rows), batch_size):
        cur.executemany(sql, rows[start:start + batch_size])
        conn.commit()
    cur.close()


def reset_for_rerun(settings):
    # used by --skip-prep: keep the prepared data, empty everything else
    conn = connect(settings)
    cur = conn.cursor()
    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    for table in ("fact_sales", "dim_customer", "dim_product", "dim_supplier",
                  "dim_store", "dim_time", "shed_table"):
        cur.execute(f"TRUNCATE TABLE {table}")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    cur.execute("UPDATE periodic_sales_data SET released = 0")
    conn.commit()
    cur.close()
    conn.close()
