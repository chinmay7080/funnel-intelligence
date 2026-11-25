with purchases as (
    select transaction_id, session_key, observed_date as purchase_date,
           revenue_usd, event_us,
           count(*) over (partition by transaction_id) as event_count,
           count(distinct session_key) over (partition by transaction_id) as session_count,
           min(revenue_usd) over (partition by transaction_id) as min_revenue,
           max(revenue_usd) over (partition by transaction_id) as max_revenue
    from {{ ref('stg_ga4_events') }}
    where event_name = 'purchase' and transaction_id is not null
    qualify row_number() over (
        partition by transaction_id order by event_us, observed_date, session_key, revenue_usd
    ) = 1
)
select transaction_id, session_key, purchase_date, revenue_usd, event_count,
       session_count > 1 as spans_sessions,
       coalesce(min_revenue <> max_revenue, false) as conflicting_revenue
from purchases
