select observed_date, event_us, event_name, session_key, transaction_id,
       {{ clean_label('item.item_id') }} as item_id,
       {{ clean_label('item.item_name') }} as item_name,
       {{ clean_label('item.item_category') }} as category
from {{ ref('stg_ga4_events') }}
{% if target.type == 'bigquery' %}
cross join unnest(items) as item
{% else %}
cross join unnest(items) as i(item)
{% endif %}
where event_name in ('view_item', 'add_to_cart', 'purchase')
