{% macro clean_label(value) -%}
    case when lower(trim({{ value }})) in ('', '<other>', '(not set)', '<not set>', 'null')
        then null else trim({{ value }}) end
{%- endmacro %}

{% macro session_parameter(name) -%}
    {% if target.type == 'bigquery' %}
    (select max(param.value.int_value) from unnest(event_params) as param
        where param.key = '{{ name }}')
    {% else %}
    (select max(param.value.int_value) from unnest(event_params) as p(param)
        where param.key = '{{ name }}')
    {% endif %}
{%- endmacro %}

{% macro week_start(column) -%}
    {% if target.type == 'bigquery' %}
    date_trunc({{ column }}, week(monday))
    {% else %}
    cast(date_trunc('week', {{ column }}) as date)
    {% endif %}
{%- endmacro %}

{% macro days_between(start, end) -%}
    {% if target.type == 'bigquery' %}
    date_diff({{ end }}, {{ start }}, day)
    {% else %}
    date_diff('day', {{ start }}, {{ end }})
    {% endif %}
{%- endmacro %}
