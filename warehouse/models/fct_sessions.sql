with events as (
    select * from {{ ref('stg_ga4_events') }} where session_key is not null
),
session_entry as (
    select
        session_key,
        coalesce(device, 'unknown') as device,
        case
            when acquisition_medium in ('(none)', 'none') and acquisition_source in ('(direct)', 'direct') then 'Direct'
            when acquisition_medium in ('cpc', 'ppc', 'paidsearch', 'paid_search') then 'Paid Search'
            when acquisition_medium in ('email', 'e-mail') then 'Email'
            when acquisition_medium in ('social', 'social-network', 'social-media', 'paid_social') then 'Social'
            when acquisition_medium = 'organic' then 'Organic Search'
            when acquisition_medium = 'referral' then 'Referral'
            when acquisition_medium is null or acquisition_source is null then 'Unknown'
            else 'Other'
        end as channel
    from events
    qualify row_number() over (
        partition by session_key
        order by case when event_name = 'session_start' then 0 else 1 end,
                 event_us, device, acquisition_source, acquisition_medium
    ) = 1
),
session_rollup as (
    select
        session_key,
        min(user_key) as user_key,
        coalesce(min(case when event_name = 'session_start' then observed_date end), min(observed_date)) as session_date,
        max(event_us) - min(event_us) as duration_us,
        count(*) as events,
        count(distinct event_us) as distinct_times,
        countif(event_name = 'purchase') as purchase_events,
        countif(event_name = 'begin_checkout') as checkout_events,
        countif(event_name = 'session_start') as start_events,
        countif(event_name = 'first_visit') as first_visits,
        min(case when session_number > 0 then session_number end) as min_session_number,
        max(case when session_number > 0 then session_number end) as max_session_number,
        min(case when event_name = 'view_item' then event_us end) as view_us
    from events
    group by session_key
),
cart as (
    select e.session_key, min(e.event_us) as cart_us
    from events e join session_rollup s using (session_key)
    where e.event_name = 'add_to_cart' and e.event_us > s.view_us
    group by e.session_key
),
checkout as (
    select e.session_key, min(e.event_us) as checkout_us
    from events e join cart c using (session_key)
    where e.event_name = 'begin_checkout' and e.event_us > c.cart_us
    group by e.session_key
),
purchase as (
    select e.session_key, min(e.event_us) as ordered_purchase_us
    from events e join checkout c using (session_key)
    where e.event_name = 'purchase' and e.event_us > c.checkout_us
    group by e.session_key
)
select
    s.session_key, s.user_key, s.session_date, a.device, a.channel,
    case
        when min_session_number <> max_session_number or (first_visits > 0 and min_session_number > 1)
            then 'Unknown'
        when first_visits > 0 or min_session_number = 1 then 'New'
        when min_session_number > 1 then 'Returning'
        else 'Unknown'
    end as visitor,
    duration_us, events, purchase_events, checkout_events, start_events,
    events > distinct_times as has_timestamp_ties,
    view_us is not null as viewed,
    cart_us is not null as added,
    checkout_us is not null as checked_out,
    ordered_purchase_us is not null as ordered_purchase,
    purchase_events > 0 as purchased
from session_rollup s
join session_entry a using (session_key)
left join cart using (session_key)
left join checkout using (session_key)
left join purchase using (session_key)
