-- The current snapshot of each term, typed. Which raw column supplies each part is the dataset's approved mapping (bi.mapping).
with raw as (select * from {{ source('raw', 'enrollment') }}),

latest as (
    select trim({{ mapped('enrollment', 'term_code') }}::text) as term_code, max(_bi_loaded_at) as loaded_at
    from raw
    group by 1
)

select
    trim({{ mapped('enrollment', 'student_id') }}::text) as student_id,
    trim({{ mapped('enrollment', 'term_code') }}::text) as term_code,
    trim({{ mapped('enrollment', 'term') }}::text) as term_label,
    cast({{ mapped('enrollment', 'term_start') }} as date) as term_start,
    cast({{ mapped('enrollment', 'term_end') }} as date) as term_end,
    trim({{ mapped('enrollment', 'program') }}::text) as program,
    lower(trim({{ mapped('enrollment', 'level') }}::text)) as level,
    lower(trim({{ mapped('enrollment', 'status') }}::text)) as status,
    cast(raw._bi_as_of as date) as as_of,
    raw._bi_file_sha256 as source_file_sha256,
    raw._bi_loaded_at as loaded_at
from raw
inner join latest
    on trim({{ mapped('enrollment', 'term_code') }}::text) = latest.term_code and raw._bi_loaded_at = latest.loaded_at
