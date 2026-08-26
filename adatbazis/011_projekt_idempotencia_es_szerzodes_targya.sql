-- 011 - Projekt letrehozasi idempotencia es a szerzodes targya.
-- Meglevo adatbazisnal ezt a fajlt kulon futtasd a Supabase SQL Editorban.

begin;

create extension if not exists pgcrypto;

alter table public.projects
    add column if not exists contract_subject text not null default '',
    add column if not exists creation_idempotency_key text,
    add column if not exists creation_request_fingerprint text;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'public.projects'::regclass
          and conname = 'projects_creation_idempotency_key_length'
    ) then
        alter table public.projects
            add constraint projects_creation_idempotency_key_length
            check (
                creation_idempotency_key is null
                or char_length(creation_idempotency_key) between 1 and 255
            );
    end if;

    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'public.projects'::regclass
          and conname = 'projects_creation_request_fingerprint_format'
    ) then
        alter table public.projects
            add constraint projects_creation_request_fingerprint_format
            check (
                creation_request_fingerprint is null
                or creation_request_fingerprint ~ '^[0-9a-f]{64}$'
            );
    end if;
end;
$$;

create unique index if not exists projects_creator_idempotency_key_uidx
    on public.projects(created_by, creation_idempotency_key)
    where creation_idempotency_key is not null;

create or replace function public.create_project(payload jsonb)
returns public.projects
language plpgsql
security definer
set search_path = ''
as $$
declare
    result public.projects;
    current_profile_id uuid;
    request_key text;
    request_fingerprint text;
    project_name text;
    project_work_number text;
    project_responsible_company text;
    project_contract_value numeric(18,2);
    project_contract_subject text;
    project_customer text;
    project_main_customer text;
    project_status text;
    canonical_payload jsonb;
begin
    if not public.has_permission('project_create') then
        raise exception 'permission denied';
    end if;

    current_profile_id := auth.uid();
    request_key := nullif(trim(payload ->> 'idempotency_key'), '');
    project_name := nullif(trim(payload ->> 'name'), '');
    project_work_number := coalesce(payload ->> 'work_number', '');
    project_responsible_company := coalesce(payload ->> 'responsible_company', '');
    project_contract_value := nullif(payload ->> 'contract_value', '')::numeric;
    project_contract_subject := coalesce(payload ->> 'contract_subject', '');
    project_customer := coalesce(payload ->> 'customer', '');
    project_main_customer := coalesce(payload ->> 'main_customer', '');
    project_status := coalesce(nullif(payload ->> 'status', ''), 'Aktív');

    canonical_payload := jsonb_build_object(
        'name', project_name,
        'work_number', project_work_number,
        'responsible_company', project_responsible_company,
        'contract_value', project_contract_value,
        'contract_subject', project_contract_subject,
        'customer', project_customer,
        'main_customer', project_main_customer,
        'status', project_status
    );
    request_fingerprint := encode(
        digest(convert_to(canonical_payload::text, 'UTF8'), 'sha256'),
        'hex'
    );

    if request_key is not null then
        select p.*
        into result
        from public.projects p
        where p.created_by = current_profile_id
          and p.creation_idempotency_key = request_key;

        if result.id is not null then
            if result.creation_request_fingerprint = request_fingerprint then
                return result;
            end if;
            raise exception using
                errcode = '23505',
                message = 'Az idempotenciakulcs mar egy masik projektkereshez tartozik.';
        end if;
    end if;

    insert into public.projects(
        name,
        work_number,
        responsible_company,
        contract_value,
        contract_subject,
        customer,
        main_customer,
        status,
        created_by,
        creation_idempotency_key,
        creation_request_fingerprint
    )
    values (
        project_name,
        project_work_number,
        project_responsible_company,
        project_contract_value,
        project_contract_subject,
        project_customer,
        project_main_customer,
        project_status,
        current_profile_id,
        request_key,
        case when request_key is null then null else request_fingerprint end
    )
    on conflict (created_by, creation_idempotency_key)
        where creation_idempotency_key is not null
        do nothing
    returning * into result;

    if result.id is null then
        select p.*
        into result
        from public.projects p
        where p.created_by = current_profile_id
          and p.creation_idempotency_key = request_key;

        if result.id is null then
            raise exception 'A projekt letrehozasa nem sikerult.';
        end if;
        if result.creation_request_fingerprint <> request_fingerprint then
            raise exception using
                errcode = '23505',
                message = 'Az idempotenciakulcs mar egy masik projektkereshez tartozik.';
        end if;
        return result;
    end if;

    insert into public.project_memberships(profile_id, project_id, can_write)
    values (current_profile_id, result.id, true)
    on conflict do nothing;

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
    if not public.can_access_project(target_project_id, true)
       or not public.has_permission('project_write') then
        raise exception 'permission denied';
    end if;

    update public.projects p
    set
        name = case
            when payload ? 'name' then nullif(trim(payload ->> 'name'), '')
            else p.name
        end,
        work_number = case
            when payload ? 'work_number' then coalesce(payload ->> 'work_number', '')
            else p.work_number
        end,
        responsible_company = case
            when payload ? 'responsible_company' then coalesce(payload ->> 'responsible_company', '')
            else p.responsible_company
        end,
        contract_value = case
            when payload ? 'contract_value' then nullif(payload ->> 'contract_value', '')::numeric
            else p.contract_value
        end,
        contract_subject = case
            when payload ? 'contract_subject' then coalesce(payload ->> 'contract_subject', '')
            else p.contract_subject
        end,
        customer = case
            when payload ? 'customer' then coalesce(payload ->> 'customer', '')
            else p.customer
        end,
        main_customer = case
            when payload ? 'main_customer' then coalesce(payload ->> 'main_customer', '')
            else p.main_customer
        end,
        status = case
            when payload ? 'status' then coalesce(payload ->> 'status', '')
            else p.status
        end
    where p.id = target_project_id
      and not p.is_deleted
    returning * into result;

    if result.id is null then
        raise exception 'project not found';
    end if;
    return result;
end;
$$;

commit;
