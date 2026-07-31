select
    customer_id,
    email,
    full_name,
    signup_date,
    country_code
    -- REMOVED BY schema-drift-repair (2026-08-01): upstream column dropped. coalesce(marketing_opt_in, false) as is_marketable
    -- TODO(data-team): confirm no consumer depends on this
from {{ ref('stg_customers') }}

