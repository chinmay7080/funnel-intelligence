select session_date, device, channel, visitor,
       count(*) as sessions, countif(viewed) as views, countif(added) as adds,
       countif(checked_out) as checkouts, countif(ordered_purchase) as ordered_purchases,
       countif(purchased) as purchasing_sessions
from {{ ref('fct_sessions') }}
group by session_date, device, channel, visitor
