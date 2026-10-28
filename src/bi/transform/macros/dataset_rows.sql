{# The rows of a dataset from every raw table and layout with an approved mapping (variable `<dataset>_inputs`, set by bi.mapping):
   each part as trimmed text, under its own name, with the BI's metadata. A part a layout does not supply is null. With no inputs, no
   rows (the analytics exist, empty). #}
{% macro dataset_rows(dataset, parts) %}
    {%- set inputs = var(dataset ~ '_inputs', []) -%}
    {%- for input in inputs %}
    select
        {%- for part in parts %}
        {%- set column = input['columns'].get(part) %}
        {% if column %}nullif(trim({{ adapter.quote(column) }}::text), ''){% else %}null::text{% endif %} as {{ part }},
        {%- endfor %}
        _bi_as_of,
        _bi_file_sha256,
        _bi_loaded_at
    from {{ adapter.quote('raw') }}.{{ adapter.quote(input['table']) }}
    where _bi_layout = '{{ input['layout'] }}'
        and _bi_sync_id in ({% for id in input['syncs'] %}'{{ id }}'{% if not loop.last %}, {% endif %}{% endfor %})
    {% if not loop.last %}union all{% endif %}
    {%- else %}
    select
        {%- for part in parts %}
        null::text as {{ part }},
        {%- endfor %}
        null::date as _bi_as_of,
        null::text as _bi_file_sha256,
        null::timestamptz as _bi_loaded_at
    where false
    {%- endfor %}
{% endmacro %}
