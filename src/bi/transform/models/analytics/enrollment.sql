-- Enrollment at student grain: one row per student and term. Read by Cube only (CLAUDE.md rule 5).
select
    student_id,
    term_code,
    term_label,
    term_start,
    term_end,
    program,
    level,
    status,
    as_of,
    source_file_sha256,
    loaded_at
from {{ ref('stg_enrollment') }}
