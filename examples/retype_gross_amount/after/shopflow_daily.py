"""Daily ShopFlow extraction and dbt transformation DAG."""

from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.providers.snowflake.operators.snowflake import SnowflakeOperator


RECENT_ORDERS_SQL = """
select order_id, customer_id, order_placed_at, CAST(gross_amount AS NUMBER(12,2)) AS gross_amount
from shop_prod.raw.orders
where order_placed_at >= dateadd('day', -1, current_timestamp())
"""

PRODUCT_CATALOG_SQL = """
select product_id, sku, product_name, category, list_price
from shop_prod.raw.products
where product_id is not null
"""


with DAG(
    dag_id="shopflow_daily",
    description="Extract recent ShopFlow data and refresh the dbt warehouse.",
    start_date=datetime(2026, 1, 1),
    schedule="0 5 * * *",
    catchup=False,
    tags=["shopflow", "datahub-demo"],
) as dag:
    extract_recent_orders = SnowflakeOperator(
        task_id="extract_recent_orders",
        snowflake_conn_id="shopflow_snowflake",
        sql=RECENT_ORDERS_SQL,
    )

    refresh_product_catalog = SnowflakeOperator(
        task_id="refresh_product_catalog",
        snowflake_conn_id="shopflow_snowflake",
        sql=PRODUCT_CATALOG_SQL,
    )

    run_dbt_staging = BashOperator(
        task_id="run_dbt_staging",
        bash_command="cd /opt/airflow/demo-warehouse && dbt run --select staging",
    )

    run_dbt_marts = BashOperator(
        task_id="run_dbt_marts",
        bash_command="cd /opt/airflow/demo-warehouse && dbt run --select marts",
    )

    [extract_recent_orders, refresh_product_catalog] >> run_dbt_staging >> run_dbt_marts

