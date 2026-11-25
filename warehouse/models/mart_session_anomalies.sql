with sessions as (
    select *
    from {{ ref('fct_sessions') }}
),
baseline as (
    select device, count(*) as baseline_sessions,
           {% if target.type == 'bigquery' %}
           approx_quantiles(events, 100)[offset(99)] as p99_events,
           approx_quantiles(duration_us, 100)[offset(99)] as p99_duration_us
           {% else %}
           quantile_disc(events, 0.99) as p99_events,
           quantile_disc(duration_us, 0.99) as p99_duration_us
           {% endif %}
    from sessions
    group by device
),
flagged as (
    select s.session_key, s.session_date, s.device, s.channel, s.visitor, s.events, s.purchase_events,
           round(s.duration_us / 1000000.0, 1) as observed_seconds,
           b.p99_events, round(b.p99_duration_us / 1000000.0, 1) as p99_seconds,
           b.baseline_sessions,
           s.purchase_events > 1 as repeated_purchase,
           s.purchased and s.checkout_events = 0 as purchase_without_checkout,
           b.baseline_sessions >= 100 and s.events > b.p99_events as unusual_events,
           b.baseline_sessions >= 100 and s.duration_us > b.p99_duration_us as unusual_duration
    from sessions s join baseline b using (device)
)
select * from flagged where repeated_purchase or purchase_without_checkout or unusual_events or unusual_duration
