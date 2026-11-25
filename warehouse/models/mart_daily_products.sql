select session_date, device, channel, visitor, item_id, item_name, category,
       count(*) as views, countif(added_after_view) as adds,
       countif(purchased_after_view) as purchases
from {{ ref('fct_session_items') }}
group by session_date, device, channel, visitor, item_id, item_name, category
