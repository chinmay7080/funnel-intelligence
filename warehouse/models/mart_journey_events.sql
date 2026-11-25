select e.observed_date, e.session_key, e.event_us, e.event_name
from {{ ref('stg_ga4_events') }} e
join {{ ref('mart_session_anomalies') }} a using (session_key)
