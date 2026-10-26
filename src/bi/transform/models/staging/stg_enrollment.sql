-- The current enrollment snapshot: for each term, the rows of the latest load that contains the term (a new upload of a term
-- replaces the earlier one), typed.
with raw as (
    select * from {{ source('raw', 'enrollment') }}
),

latest as (
    select term_code, max(_bi_loaded_at) as loaded_at
    from raw
    group by term_code
)

select
    trim(raw.student_id) as student_id,
    trim(raw.term_code) as term_code,
    trim(raw.term) as term_label,
    cast(raw.term_start as date) as term_start,
    cast(raw.term_end as date) as term_end,
    trim(raw.program) as program,
    lower(trim(raw.level)) as level,
    lower(trim(raw.status)) as status,
    cast(raw._bi_as_of as date) as as_of,
    raw._bi_file_sha256 as source_file_sha256,
    raw._bi_loaded_at as loaded_at
from raw
inner join latest
    on raw.term_code = latest.term_code
    and raw._bi_loaded_at = latest.loaded_at
