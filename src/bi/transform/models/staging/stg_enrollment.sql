-- The current snapshot of each term, typed, from every source and layout that feeds enrollment (bi.mapping, DEC-029).
with raw as (
    {{ dataset_rows('enrollment', ['student_id', 'term_code', 'term', 'term_start', 'term_end', 'program', 'level', 'status']) }}
),

latest as (
    select term_code, max(_bi_loaded_at) as loaded_at
    from raw
    group by term_code
)

select
    raw.student_id,
    raw.term_code,
    raw.term as term_label,
    cast(raw.term_start as date) as term_start,
    cast(raw.term_end as date) as term_end,
    raw.program,
    lower(raw.level) as level,
    lower(raw.status) as status,
    cast(raw._bi_as_of as date) as as_of,
    raw._bi_file_sha256 as source_file_sha256,
    raw._bi_loaded_at as loaded_at
from raw
inner join latest
    on raw.term_code = latest.term_code and raw._bi_loaded_at = latest.loaded_at
