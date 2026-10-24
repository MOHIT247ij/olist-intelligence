-- Applied automatically after ETL load when DATABASE_URL points to PostgreSQL.
-- Star schema keys + indexes for dashboard / AI query performance.

ALTER TABLE dim_customer ADD PRIMARY KEY (customer_unique_id);
ALTER TABLE dim_product  ADD PRIMARY KEY (product_id);
ALTER TABLE dim_seller   ADD PRIMARY KEY (seller_id);
ALTER TABLE dim_date     ADD PRIMARY KEY (date_key);
ALTER TABLE fact_orders  ADD PRIMARY KEY (order_id);
ALTER TABLE fact_order_items ADD PRIMARY KEY (order_id, order_item_id);

ALTER TABLE fact_orders ADD CONSTRAINT fk_orders_customer FOREIGN KEY (customer_unique_id) REFERENCES dim_customer (customer_unique_id);
ALTER TABLE fact_orders ADD CONSTRAINT fk_orders_date     FOREIGN KEY (date_key) REFERENCES dim_date (date_key);
ALTER TABLE fact_order_items ADD CONSTRAINT fk_items_order   FOREIGN KEY (order_id) REFERENCES fact_orders (order_id);
ALTER TABLE fact_order_items ADD CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES dim_product (product_id);
ALTER TABLE fact_order_items ADD CONSTRAINT fk_items_seller  FOREIGN KEY (seller_id) REFERENCES dim_seller (seller_id);

CREATE INDEX IF NOT EXISTS ix_orders_purchase_date ON fact_orders (purchase_date);
CREATE INDEX IF NOT EXISTS ix_orders_customer      ON fact_orders (customer_unique_id);
CREATE INDEX IF NOT EXISTS ix_orders_state         ON fact_orders (customer_state);
CREATE INDEX IF NOT EXISTS ix_items_product        ON fact_order_items (product_id);
CREATE INDEX IF NOT EXISTS ix_items_category       ON fact_order_items (category);
CREATE INDEX IF NOT EXISTS ix_items_seller         ON fact_order_items (seller_id);
