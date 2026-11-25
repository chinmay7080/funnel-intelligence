with activity as (
    select distinct user_key, {{ week_start('session_date') }} as activity_week
    from {{ ref('fct_sessions') }}
),
labeled as (
    select *, min(activity_week) over (partition by user_key) as cohort_week
    from activity
),
counts as (
    select cohort_week, activity_week, count(*) as active_users
    from labeled
    group by cohort_week, activity_week
)
select cohort_week, activity_week, cast({{ days_between('cohort_week', 'activity_week') }} / 7 as integer) as week_number,
       active_users, max(case when cohort_week = activity_week then active_users end)
           over (partition by cohort_week) as cohort_size
from counts
