-- Run in the same Google Cloud project as dbt. Match the date bounds to the build.
-- These are independent event-based counts for checking the staging and coverage models.
select
    _table_suffix as source_day,
    event_name,
    count(*) as raw_events,
    countif(
        user_pseudo_id is null
        or lower(trim(user_pseudo_id)) in ('', '<other>', '(not set)', '<not set>', 'null')
        or coalesce((
            select max(p.value.int_value)
            from unnest(event_params) p
            where p.key = 'ga_session_id'
        ), 0) <= 0
    ) as unassigned_events,
    countif(exists (
        select 1
        from unnest(items) i
        where lower(trim(i.item_id)) not in ('', '<other>', '(not set)', '<not set>', 'null')
    )) as events_with_usable_items
from `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
where _table_suffix between '20210104' and '20210110'
group by source_day, event_name
order by source_day, raw_events desc;
