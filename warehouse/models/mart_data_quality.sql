with events as (
    select observed_date as report_date, count(*) as event_count,
           countif(session_key is null) as unassigned_events,
           countif(event_name = 'purchase') as purchase_events,
           countif(event_name = 'purchase' and session_key is null) as unassigned_purchases,
           countif(event_name = 'purchase' and transaction_id is null) as purchases_without_id,
           countif(event_name = 'view_item') as view_events,
           countif(event_name = 'view_item' and exists (
               select 1 from unnest(items) as {% if target.type == 'bigquery' %}item{% else %}i(item){% endif %}
               where {{ clean_label('item.item_id') }} is not null
           )) as view_events_with_item_id
    from {{ ref('stg_ga4_events') }}
    group by observed_date
),
order_stats as (
    select purchase_date as report_date, count(*) as orders,
           countif(revenue_usd is not null) as orders_with_revenue,
           sum(revenue_usd) as gross_revenue_usd,
           countif(spans_sessions) as cross_session_orders,
           countif(conflicting_revenue) as conflicting_orders
    from {{ ref('fct_orders') }}
    group by purchase_date
)
select events.*, coalesce(o.orders, 0) as orders, coalesce(o.orders_with_revenue, 0) as orders_with_revenue,
       o.gross_revenue_usd, coalesce(o.cross_session_orders, 0) as cross_session_orders,
       coalesce(o.conflicting_orders, 0) as conflicting_orders
from events left join order_stats o using (report_date)
