-- Independent counts from the public source for the bounded validation build.
with event_fields as (
    select
        _table_suffix as source_day,
        event_name,
        trim(user_pseudo_id) as user_key,
        (select max(p.value.int_value) from unnest(event_params) p
         where p.key = 'ga_session_id') as session_id,
        trim(ecommerce.transaction_id) as transaction_id
    from `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
    where _table_suffix between '20210104' and '20210110'
),
classified as (
    select *,
        coalesce(
            lower(user_key) not in ('', '<other>', '(not set)', '<not set>', 'null') and session_id > 0,
            false
        ) as eligible_session,
        coalesce(lower(transaction_id) not in ('', '<other>', '(not set)', '<not set>', 'null'), false)
            as usable_order
    from event_fields
),
session_counts as (
    select user_key, session_id, countif(event_name = 'purchase') > 0 as purchased
    from classified
    where eligible_session
    group by user_key, session_id
),
sessions as (
    select count(*) as sessions, countif(purchased) as purchasing_sessions
    from session_counts
),
events as (
    select count(distinct source_day) as dates,
        count(*) as events,
        countif(not eligible_session) as unassigned_events,
        countif(event_name = 'purchase') as purchase_events,
        countif(event_name = 'purchase' and not eligible_session) as unassigned_purchases,
        count(distinct if(event_name = 'purchase' and usable_order, transaction_id, null)) as orders
    from classified
)
select * from events cross join sessions
