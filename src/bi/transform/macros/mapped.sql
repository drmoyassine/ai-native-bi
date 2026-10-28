{# The raw column that supplies a part of a dataset: the approved mapping (variable `<dataset>_columns`, set by bi.mapping), or the column
   of the part's own name when there is none. A part with no column is null. #}
{% macro mapped(dataset, part, relation='raw') %}
    {%- set chosen = var(dataset ~ '_columns', {}).get(part, part) -%}
    {%- if chosen -%}{{ relation }}.{{ adapter.quote(chosen) }}{%- else -%}null{%- endif -%}
{% endmacro %}
