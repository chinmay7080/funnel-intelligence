with item_events as (
    select * from {{ ref('int_event_items') }}
    where session_key is not null and item_id is not null
),
views as (
    select session_key, item_id, min(event_us) as view_us
    from item_events
    where event_name = 'view_item'
    group by session_key, item_id
),
labels as (
    select item_id, item_name, category
    from item_events
    qualify row_number() over (
        partition by item_id
        order by case when item_name is null then 1 else 0 end,
                 case when category is null then 1 else 0 end,
                 event_us desc, item_name, category
    ) = 1
),
outcomes as (
    select v.session_key, v.item_id,
        countif(e.event_name = 'add_to_cart') > 0 as added_after_view,
        countif(e.event_name = 'purchase') > 0 as purchased_after_view
    from views v
    left join item_events e
        on e.session_key = v.session_key and e.item_id = v.item_id and e.event_us > v.view_us
    group by v.session_key, v.item_id
)
select o.*, s.session_date, s.device, s.channel, s.visitor,
       coalesce(l.item_name, o.item_id) as item_name, coalesce(l.category, 'Unknown') as category
from outcomes o
join {{ ref('fct_sessions') }} s using (session_key)
join labels l using (item_id)
