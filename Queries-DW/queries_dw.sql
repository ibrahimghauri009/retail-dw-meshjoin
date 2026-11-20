-- DW project (DS3003) - queries_dw.sql : the 20 OLAP queries
-- dates loaded in the DW: 1 Dec 2010 to 9 Dec 2011 (2010 only has December)
-- so when a question says 'the year' I used 2011 (1 Jan 2011 - 9 Dec 2011)
-- note: the data has no Saturday sales, so weekend = Sunday only
-- all money values use the revenue column stored in fact_sales

USE retail_dw;


-- Q1. top 5 products by revenue on weekdays and weekends, drilled down by month
-- year: 2011 (1 Jan - 9 Dec 2011). ranks the products for the whole year, then shows their months
SELECT day_type,
       revenue_rank,
       product_id,
       product_name,
       ROUND(year_revenue, 2)  AS year_revenue,
       month_num,
       month_name,
       ROUND(month_revenue, 2) AS month_revenue
FROM (
    SELECT m.*,
           DENSE_RANK() OVER (PARTITION BY day_type ORDER BY year_revenue DESC) AS revenue_rank
    FROM (
        SELECT t.day_type,
               p.product_key,
               p.product_id,
               p.product_name,
               t.month_num,
               t.month_name,
               SUM(f.revenue) AS month_revenue,
               SUM(SUM(f.revenue)) OVER (PARTITION BY t.day_type, p.product_key) AS year_revenue
        FROM fact_sales f
        JOIN dim_time    t ON t.time_key    = f.time_key
        JOIN dim_product p ON p.product_key = f.product_key
        WHERE t.year_num = 2011
        GROUP BY t.day_type, p.product_key, p.product_id, p.product_name,
                 t.month_num, t.month_name
    ) m
) ranked
WHERE revenue_rank <= 5
ORDER BY day_type, revenue_rank, product_id, month_num;


-- Q2. purchase amount by gender and age group, split by city category
-- period: all loaded data (1 Dec 2010 - 9 Dec 2011)
SELECT c.gender,
       c.age_group,
       c.city_category,
       COUNT(DISTINCT c.customer_key) AS customers,
       ROUND(SUM(f.revenue), 2)       AS purchase_amount
FROM fact_sales f
JOIN dim_customer c ON c.customer_key = f.customer_key
GROUP BY c.gender, c.age_group, c.city_category
ORDER BY c.gender, c.age_group, c.city_category;


-- Q3. product category sales by occupation
-- period: all loaded data (1 Dec 2010 - 9 Dec 2011)
SELECT p.product_category,
       c.occupation,
       SUM(f.quantity)           AS quantity_sold,
       ROUND(SUM(f.revenue), 2)  AS total_sales
FROM fact_sales f
JOIN dim_product  p ON p.product_key  = f.product_key
JOIN dim_customer c ON c.customer_key = f.customer_key
GROUP BY p.product_category, c.occupation
ORDER BY p.product_category, total_sales DESC;


-- Q4. purchases by gender and age group per quarter, with % change from last quarter
-- year: 2011, Q4 only goes up to 9 Dec 2011
SELECT gender,
       age_group,
       CONCAT('2011-Q', quarter_num)  AS quarter,
       ROUND(purchase_amount, 2)      AS purchase_amount,
       ROUND(LAG(purchase_amount) OVER w, 2) AS previous_quarter,
       ROUND(100 * (purchase_amount - LAG(purchase_amount) OVER w)
             / LAG(purchase_amount) OVER w, 2) AS change_pct
FROM (
    SELECT c.gender,
           c.age_group,
           t.quarter_num,
           SUM(f.revenue) AS purchase_amount
    FROM fact_sales f
    JOIN dim_customer c ON c.customer_key = f.customer_key
    JOIN dim_time     t ON t.time_key     = f.time_key
    WHERE t.year_num = 2011
    GROUP BY c.gender, c.age_group, t.quarter_num
) q
WINDOW w AS (PARTITION BY gender, age_group ORDER BY quarter_num)
ORDER BY gender, age_group, quarter_num;


-- Q5. top 5 occupations in each product category
-- period: all loaded data (1 Dec 2010 - 9 Dec 2011)
SELECT product_category,
       sales_rank,
       occupation,
       ROUND(total_sales, 2) AS total_sales
FROM (
    SELECT p.product_category,
           c.occupation,
           SUM(f.revenue) AS total_sales,
           RANK() OVER (PARTITION BY p.product_category ORDER BY SUM(f.revenue) DESC) AS sales_rank
    FROM fact_sales f
    JOIN dim_product  p ON p.product_key  = f.product_key
    JOIN dim_customer c ON c.customer_key = f.customer_key
    GROUP BY p.product_category, c.occupation
) x
WHERE sales_rank <= 5
ORDER BY product_category, sales_rank;


-- Q6. city category and marital status, month by month, for the latest 6 months
-- latest 6 months in the DW = July 2011 to December 2011 (Dec stops on 9 Dec)
SELECT t.year_num,
       t.month_num,
       t.month_name,
       c.city_category,
       c.marital_status,
       ROUND(SUM(f.revenue), 2) AS purchase_amount
FROM fact_sales f
JOIN dim_time     t ON t.time_key     = f.time_key
JOIN dim_customer c ON c.customer_key = f.customer_key
WHERE t.year_num = 2011
  AND t.month_num BETWEEN 7 AND 12
GROUP BY t.year_num, t.month_num, t.month_name, c.city_category, c.marital_status
ORDER BY t.year_num, t.month_num, c.city_category, c.marital_status;


-- Q7. average purchase amount by years in city and gender
-- average revenue of one transaction (one product in one cart). period: all loaded data
SELECT c.stay_in_current_city_years,
       c.gender,
       COUNT(*)                  AS transactions,
       ROUND(AVG(f.revenue), 2)  AS avg_purchase_amount
FROM fact_sales f
JOIN dim_customer c ON c.customer_key = f.customer_key
GROUP BY c.stay_in_current_city_years, c.gender
ORDER BY c.stay_in_current_city_years, c.gender;


-- Q8. city categories (A, B, C) ranked by revenue in each product category
-- period: all loaded data (1 Dec 2010 - 9 Dec 2011)
SELECT p.product_category,
       RANK() OVER (PARTITION BY p.product_category ORDER BY SUM(f.revenue) DESC) AS city_rank,
       c.city_category,
       ROUND(SUM(f.revenue), 2) AS revenue
FROM fact_sales f
JOIN dim_product  p ON p.product_key  = f.product_key
JOIN dim_customer c ON c.customer_key = f.customer_key
GROUP BY p.product_category, c.city_category
ORDER BY p.product_category, city_rank;


-- Q9. month over month sales growth % per product category
-- year: 2011. Jan 2011 is compared with Dec 2010. Dec 2011 is only 9 days so it drops
SELECT product_category,
       year_num,
       month_num,
       ROUND(sales, 2)           AS sales,
       ROUND(previous_sales, 2)  AS previous_month_sales,
       ROUND(100 * (sales - previous_sales) / previous_sales, 2) AS growth_pct
FROM (
    SELECT m.*,
           LAG(sales) OVER (PARTITION BY product_category ORDER BY year_num, month_num) AS previous_sales
    FROM (
        SELECT p.product_category,
               t.year_num,
               t.month_num,
               SUM(f.revenue) AS sales
        FROM fact_sales f
        JOIN dim_product p ON p.product_key = f.product_key
        JOIN dim_time    t ON t.time_key    = f.time_key
        GROUP BY p.product_category, t.year_num, t.month_num
    ) m
) g
WHERE year_num = 2011
ORDER BY product_category, year_num, month_num;


-- Q10. weekday vs weekend sales by age group
-- year: 2011 (1 Jan - 9 Dec 2011)
SELECT c.age_group,
       ROUND(SUM(CASE WHEN t.day_type = 'Weekday' THEN f.revenue ELSE 0 END), 2) AS weekday_sales,
       ROUND(SUM(CASE WHEN t.day_type = 'Weekend' THEN f.revenue ELSE 0 END), 2) AS weekend_sales
FROM fact_sales f
JOIN dim_customer c ON c.customer_key = f.customer_key
JOIN dim_time     t ON t.time_key     = f.time_key
WHERE t.year_num = 2011
GROUP BY c.age_group
ORDER BY c.age_group;


-- Q11. top 5 products on weekdays and weekends inside every month
-- year: 2011. different from Q1 because the ranking is done again for each month
SELECT month_num,
       month_name,
       day_type,
       revenue_rank,
       product_id,
       product_name,
       ROUND(revenue, 2) AS revenue
FROM (
    SELECT t.month_num,
           t.month_name,
           t.day_type,
           p.product_id,
           p.product_name,
           SUM(f.revenue) AS revenue,
           RANK() OVER (PARTITION BY t.month_num, t.day_type ORDER BY SUM(f.revenue) DESC) AS revenue_rank
    FROM fact_sales f
    JOIN dim_time    t ON t.time_key    = f.time_key
    JOIN dim_product p ON p.product_key = f.product_key
    WHERE t.year_num = 2011
    GROUP BY t.month_num, t.month_name, t.day_type, p.product_id, p.product_name
) x
WHERE revenue_rank <= 5
ORDER BY month_num, day_type, revenue_rank;


-- Q12. revenue growth % of each store from one quarter to the next
-- year: 2011, Q1 has no previous quarter so its growth is NULL
SELECT store_id,
       store_name,
       CONCAT('2011-Q', quarter_num)  AS quarter,
       ROUND(revenue, 2)              AS revenue,
       ROUND(LAG(revenue) OVER w, 2)  AS previous_quarter_revenue,
       ROUND(100 * (revenue - LAG(revenue) OVER w) / LAG(revenue) OVER w, 2) AS growth_pct
FROM (
    SELECT s.store_id,
           s.store_name,
           t.quarter_num,
           SUM(f.revenue) AS revenue
    FROM fact_sales f
    JOIN dim_store s ON s.store_key = f.store_key
    JOIN dim_time  t ON t.time_key  = f.time_key
    WHERE t.year_num = 2011
    GROUP BY s.store_id, s.store_name, t.quarter_num
) q
WINDOW w AS (PARTITION BY store_id ORDER BY quarter_num)
ORDER BY store_id, quarter_num;


-- Q13. supplier contribution per store, broken down by product name
-- grouped by store, then supplier, then product name. period: all loaded data
SELECT s.store_name,
       sp.supplier_name,
       p.product_name,
       SUM(f.quantity)           AS quantity_sold,
       ROUND(SUM(f.revenue), 2)  AS product_sales
FROM fact_sales f
JOIN dim_store    s  ON s.store_key     = f.store_key
JOIN dim_supplier sp ON sp.supplier_key = f.supplier_key
JOIN dim_product  p  ON p.product_key   = f.product_key
GROUP BY s.store_name, sp.supplier_name, p.product_name
ORDER BY s.store_name, sp.supplier_name, p.product_name;


-- Q14. sales of each product by season
-- spring = Mar-May 2011, summer = Jun-Aug 2011, fall = Sep-Nov 2011,
-- winter = Dec 2010, Jan-Feb 2011 and 1-9 Dec 2011
SELECT p.product_id,
       p.product_name,
       ROUND(SUM(CASE WHEN t.season = 'Spring' THEN f.revenue ELSE 0 END), 2) AS spring_sales,
       ROUND(SUM(CASE WHEN t.season = 'Summer' THEN f.revenue ELSE 0 END), 2) AS summer_sales,
       ROUND(SUM(CASE WHEN t.season = 'Fall'   THEN f.revenue ELSE 0 END), 2) AS fall_sales,
       ROUND(SUM(CASE WHEN t.season = 'Winter' THEN f.revenue ELSE 0 END), 2) AS winter_sales,
       ROUND(SUM(f.revenue), 2)                                               AS total_sales
FROM fact_sales f
JOIN dim_product p ON p.product_key = f.product_key
JOIN dim_time    t ON t.time_key    = f.time_key
GROUP BY p.product_key, p.product_id, p.product_name
ORDER BY total_sales DESC;


-- Q15. monthly revenue volatility (% change from last month) for each store + supplier
-- period: Dec 2010 to Dec 2011 (Dec 2011 stops on 9 Dec)
SELECT store_name,
       supplier_name,
       year_num,
       month_num,
       ROUND(revenue, 2)              AS revenue,
       ROUND(LAG(revenue) OVER w, 2)  AS previous_month_revenue,
       ROUND(100 * (revenue - LAG(revenue) OVER w) / LAG(revenue) OVER w, 2) AS volatility_pct
FROM (
    SELECT s.store_id,
           s.store_name,
           sp.supplier_id,
           sp.supplier_name,
           t.year_num,
           t.month_num,
           SUM(f.revenue) AS revenue
    FROM fact_sales f
    JOIN dim_store    s  ON s.store_key     = f.store_key
    JOIN dim_supplier sp ON sp.supplier_key = f.supplier_key
    JOIN dim_time     t  ON t.time_key      = f.time_key
    GROUP BY s.store_id, s.store_name, sp.supplier_id, sp.supplier_name, t.year_num, t.month_num
) x
WINDOW w AS (PARTITION BY store_id, supplier_id ORDER BY year_num, month_num)
ORDER BY store_id, supplier_id, year_num, month_num;


-- Q16. top 5 product pairs bought together (counted once per shopping cart)
-- period: all loaded data. tmp_table_size is raised only for this query or it takes
-- minutes (about 9 million pairs), then it is set back
SET SESSION tmp_table_size = 536870912;

SELECT p1.product_id    AS product_1_id,
       p1.product_name  AS product_1_name,
       p2.product_id    AS product_2_id,
       p2.product_name  AS product_2_name,
       pc.carts_together
FROM (
    SELECT a.product_key AS product_1_key,
           b.product_key AS product_2_key,
           COUNT(*)      AS carts_together
    FROM (SELECT DISTINCT transaction_id, product_key FROM fact_sales) a
    JOIN (SELECT DISTINCT transaction_id, product_key FROM fact_sales) b
         ON b.transaction_id = a.transaction_id
        AND b.product_key    > a.product_key
    GROUP BY a.product_key, b.product_key
    ORDER BY carts_together DESC, product_1_key, product_2_key
    LIMIT 5
) pc
JOIN dim_product p1 ON p1.product_key = pc.product_1_key
JOIN dim_product p2 ON p2.product_key = pc.product_2_key
ORDER BY pc.carts_together DESC, p1.product_id, p2.product_id;

SET SESSION tmp_table_size = DEFAULT;


-- Q17. 2011 revenue by store, supplier and product with ROLLUP
-- gives product rows, supplier subtotals, store subtotals and the grand total
SELECT 2011 AS year_num,
       IF(GROUPING(s.store_name) = 1, 'ALL STORES', s.store_name)            AS store_name,
       IF(GROUPING(sp.supplier_name) = 1, 'ALL SUPPLIERS', sp.supplier_name) AS supplier_name,
       IF(GROUPING(p.product_id) = 1, 'ALL PRODUCTS', p.product_id)          AS product_id,
       IF(GROUPING(p.product_id) = 1, 'ALL PRODUCTS', MAX(p.product_name))   AS product_name,
       CASE WHEN GROUPING(s.store_name) = 1     THEN 'Grand total'
            WHEN GROUPING(sp.supplier_name) = 1 THEN 'Store subtotal'
            WHEN GROUPING(p.product_id) = 1     THEN 'Supplier subtotal'
            ELSE 'Product'
       END                                                                   AS level_name,
       ROUND(SUM(f.revenue), 2)                                              AS revenue
FROM fact_sales f
JOIN dim_store    s  ON s.store_key     = f.store_key
JOIN dim_supplier sp ON sp.supplier_key = f.supplier_key
JOIN dim_product  p  ON p.product_key   = f.product_key
JOIN dim_time     t  ON t.time_key      = f.time_key
WHERE t.year_num = 2011
GROUP BY s.store_name, sp.supplier_name, p.product_id WITH ROLLUP;


-- Q18. quantity and revenue per product for H1, H2 and the full year
-- year: 2011. H1 = Jan-Jun 2011, H2 = Jul - 9 Dec 2011
SELECT p.product_id,
       p.product_name,
       SUM(CASE WHEN t.half_year = 'H1' THEN f.quantity ELSE 0 END)           AS h1_quantity,
       ROUND(SUM(CASE WHEN t.half_year = 'H1' THEN f.revenue ELSE 0 END), 2)  AS h1_revenue,
       SUM(CASE WHEN t.half_year = 'H2' THEN f.quantity ELSE 0 END)           AS h2_quantity,
       ROUND(SUM(CASE WHEN t.half_year = 'H2' THEN f.revenue ELSE 0 END), 2)  AS h2_revenue,
       SUM(f.quantity)                                                        AS year_quantity,
       ROUND(SUM(f.revenue), 2)                                               AS year_revenue
FROM fact_sales f
JOIN dim_product p ON p.product_key = f.product_key
JOIN dim_time    t ON t.time_key    = f.time_key
WHERE t.year_num = 2011
GROUP BY p.product_key, p.product_id, p.product_name
ORDER BY year_revenue DESC;


-- Q19. revenue spikes: days where a product made more than 2x its own daily average
-- average is taken over the days the product was sold. period: all loaded data
SELECT product_id,
       product_name,
       sale_date,
       ROUND(daily_revenue, 2)                      AS daily_revenue,
       ROUND(avg_daily_revenue, 2)                  AS avg_daily_revenue,
       ROUND(daily_revenue / avg_daily_revenue, 2)  AS times_the_average
FROM (
    SELECT d.*,
           AVG(daily_revenue) OVER (PARTITION BY product_key) AS avg_daily_revenue
    FROM (
        SELECT p.product_key,
               p.product_id,
               p.product_name,
               t.sale_date,
               SUM(f.revenue) AS daily_revenue
        FROM fact_sales f
        JOIN dim_product p ON p.product_key = f.product_key
        JOIN dim_time    t ON t.time_key    = f.time_key
        GROUP BY p.product_key, p.product_id, p.product_name, t.sale_date
    ) d
) x
WHERE daily_revenue > 2 * avg_daily_revenue
ORDER BY times_the_average DESC, daily_revenue DESC;


-- Q20. view STORE_QUARTERLY_SALES = total sales per store per quarter
-- quarters loaded: 2010-Q4 (Dec only) to 2011-Q4 (up to 9 Dec)
-- MySQL ignores ORDER BY inside a view, so the ordering is on the select below
DROP VIEW IF EXISTS STORE_QUARTERLY_SALES;

CREATE VIEW STORE_QUARTERLY_SALES AS
SELECT s.store_id,
       s.store_name,
       s.city,
       t.year_num,
       t.quarter_num,
       CONCAT(t.year_num, '-Q', t.quarter_num) AS quarter,
       SUM(f.quantity)                         AS total_quantity,
       SUM(f.revenue)                          AS total_sales
FROM fact_sales f
JOIN dim_store s ON s.store_key = f.store_key
JOIN dim_time  t ON t.time_key  = f.time_key
GROUP BY s.store_id, s.store_name, s.city, t.year_num, t.quarter_num;

SELECT store_name,
       quarter,
       total_quantity,
       ROUND(total_sales, 2) AS total_sales
FROM STORE_QUARTERLY_SALES
ORDER BY store_name, year_num, quarter_num;
