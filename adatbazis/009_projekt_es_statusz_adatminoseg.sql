-- 009 - Projekt lobby mezok es ajanlatkeresi statusz adatminoseg.
-- Meglevo adatbazisnal ezt a fajlt kulon futtasd a Supabase SQL Editorban.

begin;

alter table public.projects
    add column if not exists work_number text not null default '',
    add column if not exists responsible_company text not null default '';

update public.projects
set responsible_company = coalesce(
    nullif(trim(responsible_company), ''),
    nullif(trim(customer), ''),
    nullif(trim(main_customer), ''),
    ''
)
where trim(coalesce(responsible_company, '')) = '';

update public.subcontractor_workflows
set offer_status = 'Elutasítva'
where lower(trim(offer_status)) in ('késik', 'kesik');

update public.subcontractor_workflows
set offer_status = 'Kiküldésre vár'
where trim(coalesce(offer_status, '')) = '';

alter table public.subcontractor_workflows
    alter column offer_status set default 'Kiküldésre vár';

alter table public.subcontractor_workflows
    drop constraint if exists subcontractor_workflows_offer_status_check;

alter table public.subcontractor_workflows
    add constraint subcontractor_workflows_offer_status_check
    check (offer_status in ('Kiküldésre vár', 'Kiküldve', 'Elutasítva'));

create or replace function public.create_project(payload jsonb)
returns public.projects
language plpgsql
security definer
set search_path = ''
as $$
declare result public.projects;
begin
    if not public.has_permission('project_create') then raise exception 'permission denied'; end if;
    insert into public.projects(
        name, work_number, responsible_company, contract_value,
        customer, main_customer, status, created_by
    )
    values (
        nullif(trim(payload ->> 'name'), ''),
        coalesce(payload ->> 'work_number', ''),
        coalesce(payload ->> 'responsible_company', ''),
        nullif(payload ->> 'contract_value', '')::numeric,
        coalesce(payload ->> 'customer', ''),
        coalesce(payload ->> 'main_customer', ''),
        coalesce(nullif(payload ->> 'status', ''), 'Aktív'),
        auth.uid()
    ) returning * into result;
    insert into public.project_memberships(profile_id, project_id, can_write)
    values (auth.uid(), result.id, true) on conflict do nothing;
    return result;
end;
$$;

create or replace function public.update_project(target_project_id bigint, payload jsonb)
returns public.projects
language plpgsql
security definer
set search_path = ''
as $$
declare result public.projects;
begin
    if not public.can_access_project(target_project_id, true) or not public.has_permission('project_write') then
        raise exception 'permission denied';
    end if;
    update public.projects p set
        name = case when payload ? 'name' then nullif(trim(payload ->> 'name'), '') else p.name end,
        work_number = case when payload ? 'work_number' then coalesce(payload ->> 'work_number', '') else p.work_number end,
        responsible_company = case when payload ? 'responsible_company' then coalesce(payload ->> 'responsible_company', '') else p.responsible_company end,
        contract_value = case when payload ? 'contract_value' then nullif(payload ->> 'contract_value', '')::numeric else p.contract_value end,
        customer = case when payload ? 'customer' then coalesce(payload ->> 'customer', '') else p.customer end,
        main_customer = case when payload ? 'main_customer' then coalesce(payload ->> 'main_customer', '') else p.main_customer end,
        status = case when payload ? 'status' then coalesce(payload ->> 'status', '') else p.status end
    where p.id = target_project_id and not p.is_deleted
    returning * into result;
    if result.id is null then raise exception 'project not found'; end if;
    return result;
end;
$$;

commit;
