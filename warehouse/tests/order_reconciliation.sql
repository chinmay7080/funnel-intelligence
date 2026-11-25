with expected as (
    select count(distinct transaction_id) as orders from {{ ref('stg_ga4_events') }}
    where event_name = 'purchase'
),
actual as (
    select count(*) as orders from {{ ref('fct_orders') }}
)
select e.orders from expected e cross join actual a where e.orders <> a.orders
