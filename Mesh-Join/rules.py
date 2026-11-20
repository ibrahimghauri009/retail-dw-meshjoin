# the fixed MD5 rules from section 5.4 (no random numbers)

import hashlib

import config


def md5_number(text):
    # MD5 of the text (UTF-8), first 8 hex characters, as a whole number
    digest = hashlib.md5(str(text).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def stable(text, n):
    # md5_number(text) modulo n
    return md5_number(text) % n


def sales_mode_of(transaction_id):
    # remainder 0-6 -> Online, 7-9 -> Periodic. Decided per shopping cart
    if md5_number(transaction_id) % 10 <= 6:
        return config.ONLINE
    return config.PERIODIC


def store_id_of(transaction_id, sales_mode):
    # online carts use store 1; store carts get one of stores 2..5
    if sales_mode == config.ONLINE:
        return 1
    return 2 + md5_number(transaction_id) % 4


def customer_attributes(customer_id, country):
    # return the customer Master Data tuple for one customer id
    return (
        customer_id,
        config.GENDERS[stable(customer_id, 2)],
        config.AGE_GROUPS[stable(customer_id + "age", 7)],
        config.OCCUPATIONS[stable(customer_id + "occ", 10)],
        config.CITY_CATEGORIES[stable(customer_id + country, 3)],
        config.STAY_YEARS[stable(customer_id + "stay", 5)],
        config.MARITAL_STATUSES[stable(customer_id + "mar", 2)],
    )


def product_attributes(product_id, product_name):
    # return the product Master Data tuple for one product id
    supplier_id, supplier_name = config.SUPPLIERS[stable(product_id, 5)]
    return (
        product_id,
        product_name,
        config.PRODUCT_CATEGORIES[stable(product_id + "cat", 10)],
        supplier_id,
        supplier_name,
    )
