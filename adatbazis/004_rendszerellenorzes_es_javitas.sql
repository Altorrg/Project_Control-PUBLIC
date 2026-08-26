-- Project Control - idempotens rendszerellenorzes es profiljavitas
-- Nem tartalmaz projekt- vagy korabbi alkalmazasadatokat.

begin;

drop function if exists public.link_legacy_user(bigint, uuid);
drop table if exists public.legacy_source_rows cascade;
drop table if exists public.legacy_notification_dismissals cascade;
drop table if exists public.legacy_module_visibility cascade;
drop table if exists public.legacy_project_memberships cascade;
drop table if exists public.legacy_user_import cascade;
drop table if exists public.migration_issues cascade;
alter table public.profiles drop column if exists legacy_user_id;

alter table public.profiles alter column role set default 'editor';

create or replace function public.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.profiles(id, display_name, role)
    values (
        new.id,
        coalesce(nullif(new.raw_user_meta_data ->> 'display_name', ''), new.email, 'Felhasznalo'),
        'editor'
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

insert into public.permissions(permission_key, description) values
    ('projects_all', 'Osszes projekt megtekintese'),
    ('project_create', 'Projekt letrehozasa'),
    ('project_write', 'Projektadatok modositasa'),
    ('project_delete', 'Projekt archivalasa'),
    ('admin_panel', 'Admin kozpont hasznalata'),
    ('arbevetel', 'Ceges arbevetel es cash-flow'),
    ('module_szakagak', 'Szakag napi adatok modul'),
    ('module_utemterv', 'Gantt utemterv modul'),
    ('module_alvallalkozo', 'Alvallalkozo es szerzodes modul'),
    ('module_penzugy', 'Penzugyi modul'),
    ('module_beallitasok', 'Projektbeallitasok modul'),
    ('module_engedelyek', 'Engedelyezesi modul'),
    ('discipline_write', 'Szakagi adatok szerkesztese'),
    ('schedule_write', 'Utemterv szerkesztese'),
    ('subcontractor_write', 'Alvallalkozoi adatok szerkesztese'),
    ('finance_write', 'Penzugyi adatok szerkesztese'),
    ('eng_write', 'Engedelyezesi adatok szerkesztese'),
    ('eng_admin', 'Engedelyezesi admin jovahagyas'),
    ('master_data_admin', 'Globalis torzsadatok kezelese')
on conflict (permission_key) do update set description = excluded.description;

insert into public.role_permissions(role, permission_key, allowed)
select 'editor', permission_key, true
from unnest(array[
    'module_szakagak', 'module_utemterv', 'module_alvallalkozo',
    'module_penzugy', 'module_beallitasok', 'module_engedelyek',
    'projects_all', 'project_create', 'project_write', 'arbevetel',
    'discipline_write', 'schedule_write',
    'subcontractor_write', 'finance_write', 'eng_write'
]) permission_list(permission_key)
on conflict (role, permission_key) do update set allowed = true;

delete from public.role_permissions where role <> 'editor';

alter table public.profiles drop constraint if exists profiles_id_fkey;

-- A trigger letrehozasa elott mar letezo Auth-felhasznalok profiljat is potolja.
-- A helyi teszteleshez hasznalt kezdeti admin fiokot helyreallitja.
insert into public.profiles(id, display_name, role, active)
select
    user_row.id,
    coalesce(nullif(user_row.raw_user_meta_data ->> 'display_name', ''), user_row.email, 'Felhasznalo'),
    case
        when lower(coalesce(user_row.email, '')) in ('admin@demo.local', 'admin@example.com') then 'admin'
        else 'editor'
    end,
    true
from auth.users user_row
on conflict (id) do update
set
    display_name = case
        when trim(public.profiles.display_name) = '' then excluded.display_name
        else public.profiles.display_name
    end,
    role = case when excluded.role = 'admin' then 'admin' else 'editor' end,
    active = case when excluded.role = 'admin' then true else public.profiles.active end,
    updated_at = now();

alter table public.profiles drop constraint if exists profiles_role_check;
alter table public.profiles
    add constraint profiles_role_check check (role in ('admin', 'editor'));

do $verification$
declare
    missing_items text[] := array[]::text[];
    required_table text;
    required_permission text;
begin
    foreach required_table in array array[
        'profiles', 'projects', 'project_memberships', 'permissions', 'role_permissions',
        'project_disciplines', 'daily_progress', 'schedule_rows',
        'subcontractor_workflows', 'contract_matrix', 'payments',
        'eng_partners', 'eng_assignments', 'eng_event_rounds'
    ] loop
        if to_regclass('public.' || required_table) is null then
            missing_items := array_append(missing_items, 'tabla: ' || required_table);
        end if;
    end loop;

    foreach required_permission in array array[
        'project_create', 'project_write', 'project_delete', 'admin_panel'
    ] loop
        if not exists (
            select 1 from public.permissions where permission_key = required_permission
        ) then
            missing_items := array_append(missing_items, 'jogosultsag: ' || required_permission);
        end if;
    end loop;

    if to_regprocedure('public.has_permission(text)') is null then
        missing_items := array_append(missing_items, 'has_permission RPC');
    end if;
    if to_regprocedure('public.can_access_project(bigint,boolean)') is null then
        missing_items := array_append(missing_items, 'can_access_project RPC');
    end if;
    if to_regprocedure('public.create_project(jsonb)') is null then
        missing_items := array_append(missing_items, 'create_project RPC');
    end if;
    if to_regprocedure('public.update_project(bigint,jsonb)') is null then
        missing_items := array_append(missing_items, 'update_project RPC');
    end if;
    if to_regprocedure('public.archive_project(bigint)') is null then
        missing_items := array_append(missing_items, 'archive_project RPC');
    end if;

    if cardinality(missing_items) > 0 then
        raise exception 'Hianyos Project Control telepites: %', array_to_string(missing_items, ', ');
    end if;
end;
$verification$;

commit;

-- A riport nem var el korabbi projektadatot; ures rendszerben is sikeres lehet.
select * from (
    select
        'rendszerobjektumok'::text as ellenorzes,
        'rendben'::text as eredmeny
    union all
    select
        'projekt CRUD RPC-k',
        case when
            to_regprocedure('public.create_project(jsonb)') is not null and
            to_regprocedure('public.update_project(bigint,jsonb)') is not null and
            to_regprocedure('public.archive_project(bigint)') is not null
        then 'rendben' else 'hianyos' end
    union all
    select
        'admin profilok',
        concat(
            count(*) filter (
                where lower(auth_user.email) in ('admin@demo.local', 'admin@example.com')
                  and profile.role = 'admin' and profile.active
            ),
            ' aktiv admin'
        )
    from auth.users auth_user
    join public.profiles profile on profile.id = auth_user.id
    union all
    select
        'aktiv projektek',
        count(*)::text
    from public.projects
    where not is_deleted
) report
order by ellenorzes;
