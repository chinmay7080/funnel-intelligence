{% set raw_events = source('ga4', 'events') %}
{% set start = modules.datetime.date.fromisoformat(var('source_start')) %}
{% set end = modules.datetime.date.fromisoformat(var('source_end')) %}
{% if start > end or start.isoformat() < '2020-11-01' or end.isoformat() > '2021-01-31' %}
    {{ exceptions.raise_compiler_error('Source range must fit inside the published GA4 sample.') }}
{% endif %}

with extracted as (
    select
        {% if target.type == 'bigquery' %}
        parse_date('%Y%m%d', event_date) as observed_date,
        {% else %}
        cast(strptime(event_date, '%Y%m%d') as date) as observed_date,
        {% endif %}
        event_timestamp as event_us,
        event_name,
        {{ clean_label('user_pseudo_id') }} as user_key,
        {{ session_parameter('ga_session_id') }} as session_id,
        {{ session_parameter('ga_session_number') }} as session_number,
        lower({{ clean_label('device.category') }}) as device,
        lower({{ clean_label('traffic_source.source') }}) as acquisition_source,
        lower({{ clean_label('traffic_source.medium') }}) as acquisition_medium,
        {{ clean_label('ecommerce.transaction_id') }} as transaction_id,
        ecommerce.purchase_revenue_in_usd as revenue_usd,
        items
    {% if target.type == 'bigquery' %}
    from `{{ raw_events.database }}.{{ raw_events.schema }}.{{ raw_events.identifier }}`
    where _table_suffix between '{{ start.strftime("%Y%m%d") }}' and '{{ end.strftime("%Y%m%d") }}'
    {% else %}
    from {{ raw_events }}
    where event_date between '{{ start.strftime("%Y%m%d") }}' and '{{ end.strftime("%Y%m%d") }}'
    {% endif %}
)
select *,
    case when user_key is not null and session_id > 0
        then concat(user_key, ':', cast(session_id as {{ dbt.type_string() }})) end as session_key
from extracted
