with eligible as (
    select count(distinct session_key) as eligible_sessions,
           count(distinct case when event_name = 'purchase' then session_key end) as purchasing_sessions
    from {{ ref('stg_ga4_events') }}
),
reported as (
    select sum(sessions) as sessions, sum(purchasing_sessions) as purchasing_sessions
    from {{ ref('mart_daily_funnel') }}
)
select * from eligible e cross join reported r
where e.eligible_sessions <> coalesce(r.sessions, 0)
    or e.purchasing_sessions <> coalesce(r.purchasing_sessions, 0)
