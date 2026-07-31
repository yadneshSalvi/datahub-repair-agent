with source as (
    select * from {{ source('shop_raw', 'customers') }}
)
select
    customer_id,
    email,
    full_name,
    signup_date,
    country_code,
    marketing_opt_in
from source

