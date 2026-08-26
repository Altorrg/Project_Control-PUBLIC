-- 012 - Utemtervi fazisok es szerzodeses merfoldkovek bovitesei.
-- Meglevo adatbazisnal ezt a fajlt kulon futtasd a Supabase SQL Editorban.

begin;

alter table public.schedule_rows
    add column if not exists section text,
    add column if not exists phase_code text;

with ordered_rows as (
    select
        id,
        row_number() over (
            partition by project_id
            order by position, id
        ) * 10 as normalized_position
    from public.schedule_rows
)
update public.schedule_rows target
set position = ordered_rows.normalized_position
from ordered_rows
where target.id = ordered_rows.id
  and target.position is distinct from ordered_rows.normalized_position;

do $$
declare
    constraint_name text;
begin
    for constraint_name in
        select conname
        from pg_constraint
        where conrelid = 'public.phase_templates'::regclass
          and contype = 'c'
          and pg_get_constraintdef(oid) ilike '%default_calc_type%'
    loop
        execute format(
            'alter table public.phase_templates drop constraint %I',
            constraint_name
        );
    end loop;

    for constraint_name in
        select conname
        from pg_constraint
        where conrelid = 'public.schedule_rows'::regclass
          and contype = 'c'
          and (
              pg_get_constraintdef(oid) ilike '%calc_type%'
              or pg_get_constraintdef(oid) ilike '%position%'
          )
    loop
        execute format(
            'alter table public.schedule_rows drop constraint %I',
            constraint_name
        );
    end loop;
end;
$$;

alter table public.phase_templates
    add constraint phase_templates_default_calc_type_check
    check (default_calc_type in ('Naptári nap', 'Munkanap', 'Hónap'));

alter table public.schedule_rows
    add constraint schedule_rows_calc_type_check
    check (calc_type in ('Naptári nap', 'Munkanap', 'Hónap')),
    add constraint schedule_rows_position_positive
    check (position > 0),
    add constraint schedule_rows_section_length
    check (section is null or char_length(section) <= 255),
    add constraint schedule_rows_phase_code_length
    check (phase_code is null or char_length(phase_code) <= 255);

create index if not exists schedule_rows_project_position_id_idx
    on public.schedule_rows(project_id, position, id);

alter table public.project_milestones
    add column if not exists short_name text,
    add column if not exists official_name text,
    add column if not exists schedule_row_id bigint;

update public.project_milestones
set
    official_name = coalesce(nullif(trim(official_name), ''), name),
    short_name = coalesce(
        nullif(trim(short_name), ''),
        nullif(trim(name), ''),
        nullif(trim(official_name), '')
    ),
    name = coalesce(nullif(trim(official_name), ''), name);

alter table public.project_milestones
    alter column short_name set default '',
    alter column short_name set not null,
    alter column official_name set default '',
    alter column official_name set not null;

with unique_schedule_names as (
    select
        project_id,
        phase_name,
        min(id) as schedule_row_id
    from public.schedule_rows
    group by project_id, phase_name
    having count(*) = 1
)
update public.project_milestones milestone
set schedule_row_id = source.schedule_row_id
from unique_schedule_names source
where milestone.schedule_row_id is null
  and milestone.date_type = 'Ütemterv sorhoz kötve'
  and milestone.project_id = source.project_id
  and trim(milestone.reference_name) = trim(source.phase_name);

do $$
declare
    constraint_name text;
begin
    for constraint_name in
        select conname
        from pg_constraint
        where conrelid = 'public.project_contract_sections'::regclass
          and contype = 'c'
          and pg_get_constraintdef(oid) ilike '%section_no%'
    loop
        execute format(
            'alter table public.project_contract_sections drop constraint %I',
            constraint_name
        );
    end loop;

    for constraint_name in
        select conname
        from pg_constraint
        where conrelid = 'public.project_milestones'::regclass
          and contype = 'c'
          and pg_get_constraintdef(oid) ilike '%phase_no%'
    loop
        execute format(
            'alter table public.project_milestones drop constraint %I',
            constraint_name
        );
    end loop;
end;
$$;

alter table public.project_contract_sections
    add constraint project_contract_sections_section_no_check
    check (section_no between 0 and 5);

alter table public.project_milestones
    add constraint project_milestones_phase_no_check
    check (phase_no between 0 and 5);

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'public.project_milestones'::regclass
          and conname = 'project_milestones_schedule_row_id_fkey'
    ) then
        alter table public.project_milestones
            add constraint project_milestones_schedule_row_id_fkey
            foreign key (schedule_row_id)
            references public.schedule_rows(id)
            on delete set null;
    end if;
end;
$$;

create index if not exists project_milestones_project_schedule_row_idx
    on public.project_milestones(project_id, schedule_row_id);

commit;
