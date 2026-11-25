select session_key, item_id from {{ ref('fct_session_items') }}
group by session_key, item_id having count(*) > 1
