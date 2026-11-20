# fixed settings from section 12 of the project handout

PARTITION_SIZE = 500        # Master Data tuples in one disk-buffer page
CHUNK_SIZE = 500            # w: transactions moved into H on each iteration
STREAM_BUFFER_LIMIT = 1000  # capacity of the stream buffer

PEAK_RATE = 80              # online transactions per second in peak time
NON_PEAK_RATE = 10          # online transactions per second in non-peak time
SECONDS_PER_HOUR = 60       # one simulated hour, in real seconds

PERIODIC_GROUPS = 48        # hourly groups in the staging table

# Pause between two MESHJOIN iterations when less than a full chunk was
# waiting. With a full chunk the next iteration starts immediately.
ITERATION_PAUSE = 0.5

ONLINE = "Online"
PERIODIC = "Periodic"

# store_id -> (store_name, city). Kept in memory, joined outside MESHJOIN.
STORE_LIST = {
    1: ("Online", "Web"),
    2: ("London Bridge", "London"),
    3: ("Manchester Arndale", "Manchester"),
    4: ("Birmingham Bullring", "Birmingham"),
    5: ("Edinburgh Princes", "Edinburgh"),
}

# Value lists for the Master Data rules. Index 0 is the first value.
GENDERS = ["Male", "Female"]
AGE_GROUPS = ["0-17", "18-25", "26-35", "36-45", "46-50", "51-55", "55+"]
OCCUPATIONS = ["Student", "Engineer", "Teacher", "Executive", "Clerk",
               "Healthcare", "Retail", "Homemaker", "Artist", "Other"]
CITY_CATEGORIES = ["A", "B", "C"]
STAY_YEARS = ["0", "1", "2", "3", "4+"]
MARITAL_STATUSES = ["Single", "Married"]
PRODUCT_CATEGORIES = ["Home Decor", "Kitchen", "Stationery", "Toys",
                      "Seasonal Gifts", "Bags", "Jewelry", "Garden",
                      "Party", "Other"]
SUPPLIERS = [
    ("SUP01", "Northwind Supplies"),
    ("SUP02", "Atlantic Gifts Ltd"),
    ("SUP03", "Midlands Wholesale"),
    ("SUP04", "Celtic Craft Co"),
    ("SUP05", "EuroPack Partners"),
]

# Column order of the online file and of a transaction everywhere else.
SALES_COLUMNS = ["transaction_id", "customer_id", "product_id", "quantity",
                 "unit_price", "event_time", "sales_mode"]
CUSTOMER_MD_COLUMNS = ["customer_id", "gender", "age_group", "occupation",
                       "city_category", "stay_in_current_city_years",
                       "marital_status"]
PRODUCT_MD_COLUMNS = ["product_id", "product_name", "product_category",
                      "supplier_id", "supplier_name"]
