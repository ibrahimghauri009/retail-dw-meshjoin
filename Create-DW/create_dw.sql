-- DW project (DS3003) - create_dw.sql
-- makes the working tables + the star schema. drops old stuff first so it can be run again

CREATE DATABASE IF NOT EXISTS retail_dw;
USE retail_dw;

-- drop old copies (view first, then the fact table because it has the FKs)
DROP VIEW  IF EXISTS STORE_QUARTERLY_SALES;

DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_supplier;
DROP TABLE IF EXISTS dim_store;
DROP TABLE IF EXISTS dim_time;

DROP TABLE IF EXISTS shed_table;
DROP TABLE IF EXISTS periodic_sales_data;
DROP TABLE IF EXISTS customer_master_data;
DROP TABLE IF EXISTS product_master_data;


-- ---------- working tables ----------

-- customer master data (read 500 rows at a time by MESHJOIN)
CREATE TABLE customer_master_data (
    customer_id                 VARCHAR(10)  NOT NULL,
    gender                      VARCHAR(6)   NOT NULL,
    age_group                   VARCHAR(5)   NOT NULL,
    occupation                  VARCHAR(12)  NOT NULL,
    city_category               CHAR(1)      NOT NULL,
    stay_in_current_city_years  VARCHAR(2)   NOT NULL,
    marital_status              VARCHAR(7)   NOT NULL,
    PRIMARY KEY (customer_id)
) ENGINE = InnoDB;

-- product master data
CREATE TABLE product_master_data (
    product_id        VARCHAR(20)   NOT NULL,
    product_name      VARCHAR(100)  NOT NULL,
    product_category  VARCHAR(15)   NOT NULL,
    supplier_id       VARCHAR(5)    NOT NULL,
    supplier_name     VARCHAR(40)   NOT NULL,
    PRIMARY KEY (product_id)
) ENGINE = InnoDB;

-- staging table for the store (periodic) sales, 48 groups in release_hour, released = 1 after extraction
CREATE TABLE periodic_sales_data (
    staging_id      INT            NOT NULL AUTO_INCREMENT,
    transaction_id  VARCHAR(10)    NOT NULL,
    customer_id     VARCHAR(10)    NOT NULL,
    product_id      VARCHAR(20)    NOT NULL,
    quantity        INT            NOT NULL,
    unit_price      DECIMAL(10,3)  NOT NULL,
    event_time      DATETIME       NOT NULL,
    sales_mode      VARCHAR(8)     NOT NULL DEFAULT 'Periodic',
    release_hour    TINYINT        NOT NULL,
    released        TINYINT(1)     NOT NULL DEFAULT 0,
    PRIMARY KEY (staging_id),
    INDEX idx_release (release_hour, released)
) ENGINE = InnoDB;

-- periodic transactions shed to disk in peak time
CREATE TABLE shed_table (
    shed_id         INT            NOT NULL AUTO_INCREMENT,
    transaction_id  VARCHAR(10)    NOT NULL,
    customer_id     VARCHAR(10)    NOT NULL,
    product_id      VARCHAR(20)    NOT NULL,
    quantity        INT            NOT NULL,
    unit_price      DECIMAL(10,3)  NOT NULL,
    event_time      DATETIME       NOT NULL,
    sales_mode      VARCHAR(8)     NOT NULL,
    shed_time       DATETIME       NOT NULL,
    PRIMARY KEY (shed_id)
) ENGINE = InnoDB;


-- ---------- star schema ----------
-- every dimension has a surrogate key and also keeps the original id

CREATE TABLE dim_customer (
    customer_key                INT          NOT NULL AUTO_INCREMENT,
    customer_id                 VARCHAR(10)  NOT NULL,
    gender                      VARCHAR(6)   NOT NULL,
    age_group                   VARCHAR(5)   NOT NULL,
    occupation                  VARCHAR(12)  NOT NULL,
    city_category               CHAR(1)      NOT NULL,
    stay_in_current_city_years  VARCHAR(2)   NOT NULL,
    marital_status              VARCHAR(7)   NOT NULL,
    PRIMARY KEY (customer_key),
    UNIQUE KEY uq_customer_id (customer_id)
) ENGINE = InnoDB;

CREATE TABLE dim_product (
    product_key       INT           NOT NULL AUTO_INCREMENT,
    product_id        VARCHAR(20)   NOT NULL,
    product_name      VARCHAR(100)  NOT NULL,
    product_category  VARCHAR(15)   NOT NULL,
    PRIMARY KEY (product_key),
    UNIQUE KEY uq_product_id (product_id)
) ENGINE = InnoDB;

CREATE TABLE dim_supplier (
    supplier_key   INT          NOT NULL AUTO_INCREMENT,
    supplier_id    VARCHAR(5)   NOT NULL,
    supplier_name  VARCHAR(40)  NOT NULL,
    PRIMARY KEY (supplier_key),
    UNIQUE KEY uq_supplier_id (supplier_id)
) ENGINE = InnoDB;

CREATE TABLE dim_store (
    store_key   INT          NOT NULL AUTO_INCREMENT,
    store_id    INT          NOT NULL,
    store_name  VARCHAR(30)  NOT NULL,
    city        VARCHAR(20)  NOT NULL,
    PRIMARY KEY (store_key),
    UNIQUE KEY uq_store_id (store_id)
) ENGINE = InnoDB;

-- one row per date + hour, time_key looks like 2010120108
CREATE TABLE dim_time (
    time_key      INT          NOT NULL,
    sale_date     DATE         NOT NULL,
    sale_hour     TINYINT      NOT NULL,
    day_of_month  TINYINT      NOT NULL,
    month_num     TINYINT      NOT NULL,
    month_name    VARCHAR(9)   NOT NULL,
    quarter_num   TINYINT      NOT NULL,
    year_num      SMALLINT     NOT NULL,
    day_of_week   VARCHAR(9)   NOT NULL,
    day_type      VARCHAR(7)   NOT NULL,   -- Weekday / Weekend
    season        VARCHAR(6)   NOT NULL,   -- Spring / Summer / Fall / Winter
    half_year     CHAR(2)      NOT NULL,   -- H1 / H2
    PRIMARY KEY (time_key),
    UNIQUE KEY uq_date_hour (sale_date, sale_hour)
) ENGINE = InnoDB;

-- fact table: one row = one product in one cart, revenue = quantity * unit_price
-- sale_key is the PK because the same product can be twice in one cart
CREATE TABLE fact_sales (
    sale_key         BIGINT         NOT NULL AUTO_INCREMENT,
    transaction_id   VARCHAR(10)    NOT NULL,
    customer_key     INT            NOT NULL,
    product_key      INT            NOT NULL,
    supplier_key     INT            NOT NULL,
    store_key        INT            NOT NULL,
    time_key         INT            NOT NULL,
    quantity         INT            NOT NULL,
    unit_price       DECIMAL(10,3)  NOT NULL,
    revenue          DECIMAL(14,3)  NOT NULL,
    sales_mode       VARCHAR(8)     NOT NULL,   -- Online / Periodic
    processing_mode  VARCHAR(8)     NOT NULL,
    PRIMARY KEY (sale_key),
    INDEX idx_fact_transaction (transaction_id),
    CONSTRAINT fk_fact_customer FOREIGN KEY (customer_key) REFERENCES dim_customer (customer_key),
    CONSTRAINT fk_fact_product  FOREIGN KEY (product_key)  REFERENCES dim_product  (product_key),
    CONSTRAINT fk_fact_supplier FOREIGN KEY (supplier_key) REFERENCES dim_supplier (supplier_key),
    CONSTRAINT fk_fact_store    FOREIGN KEY (store_key)    REFERENCES dim_store    (store_key),
    CONSTRAINT fk_fact_time     FOREIGN KEY (time_key)     REFERENCES dim_time     (time_key)
) ENGINE = InnoDB;
