-- 008 - Matrix datumjavitas es regi oszlopok normalizalasa.
-- Meglevo adatbazisnal ezt a fajlt kulon futtasd a Supabase SQL Editorban.

begin;

-- A regi EMP_YYYY.MM jellegu oszlopoknak nem volt kulon szulo rekordjuk.
-- Ezekbol datumozott contract_stages rekord keszul, majd a cellak arra allnak at.
with legacy_columns as (
    select distinct cm.project_id, trim(cm.column_code) as column_code
    from public.contract_matrix cm
    where trim(coalesce(cm.column_code, '')) <> ''
      and upper(trim(cm.column_code)) <> 'BASE'
      and upper(trim(cm.column_code)) !~ '^(M|STAGE)_[0-9]+$'
), parsed as (
    select
        legacy.project_id,
        legacy.column_code,
        regexp_match(
            legacy.column_code,
            '(?i)EMP[_ -]?([0-9]{4})[._ -]([0-9]{1,2})'
        ) as date_parts
    from legacy_columns legacy
), prepared as (
    select
        parsed.project_id,
        parsed.column_code,
        coalesce(
            case
                when parsed.date_parts is not null
                 and (parsed.date_parts)[1]::integer between 1 and 9999
                 and (parsed.date_parts)[2]::integer between 1 and 12
                then make_date(
                    (parsed.date_parts)[1]::integer,
                    (parsed.date_parts)[2]::integer,
                    1
                )
            end,
            (
                select min(coalesce(pm.actual_date, pm.planned_date))
                from public.project_milestones pm
                where pm.project_id = parsed.project_id
            ),
            (
                select min(pcs.section_date)
                from public.project_contract_sections pcs
                where pcs.project_id = parsed.project_id
            ),
            (
                select min(se.entry_date)
                from public.schedule_entries se
                where se.project_id = parsed.project_id
            ),
            (
                select p.created_at::date
                from public.projects p
                where p.id = parsed.project_id
            ),
            current_date
        ) as stage_date
    from parsed
)
insert into public.contract_stages(project_id, name, stage_date, sort_order)
select
    prepared.project_id,
    prepared.column_code,
    prepared.stage_date,
    10000 + row_number() over (
        partition by prepared.project_id
        order by prepared.stage_date, prepared.column_code
    ) * 10
from prepared
on conflict (project_id, name) do update
set stage_date = coalesce(contract_stages.stage_date, excluded.stage_date);

with parsed as (
    select
        stages.id,
        regexp_match(
            stages.name,
            '(?i)EMP[_ -]?([0-9]{4})[._ -]([0-9]{1,2})'
        ) as date_parts
    from public.contract_stages stages
    where stages.stage_date is null
)
update public.contract_stages stages
set stage_date = coalesce(
        case
            when parsed.date_parts is not null
             and (parsed.date_parts)[1]::integer between 1 and 9999
             and (parsed.date_parts)[2]::integer between 1 and 12
            then make_date(
                (parsed.date_parts)[1]::integer,
                (parsed.date_parts)[2]::integer,
                1
            )
        end,
        (
            select min(coalesce(pm.actual_date, pm.planned_date))
            from public.project_milestones pm
            where pm.project_id = stages.project_id
        ),
        (
            select min(pcs.section_date)
            from public.project_contract_sections pcs
            where pcs.project_id = stages.project_id
        ),
        (
            select min(se.entry_date)
            from public.schedule_entries se
            where se.project_id = stages.project_id
        ),
        (
            select p.created_at::date
            from public.projects p
            where p.id = stages.project_id
        ),
        current_date
    )
from parsed
where stages.id = parsed.id
  and stages.stage_date is null;

update public.contract_matrix cells
set
    stage_id = stages.id,
    column_code = 'STAGE_' || stages.id::text
from public.contract_stages stages
where cells.project_id = stages.project_id
  and stages.name = cells.column_code
  and trim(coalesce(cells.column_code, '')) <> ''
  and upper(trim(cells.column_code)) <> 'BASE'
  and upper(trim(cells.column_code)) !~ '^(M|STAGE)_[0-9]+$';

alter table public.contract_stages
    alter column stage_date set not null;

create index if not exists contract_stages_project_date_idx
    on public.contract_stages(project_id, stage_date, sort_order, id);

commit;
