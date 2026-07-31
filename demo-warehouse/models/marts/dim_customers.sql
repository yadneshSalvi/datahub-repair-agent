select
    customer_id,
    email,
    full_name,
    signup_date,
    country_code,
    coalesce(marketing_opt_in, false) as is_marketable
from {{ ref('stg_customers') }}

