with source as (
    select * from {{ source('shop_raw', 'customers') }}
)
select
    customer_id,
    email,
    full_name,
    signup_date,
    country_code
    -- REMOVED BY schema-drift-repair (2026-08-01): upstream column dropped. marketing_opt_in
    -- TODO(data-team): confirm no consumer depends on this
from source

