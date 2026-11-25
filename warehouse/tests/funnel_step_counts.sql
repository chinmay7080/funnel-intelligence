select * from {{ ref('mart_daily_funnel') }}
where sessions < views or views < adds or adds < checkouts
   or checkouts < ordered_purchases or purchasing_sessions < ordered_purchases
   or purchasing_sessions > sessions
