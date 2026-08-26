-- Project Control Web - security, RLS and transactional business logic
-- Futtatási sorrend: 001_adatbazis_sema.sql után.

begin;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

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

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_auth_user();

create or replace function public.current_role()
returns text
language sql
stable
security definer
set search_path = ''
as $$
    select coalesce((select p.role from public.profiles p where p.id = auth.uid() and p.active), 'anonymous');
$$;

create or replace function public.has_permission(permission_key text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select case
        when auth.uid() is null then false
        when public.current_role() = 'admin' then true
        else coalesce((
            select rp.allowed
            from public.role_permissions rp
            where rp.role = public.current_role() and rp.permission_key = $1
        ), false)
    end;
$$;

create or replace function public.can_access_project(target_project_id bigint, write_access boolean default false)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select auth.uid() is not null
       and exists (
            select 1 from public.profiles profile
            where profile.id = auth.uid()
              and profile.active
              and profile.role in ('admin', 'editor')
       );
$$;

create or replace function public.app_today()
returns date
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    offset_days integer := 0;
    force_first boolean := false;
    result_date date;
begin
    select coalesce((setting_value #>> '{}')::integer, 0)
      into offset_days
      from public.app_settings where setting_key = 'time_offset_days';
    select coalesce((setting_value #>> '{}')::boolean, false)
      into force_first
      from public.app_settings where setting_key = 'force_first_of_month';
    result_date := current_date + coalesce(offset_days, 0);
    if force_first then
        result_date := date_trunc('month', result_date)::date;
    end if;
    return result_date;
exception when others then
    return current_date;
end;
$$;

create or replace function public.write_audit_log()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    old_value jsonb := case when tg_op = 'INSERT' then '{}'::jsonb else to_jsonb(old) end;
    new_value jsonb := case when tg_op = 'DELETE' then '{}'::jsonb else to_jsonb(new) end;
    project_value bigint;
    record_id text;
begin
    project_value := nullif(coalesce(new_value ->> 'project_id', old_value ->> 'project_id'), '')::bigint;
    record_id := coalesce(new_value ->> 'id', old_value ->> 'id');
    insert into public.audit_logs(project_id, entity_type, entity_id, action, old_data, new_data, actor_id)
    values (project_value, tg_table_name, record_id, lower(tg_op), old_value, new_value, auth.uid());
    if tg_op = 'DELETE' then return old; end if;
    return new;
end;
$$;

create or replace function public.write_eng_audit_log()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    old_value jsonb := case when tg_op = 'INSERT' then '{}'::jsonb else to_jsonb(old) end;
    new_value jsonb := case when tg_op = 'DELETE' then '{}'::jsonb else to_jsonb(new) end;
    project_value bigint;
    record_id bigint;
begin
    project_value := nullif(coalesce(new_value ->> 'project_id', old_value ->> 'project_id'), '')::bigint;
    record_id := nullif(coalesce(new_value ->> 'id', old_value ->> 'id'), '')::bigint;
    if project_value is null and tg_table_name = 'eng_event_rounds' then
        select a.project_id into project_value
        from public.eng_assignments a
        where a.id = nullif(coalesce(new_value ->> 'assignment_id', old_value ->> 'assignment_id'), '')::bigint;
    end if;
    insert into public.eng_audit_logs(project_id, entity_type, entity_id, action, old_data, new_data, actor_id)
    values (project_value, tg_table_name, record_id, lower(tg_op), old_value, new_value, auth.uid());
    if tg_op = 'DELETE' then return old; end if;
    return new;
end;
$$;

do $$
declare table_name text;
begin
    foreach table_name in array array[
        'profiles', 'projects', 'project_disciplines', 'daily_progress', 'schedule_rows',
        'subcontractor_workflows', 'payments', 'eng_tasks', 'eng_partners', 'eng_assignments', 'eng_event_rounds'
    ] loop
        execute format('drop trigger if exists set_updated_at on public.%I', table_name);
        execute format('create trigger set_updated_at before update on public.%I for each row execute function public.set_updated_at()', table_name);
    end loop;
end;
$$;

do $$
declare table_name text;
begin
    foreach table_name in array array[
        'projects', 'project_disciplines', 'project_phases', 'project_daily_rates', 'daily_progress',
        'schedule_rows', 'schedule_entries', 'project_contract_sections', 'project_milestones',
        'subcontractor_folders', 'subcontractor_workflows', 'offer_parts', 'contract_parts', 'contract_changes', 'contract_stages', 'contract_matrix',
        'contract_base_values', 'contract_metadata', 'payments', 'finance_mappings'
    ] loop
        execute format('drop trigger if exists audit_changes on public.%I', table_name);
        execute format('create trigger audit_changes after insert or update or delete on public.%I for each row execute function public.write_audit_log()', table_name);
    end loop;
    foreach table_name in array array['eng_assignments', 'eng_event_rounds'] loop
        execute format('drop trigger if exists audit_changes on public.%I', table_name);
        execute format('create trigger audit_changes after insert or update or delete on public.%I for each row execute function public.write_eng_audit_log()', table_name);
    end loop;
end;
$$;

-- RLS: core tables
alter table public.profiles enable row level security;
alter table public.projects enable row level security;
alter table public.project_memberships enable row level security;
alter table public.module_visibility enable row level security;
alter table public.permissions enable row level security;
alter table public.role_permissions enable row level security;
alter table public.app_settings enable row level security;
alter table public.notification_dismissals enable row level security;
alter table public.audit_logs enable row level security;

drop policy if exists profiles_read on public.profiles;
create policy profiles_read on public.profiles for select to authenticated
using (id = auth.uid() or public.has_permission('admin_panel'));
drop policy if exists profiles_admin_write on public.profiles;
create policy profiles_admin_write on public.profiles for update to authenticated
using (public.has_permission('admin_panel')) with check (public.has_permission('admin_panel'));

drop policy if exists projects_read on public.projects;
create policy projects_read on public.projects for select to authenticated
using (not is_deleted and public.can_access_project(id, false));
drop policy if exists projects_insert on public.projects;
create policy projects_insert on public.projects for insert to authenticated
with check (public.has_permission('project_create'));
drop policy if exists projects_update on public.projects;
create policy projects_update on public.projects for update to authenticated
using (public.can_access_project(id, true) and public.has_permission('project_write'))
with check (public.can_access_project(id, true) and public.has_permission('project_write'));

drop policy if exists memberships_read on public.project_memberships;
create policy memberships_read on public.project_memberships for select to authenticated
using (profile_id = auth.uid() or public.has_permission('admin_panel'));
drop policy if exists memberships_admin_all on public.project_memberships;
create policy memberships_admin_all on public.project_memberships for all to authenticated
using (public.has_permission('admin_panel')) with check (public.has_permission('admin_panel'));

drop policy if exists visibility_own_read on public.module_visibility;
create policy visibility_own_read on public.module_visibility for select to authenticated
using (profile_id = auth.uid() or public.has_permission('admin_panel'));
drop policy if exists visibility_admin_all on public.module_visibility;
create policy visibility_admin_all on public.module_visibility for all to authenticated
using (public.has_permission('admin_panel')) with check (public.has_permission('admin_panel'));

drop policy if exists permission_read on public.permissions;
create policy permission_read on public.permissions for select to authenticated using (true);
drop policy if exists role_permission_read on public.role_permissions;
create policy role_permission_read on public.role_permissions for select to authenticated using (true);
drop policy if exists role_permission_admin on public.role_permissions;
create policy role_permission_admin on public.role_permissions for all to authenticated
using (public.has_permission('admin_panel')) with check (public.has_permission('admin_panel'));

drop policy if exists settings_read on public.app_settings;
create policy settings_read on public.app_settings for select to authenticated using (true);
drop policy if exists settings_admin on public.app_settings;
create policy settings_admin on public.app_settings for all to authenticated
using (public.has_permission('admin_panel')) with check (public.has_permission('admin_panel'));

drop policy if exists dismissals_own on public.notification_dismissals;
create policy dismissals_own on public.notification_dismissals for all to authenticated
using (profile_id = auth.uid()) with check (profile_id = auth.uid());

drop policy if exists audit_read on public.audit_logs;
create policy audit_read on public.audit_logs for select to authenticated
using (project_id is null and public.has_permission('admin_panel') or public.can_access_project(project_id, false));

-- RLS for project-owned tables
do $$
declare table_name text;
begin
    foreach table_name in array array[
        'project_disciplines', 'project_phases', 'project_daily_rates', 'daily_progress', 'schedule_rows',
        'schedule_entries', 'project_contract_sections', 'project_milestones', 'project_master_settings', 'subcontractor_folders',
        'subcontractor_workflows', 'contract_stages', 'contract_matrix', 'contract_base_values',
        'contract_metadata', 'payments', 'finance_mappings', 'eng_disciplines', 'eng_assignments',
        'eng_approval_requests'
    ] loop
        execute format('alter table public.%I enable row level security', table_name);
        execute format('drop policy if exists project_read on public.%I', table_name);
        execute format(
            'create policy project_read on public.%I for select to authenticated using (public.can_access_project(project_id, false))',
            table_name
        );
        execute format('drop policy if exists project_write on public.%I', table_name);
        execute format(
            'create policy project_write on public.%I for all to authenticated using (public.can_access_project(project_id, true)) with check (public.can_access_project(project_id, true))',
            table_name
        );
    end loop;
end;
$$;

-- RLS for globally visible master data
do $$
declare table_name text;
begin
    foreach table_name in array array[
        'calendar_exceptions', 'global_phases', 'customer_options', 'project_status_options',
        'phase_templates', 'subcontractor_categories', 'subcontractors',
        'eng_tasks', 'eng_statuses', 'eng_intervention_types'
    ] loop
        execute format('alter table public.%I enable row level security', table_name);
        execute format('drop policy if exists master_read on public.%I', table_name);
        execute format('create policy master_read on public.%I for select to authenticated using (true)', table_name);
        execute format('drop policy if exists master_admin on public.%I', table_name);
        execute format(
            'create policy master_admin on public.%I for all to authenticated using (public.has_permission(''master_data_admin'')) with check (public.has_permission(''master_data_admin''))',
            table_name
        );
    end loop;
end;
$$;

alter table public.offer_parts enable row level security;
alter table public.contract_parts enable row level security;
alter table public.contract_changes enable row level security;
do $$
declare table_name text;
begin
    foreach table_name in array array['offer_parts', 'contract_parts', 'contract_changes'] loop
        execute format('drop policy if exists workflow_read on public.%I', table_name);
        execute format(
            'create policy workflow_read on public.%I for select to authenticated using (exists (select 1 from public.subcontractor_workflows w where w.id = workflow_id and public.can_access_project(w.project_id, false)))',
            table_name
        );
        execute format('drop policy if exists workflow_write on public.%I', table_name);
        execute format(
            'create policy workflow_write on public.%I for all to authenticated using (exists (select 1 from public.subcontractor_workflows w where w.id = workflow_id and public.can_access_project(w.project_id, true))) with check (exists (select 1 from public.subcontractor_workflows w where w.id = workflow_id and public.can_access_project(w.project_id, true)))',
            table_name
        );
    end loop;
end;
$$;

-- Engagement-specific RLS
alter table public.eng_partners enable row level security;
alter table public.eng_partner_change_requests enable row level security;
alter table public.eng_event_rounds enable row level security;
alter table public.eng_audit_logs enable row level security;
alter table public.eng_attachments enable row level security;

drop policy if exists partners_read on public.eng_partners;
create policy partners_read on public.eng_partners for select to authenticated using (not is_deleted);

drop policy if exists partner_requests_read on public.eng_partner_change_requests;
create policy partner_requests_read on public.eng_partner_change_requests for select to authenticated
using (requester_id = auth.uid() or public.has_permission('eng_admin'));

drop policy if exists rounds_read on public.eng_event_rounds;
create policy rounds_read on public.eng_event_rounds for select to authenticated
using (exists (select 1 from public.eng_assignments a where a.id = assignment_id and public.can_access_project(a.project_id, false)));
drop policy if exists rounds_write on public.eng_event_rounds;
create policy rounds_write on public.eng_event_rounds for all to authenticated
using (exists (select 1 from public.eng_assignments a where a.id = assignment_id and public.can_access_project(a.project_id, true) and public.has_permission('eng_write')))
with check (exists (select 1 from public.eng_assignments a where a.id = assignment_id and public.can_access_project(a.project_id, true) and public.has_permission('eng_write')));

drop policy if exists eng_audit_read on public.eng_audit_logs;
create policy eng_audit_read on public.eng_audit_logs for select to authenticated
using (project_id is null and public.has_permission('eng_admin') or public.can_access_project(project_id, false));

drop policy if exists attachments_read on public.eng_attachments;
create policy attachments_read on public.eng_attachments for select to authenticated
using (exists (select 1 from public.eng_assignments a where a.id = assignment_id and public.can_access_project(a.project_id, false)));

-- Project CRUD functions
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

create or replace function public.archive_project(target_project_id bigint)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    if not public.has_permission('project_delete') then raise exception 'permission denied'; end if;
    update public.projects set is_deleted = true where id = target_project_id;
end;
$$;

-- Engagement query functions
create or replace function public.search_engagement_assignments(
    target_project_id bigint,
    search_text text default '',
    filter_discipline_id bigint default null,
    filter_task_id bigint default null,
    filter_status_code text default null,
    page_limit integer default 100,
    page_offset integer default 0
)
returns setof jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select to_jsonb(q)
    from (
        select a.*, d.name as discipline_name, d.code as discipline_code,
               t.name as task_name, p.name as partner_name,
               r.proposed_data ->> 'name' as temporary_partner_name,
               s.name as status_name, s.color as status_color, s.icon as status_icon,
               s.is_closed, s.warn,
               count(*) over() as total_count
        from public.eng_assignments a
        join public.eng_disciplines d on d.id = a.discipline_id
        join public.eng_tasks t on t.id = a.task_id
        join public.eng_statuses s on s.code = a.status_code
        left join public.eng_partners p on p.id = a.partner_id
        left join public.eng_partner_change_requests r on r.id = a.temporary_partner_request_id
        where a.project_id = $1 and not a.is_deleted and public.can_access_project(a.project_id, false)
          and ($3 is null or a.discipline_id = $3)
          and ($4 is null or a.task_id = $4)
          and ($5 is null or a.status_code = $5)
          and (coalesce($2, '') = '' or concat_ws(' ', p.name, r.proposed_data ->> 'name', a.address, a.main_note, t.name, d.name) ilike '%' || $2 || '%')
        order by s.priority desc, coalesce(a.last_date, a.updated_at::date) asc, a.id
        limit greatest(1, least($6, 500)) offset greatest($7, 0)
    ) q;
$$;

create or replace function public.engagement_assignment_detail(target_assignment_id bigint)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select to_jsonb(a) || jsonb_build_object(
        'discipline', to_jsonb(d), 'task', to_jsonb(t), 'status', to_jsonb(s),
        'partner', to_jsonb(p), 'temporary_partner_request', to_jsonb(pr),
        'rounds', coalesce((select jsonb_agg(to_jsonb(r) order by r.round_no) from public.eng_event_rounds r where r.assignment_id = a.id), '[]'::jsonb),
        'attachments', coalesce((select jsonb_agg(to_jsonb(f) order by f.created_at desc) from public.eng_attachments f where f.assignment_id = a.id), '[]'::jsonb)
    )
    from public.eng_assignments a
    join public.eng_disciplines d on d.id = a.discipline_id
    join public.eng_tasks t on t.id = a.task_id
    join public.eng_statuses s on s.code = a.status_code
    left join public.eng_partners p on p.id = a.partner_id
    left join public.eng_partner_change_requests pr on pr.id = a.temporary_partner_request_id
    where a.id = $1 and not a.is_deleted and public.can_access_project(a.project_id, false);
$$;

create or replace function public.engagement_dashboard(target_project_id bigint, warning_days integer default 14)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    with base as (
        select a.*, d.name discipline_name, t.name task_name, s.name status_name, s.is_closed, s.warn,
               coalesce(p.name, pr.proposed_data ->> 'name', '') partner_name
        from public.eng_assignments a
        join public.eng_disciplines d on d.id = a.discipline_id
        join public.eng_tasks t on t.id = a.task_id
        join public.eng_statuses s on s.code = a.status_code
        left join public.eng_partners p on p.id = a.partner_id
        left join public.eng_partner_change_requests pr on pr.id = a.temporary_partner_request_id
        where a.project_id = $1 and not a.is_deleted and public.can_access_project(a.project_id, false)
    ), disciplines as (
        select discipline_id, discipline_name, count(*) total_count,
               count(*) filter (where is_closed) closed_count,
               count(*) filter (where warn or valid_until < public.app_today()) attention_count,
               coalesce(sum(weight), 0) total_weight,
               coalesce(sum(weight) filter (where is_closed), 0) closed_weight
        from base group by discipline_id, discipline_name
    )
    select jsonb_build_object(
        'total', (select count(*) from base),
        'closed', (select count(*) from base where is_closed),
        'open', (select count(*) from base where not is_closed),
        'attention', (select count(*) from base where warn or valid_until < public.app_today() or due_date <= public.app_today() + greatest($2, 1)),
        'progress_percent', coalesce((select round(sum(weight) filter (where is_closed) / nullif(sum(weight), 0) * 100, 2) from base), 0),
        'disciplines', coalesce((select jsonb_agg(to_jsonb(d) || jsonb_build_object('progress_percent', round(d.closed_weight / nullif(d.total_weight, 0) * 100, 2)) order by d.discipline_name) from disciplines d), '[]'::jsonb),
        'attention_items', coalesce((select jsonb_agg(to_jsonb(x) order by x.last_date nulls first, x.id) from (select * from base where warn or valid_until < public.app_today() or due_date <= public.app_today() + greatest($2, 1) limit 100) x), '[]'::jsonb)
    );
$$;

create or replace function public.search_engagement_partners(
    search_text text default '',
    filter_org_type text default '',
    include_pending boolean default true,
    page_limit integer default 100
)
returns setof jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select to_jsonb(x) from (
        select p.id, null::bigint as temporary_request_id, p.name, p.address, p.contact_person, p.email, p.phone, p.org_type, p.status, false as temporary
        from public.eng_partners p
        where not p.is_deleted
          and (coalesce($1, '') = '' or concat_ws(' ', p.name, p.address, p.email, p.org_type) ilike '%' || $1 || '%')
          and (coalesce($2, '') = '' or p.org_type = $2)
        union all
        select null::bigint, r.id, r.proposed_data ->> 'name', r.proposed_data ->> 'address', r.proposed_data ->> 'contact_person',
               r.proposed_data ->> 'email', r.proposed_data ->> 'phone', r.proposed_data ->> 'org_type', r.status, true
        from public.eng_partner_change_requests r
        where $3 and r.request_type = 'create' and r.status in ('pending', 'changes_requested') and r.requester_id = auth.uid()
          and (coalesce($1, '') = '' or concat_ws(' ', r.proposed_data ->> 'name', r.proposed_data ->> 'address', r.proposed_data ->> 'email', r.proposed_data ->> 'org_type') ilike '%' || $1 || '%')
          and (coalesce($2, '') = '' or r.proposed_data ->> 'org_type' = $2)
        order by name
        limit greatest(1, least($4, 500))
    ) x;
$$;

-- Engagement transactional write functions
create or replace function public.propose_partner_change(payload jsonb)
returns public.eng_partner_change_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
    request_type_value text := payload ->> 'request_type';
    partner_value bigint := nullif(payload ->> 'partner_id', '')::bigint;
    proposed_value jsonb := coalesce(payload -> 'proposed', '{}'::jsonb);
    old_value jsonb := '{}'::jsonb;
    result public.eng_partner_change_requests;
begin
    if not public.has_permission('eng_write') then raise exception 'permission denied'; end if;
    if request_type_value not in ('create', 'update', 'delete') then raise exception 'invalid request type'; end if;
    if nullif(trim(proposed_value ->> 'name'), '') is null then raise exception 'partner name required'; end if;
    if request_type_value <> 'create' then
        select to_jsonb(p), p.id into old_value, partner_value
        from public.eng_partners p where p.id = partner_value and not p.is_deleted for update;
        if partner_value is null then raise exception 'partner not found'; end if;
    else
        partner_value := null;
    end if;
    if request_type_value = 'delete' then
        proposed_value := proposed_value || jsonb_build_object('delete_reason', coalesce(payload ->> 'reason', ''));
    end if;
    insert into public.eng_partner_change_requests(request_type, partner_id, proposed_data, old_data, requester_id)
    values (request_type_value, partner_value, proposed_value, old_value, auth.uid()) returning * into result;
    insert into public.eng_audit_logs(entity_type, entity_id, action, old_data, new_data, actor_id)
    values ('partner_request', result.id, 'create', old_value, to_jsonb(result), auth.uid());
    return result;
end;
$$;

create or replace function public.review_partner_change_request(target_request_id bigint, decision_payload jsonb)
returns public.eng_partner_change_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
    req public.eng_partner_change_requests;
    partner_value bigint;
    decision_value text := decision_payload ->> 'decision';
    proposed_value jsonb;
begin
    if not public.has_permission('eng_admin') then raise exception 'permission denied'; end if;
    select * into req from public.eng_partner_change_requests where id = $1 for update;
    if req.id is null then raise exception 'request not found'; end if;
    if req.status not in ('pending', 'changes_requested') then raise exception 'request already closed'; end if;
    if decision_value not in ('approved', 'rejected', 'changes_requested') then raise exception 'invalid decision'; end if;
    proposed_value := coalesce(decision_payload -> 'proposed', req.proposed_data);
    if decision_value = 'approved' then
        if req.request_type = 'create' then
            insert into public.eng_partners(name, address, contact_person, email, phone, org_type, status, created_by, approved_by, approved_at)
            values (
                proposed_value ->> 'name', coalesce(proposed_value ->> 'address', ''), coalesce(proposed_value ->> 'contact_person', ''),
                coalesce(proposed_value ->> 'email', ''), coalesce(proposed_value ->> 'phone', ''), coalesce(proposed_value ->> 'org_type', ''),
                'approved', req.requester_id, auth.uid(), now()
            ) returning id into partner_value;
        elsif req.request_type = 'update' then
            update public.eng_partners set
                name = proposed_value ->> 'name', address = coalesce(proposed_value ->> 'address', ''),
                contact_person = coalesce(proposed_value ->> 'contact_person', ''), email = coalesce(proposed_value ->> 'email', ''),
                phone = coalesce(proposed_value ->> 'phone', ''), org_type = coalesce(proposed_value ->> 'org_type', '')
            where id = req.partner_id and not is_deleted returning id into partner_value;
        else
            update public.eng_partners set is_deleted = true, status = 'deleted'
            where id = req.partner_id and not is_deleted returning id into partner_value;
        end if;
        if partner_value is null then raise exception 'partner operation failed'; end if;
        update public.eng_assignments
           set partner_id = partner_value, temporary_partner_request_id = null, updated_by = auth.uid()
         where temporary_partner_request_id = req.id and req.request_type = 'create';
    end if;
    update public.eng_partner_change_requests set
        proposed_data = proposed_value, status = decision_value, partner_id = coalesce(partner_value, req.partner_id),
        reviewer_id = auth.uid(), reviewer_comment = coalesce(decision_payload ->> 'comment', ''), decided_at = now()
    where id = req.id returning * into req;
    insert into public.eng_audit_logs(entity_type, entity_id, action, old_data, new_data, actor_id)
    values ('partner_request', req.id, decision_value, req.old_data, to_jsonb(req), auth.uid());
    return req;
end;
$$;

create or replace function public.create_engagement_assignment(payload jsonb)
returns public.eng_assignments
language plpgsql
security definer
set search_path = ''
as $$
declare result public.eng_assignments;
begin
    if not public.has_permission('eng_write') or not public.can_access_project((payload ->> 'project_id')::bigint, true) then
        raise exception 'permission denied';
    end if;
    insert into public.eng_assignments(
        project_id, discipline_id, partner_id, temporary_partner_request_id, task_id, address, weight,
        main_note, status_code, valid_until, responsible, due_date, created_by, updated_by
    ) values (
        (payload ->> 'project_id')::bigint, (payload ->> 'discipline_id')::bigint,
        nullif(payload ->> 'partner_id', '')::bigint, nullif(payload ->> 'temporary_partner_request_id', '')::bigint,
        (payload ->> 'task_id')::bigint, coalesce(payload ->> 'address', ''), coalesce((payload ->> 'weight')::numeric, 1),
        coalesce(payload ->> 'main_note', ''), coalesce(payload ->> 'status_code', '!'),
        nullif(payload ->> 'valid_until', '')::date, coalesce(payload ->> 'responsible', ''),
        nullif(payload ->> 'due_date', '')::date, auth.uid(), auth.uid()
    ) returning * into result;
    return result;
end;
$$;

create or replace function public.update_engagement_assignment(target_assignment_id bigint, payload jsonb)
returns public.eng_assignments
language plpgsql
security definer
set search_path = ''
as $$
declare result public.eng_assignments;
begin
    select * into result from public.eng_assignments where id = $1 and not is_deleted for update;
    if result.id is null then raise exception 'assignment not found'; end if;
    if not public.has_permission('eng_write') or not public.can_access_project(result.project_id, true) then raise exception 'permission denied'; end if;
    update public.eng_assignments a set
        discipline_id = case when payload ? 'discipline_id' then (payload ->> 'discipline_id')::bigint else a.discipline_id end,
        task_id = case when payload ? 'task_id' then (payload ->> 'task_id')::bigint else a.task_id end,
        partner_id = case when payload ? 'partner_id' then nullif(payload ->> 'partner_id', '')::bigint else a.partner_id end,
        temporary_partner_request_id = case when payload ? 'temporary_partner_request_id' then nullif(payload ->> 'temporary_partner_request_id', '')::bigint else a.temporary_partner_request_id end,
        address = case when payload ? 'address' then coalesce(payload ->> 'address', '') else a.address end,
        weight = case when payload ? 'weight' then (payload ->> 'weight')::numeric else a.weight end,
        main_note = case when payload ? 'main_note' then coalesce(payload ->> 'main_note', '') else a.main_note end,
        status_code = case when payload ? 'status_code' then payload ->> 'status_code' else a.status_code end,
        valid_until = case when payload ? 'valid_until' then nullif(payload ->> 'valid_until', '')::date else a.valid_until end,
        responsible = case when payload ? 'responsible' then coalesce(payload ->> 'responsible', '') else a.responsible end,
        due_date = case when payload ? 'due_date' then nullif(payload ->> 'due_date', '')::date else a.due_date end,
        manual_override = case when payload ? 'manual_override' then (payload ->> 'manual_override')::boolean else a.manual_override end,
        updated_by = auth.uid()
    where a.id = $1 returning * into result;
    return result;
end;
$$;

create or replace function public.archive_engagement_assignment(target_assignment_id bigint)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare project_value bigint;
begin
    select project_id into project_value from public.eng_assignments where id = $1;
    if not public.has_permission('eng_write') or not public.can_access_project(project_value, true) then raise exception 'permission denied'; end if;
    update public.eng_assignments set is_deleted = true, updated_by = auth.uid() where id = $1;
end;
$$;

create or replace function public.refresh_assignment_from_rounds(target_assignment_id bigint)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare latest_status text;
begin
    select r.status_code into latest_status
    from public.eng_event_rounds r where r.assignment_id = $1 order by r.round_no desc limit 1;
    update public.eng_assignments a set
        last_date = (select max(value_date) from (
            select r.sent_date value_date from public.eng_event_rounds r where r.assignment_id = a.id
            union all select r.received_date from public.eng_event_rounds r where r.assignment_id = a.id
        ) dates),
        status_code = case when not a.manual_override and latest_status is not null then latest_status else a.status_code end,
        updated_by = auth.uid()
    where a.id = $1;
end;
$$;

create or replace function public.create_engagement_round(target_assignment_id bigint, payload jsonb)
returns public.eng_event_rounds
language plpgsql
security definer
set search_path = ''
as $$
declare result public.eng_event_rounds; project_value bigint;
begin
    select project_id into project_value from public.eng_assignments where id = $1 and not is_deleted;
    if not public.has_permission('eng_write') or not public.can_access_project(project_value, true) then raise exception 'permission denied'; end if;
    insert into public.eng_event_rounds(assignment_id, round_no, sent_date, sent_note, received_date, received_note, intervention_type_id, status_code, created_by)
    values (
        $1, coalesce((select max(round_no) + 1 from public.eng_event_rounds where assignment_id = $1), 1),
        nullif(payload ->> 'sent_date', '')::date, coalesce(payload ->> 'sent_note', ''),
        nullif(payload ->> 'received_date', '')::date, coalesce(payload ->> 'received_note', ''),
        nullif(payload ->> 'intervention_type_id', '')::bigint, payload ->> 'status_code', auth.uid()
    ) returning * into result;
    perform public.refresh_assignment_from_rounds($1);
    return result;
end;
$$;

create or replace function public.update_engagement_round(target_round_id bigint, payload jsonb)
returns public.eng_event_rounds
language plpgsql
security definer
set search_path = ''
as $$
declare result public.eng_event_rounds; project_value bigint;
begin
    select r.* into result from public.eng_event_rounds r where r.id = $1 for update;
    if result.id is null then raise exception 'round not found'; end if;
    select a.project_id into project_value from public.eng_assignments a where a.id = result.assignment_id;
    if not public.has_permission('eng_write') or not public.can_access_project(project_value, true) then raise exception 'permission denied'; end if;
    update public.eng_event_rounds set
        sent_date = nullif(payload ->> 'sent_date', '')::date,
        sent_note = coalesce(payload ->> 'sent_note', ''),
        received_date = nullif(payload ->> 'received_date', '')::date,
        received_note = coalesce(payload ->> 'received_note', ''),
        intervention_type_id = nullif(payload ->> 'intervention_type_id', '')::bigint,
        status_code = payload ->> 'status_code'
    where id = $1 returning * into result;
    perform public.refresh_assignment_from_rounds(result.assignment_id);
    return result;
end;
$$;

create or replace function public.delete_engagement_round(target_round_id bigint)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare assignment_value bigint; project_value bigint;
begin
    select r.assignment_id, a.project_id into assignment_value, project_value
    from public.eng_event_rounds r join public.eng_assignments a on a.id = r.assignment_id where r.id = $1;
    if not public.has_permission('eng_write') or not public.can_access_project(project_value, true) then raise exception 'permission denied'; end if;
    delete from public.eng_event_rounds where id = $1;
    with ranked as (select id, row_number() over(order by round_no, id) rn from public.eng_event_rounds where assignment_id = assignment_value)
    update public.eng_event_rounds r set round_no = ranked.rn from ranked where r.id = ranked.id;
    perform public.refresh_assignment_from_rounds(assignment_value);
end;
$$;

create or replace function public.register_engagement_attachment(
    target_assignment_id bigint,
    object_path text,
    original_name text,
    content_type text,
    size_bytes bigint,
    note text default ''
)
returns public.eng_attachments
language plpgsql
security definer
set search_path = ''
as $$
declare result public.eng_attachments; project_value bigint;
begin
    select project_id into project_value from public.eng_assignments where id = $1 and not is_deleted;
    if not public.has_permission('eng_write') or not public.can_access_project(project_value, true) then raise exception 'permission denied'; end if;
    insert into public.eng_attachments(assignment_id, storage_path, original_name, content_type, size_bytes, note, uploaded_by)
    values ($1, $2, $3, $4, $5, coalesce($6, ''), auth.uid()) returning * into result;
    return result;
end;
$$;

create or replace function public.export_engagement_project(target_project_id bigint)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
    select case when public.can_access_project($1, false) then jsonb_build_object(
        'project', (select to_jsonb(p) from public.projects p where p.id = $1 and not p.is_deleted),
        'tasks', coalesce((select jsonb_agg(to_jsonb(t) order by t.sort_order, t.name) from public.eng_tasks t where t.active), '[]'::jsonb),
        'partners', coalesce((select jsonb_agg(to_jsonb(p) order by p.name) from public.eng_partners p where not p.is_deleted), '[]'::jsonb),
        'dashboard', public.engagement_dashboard($1, 14),
        'disciplines', coalesce((
            select jsonb_agg(
                to_jsonb(d) || jsonb_build_object(
                    'assignments', coalesce((
                        select jsonb_agg(
                            to_jsonb(a) || jsonb_build_object(
                                'partner', to_jsonb(p), 'task', to_jsonb(t),
                                'temporary_partner_name', pr.proposed_data ->> 'name',
                                'rounds', coalesce((select jsonb_agg(to_jsonb(r) order by r.round_no) from public.eng_event_rounds r where r.assignment_id = a.id), '[]'::jsonb)
                            ) order by p.name nulls last, a.id
                        )
                        from public.eng_assignments a
                        join public.eng_tasks t on t.id = a.task_id
                        left join public.eng_partners p on p.id = a.partner_id
                        left join public.eng_partner_change_requests pr on pr.id = a.temporary_partner_request_id
                        where a.discipline_id = d.id and not a.is_deleted
                    ), '[]'::jsonb)
                ) order by d.sort_order, d.name
            ) from public.eng_disciplines d where d.project_id = $1 and d.active
        ), '[]'::jsonb)
    ) else null end;
$$;

create or replace function public.import_engagement_workbook(target_project_id bigint, payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    discipline_value jsonb;
    assignment_value jsonb;
    event_value jsonb;
    partner_value jsonb;
    task_value jsonb;
    discipline_id_value bigint;
    partner_id_value bigint;
    task_id_value bigint;
    assignment_id_value bigint;
    status_value text;
    created_disciplines integer := 0;
    created_partners integer := 0;
    created_tasks integer := 0;
    created_assignments integer := 0;
    created_rounds integer := 0;
begin
    if not public.has_permission('eng_admin') or not public.can_access_project($1, true) then raise exception 'permission denied'; end if;

    for task_value in select value from jsonb_array_elements(coalesce(payload -> 'tasks', '[]'::jsonb)) loop
        insert into public.eng_tasks(name, weight, active, sort_order, description)
        values (
            task_value ->> 'name', coalesce((task_value ->> 'weight')::numeric, 1),
            coalesce((task_value ->> 'active')::boolean, true), coalesce((task_value ->> 'sort_order')::integer, 999),
            coalesce(task_value ->> 'description', '')
        ) on conflict (name) do update set
            weight = excluded.weight, active = excluded.active, sort_order = excluded.sort_order,
            description = excluded.description, updated_at = now();
        created_tasks := created_tasks + 1;
    end loop;

    for partner_value in select value from jsonb_array_elements(coalesce(payload -> 'partners', '[]'::jsonb)) loop
        insert into public.eng_partners(name, address, contact_person, email, phone, org_type, status, created_by, approved_by, approved_at)
        values (
            partner_value ->> 'name', coalesce(partner_value ->> 'address', ''), coalesce(partner_value ->> 'contact_person', ''),
            coalesce(partner_value ->> 'email', ''), coalesce(partner_value ->> 'phone', ''), coalesce(partner_value ->> 'org_type', ''),
            'approved', auth.uid(), auth.uid(), now()
        ) on conflict do nothing;
        created_partners := created_partners + 1;
    end loop;

    for discipline_value in select value from jsonb_array_elements(coalesce(payload -> 'disciplines', '[]'::jsonb)) loop
        select id into discipline_id_value from public.eng_disciplines
        where project_id = $1 and name = discipline_value ->> 'name';
        if discipline_id_value is null then
            insert into public.eng_disciplines(project_id, name, sort_order)
            values ($1, discipline_value ->> 'name', coalesce((select max(sort_order) + 10 from public.eng_disciplines where project_id = $1), 10))
            returning id into discipline_id_value;
            created_disciplines := created_disciplines + 1;
        end if;

        for assignment_value in select value from jsonb_array_elements(coalesce(discipline_value -> 'assignments', '[]'::jsonb)) loop
            partner_value := assignment_value -> 'partner';
            select id into partner_id_value from public.eng_partners
            where lower(name) = lower(partner_value ->> 'name') and not is_deleted limit 1;
            if partner_id_value is null then
                insert into public.eng_partners(name, address, status, created_by, approved_by, approved_at)
                values (partner_value ->> 'name', coalesce(partner_value ->> 'address', ''), 'approved', auth.uid(), auth.uid(), now())
                returning id into partner_id_value;
                created_partners := created_partners + 1;
            end if;
            select id into task_id_value from public.eng_tasks where name = assignment_value ->> 'task_name';
            if task_id_value is null then
                insert into public.eng_tasks(name, weight, active, sort_order)
                values (assignment_value ->> 'task_name', coalesce((assignment_value ->> 'weight')::numeric, 1), true, 999)
                returning id into task_id_value;
                created_tasks := created_tasks + 1;
            end if;
            select id into assignment_id_value from public.eng_assignments
            where project_id = $1 and discipline_id = discipline_id_value and partner_id = partner_id_value
              and task_id = task_id_value and not is_deleted limit 1;
            if assignment_id_value is not null then continue; end if;
            status_value := coalesce(assignment_value ->> 'status_code', '!');
            if not exists (select 1 from public.eng_statuses where code = status_value) then status_value := '!'; end if;
            insert into public.eng_assignments(
                project_id, discipline_id, partner_id, task_id, address, weight, main_note, last_date,
                status_code, valid_until, created_by, updated_by
            ) values (
                $1, discipline_id_value, partner_id_value, task_id_value, coalesce(partner_value ->> 'address', ''),
                coalesce((assignment_value ->> 'weight')::numeric, 1), coalesce(assignment_value ->> 'main_note', ''),
                nullif(assignment_value ->> 'last_date', '')::date, status_value,
                nullif(assignment_value ->> 'valid_until', '')::date, auth.uid(), auth.uid()
            ) returning id into assignment_id_value;
            created_assignments := created_assignments + 1;
            for event_value in select value from jsonb_array_elements(coalesce(assignment_value -> 'rounds', '[]'::jsonb)) loop
                insert into public.eng_event_rounds(
                    assignment_id, round_no, sent_date, sent_note, received_date, received_note, status_code, created_by
                ) values (
                    assignment_id_value,
                    coalesce((select max(round_no) + 1 from public.eng_event_rounds where assignment_id = assignment_id_value), 1),
                    nullif(event_value ->> 'sent_date', '')::date, coalesce(event_value ->> 'sent_note', ''),
                    nullif(event_value ->> 'received_date', '')::date, coalesce(event_value ->> 'received_note', ''),
                    coalesce(event_value ->> 'status_code', status_value), auth.uid()
                );
                created_rounds := created_rounds + 1;
            end loop;
            perform public.refresh_assignment_from_rounds(assignment_id_value);
        end loop;
    end loop;
    insert into public.eng_audit_logs(project_id, entity_type, entity_id, action, new_data, actor_id)
    values ($1, 'import', $1, 'excel_import', payload -> 'summary', auth.uid());
    return jsonb_build_object(
        'disciplines', created_disciplines, 'partners', created_partners, 'tasks', created_tasks,
        'assignments', created_assignments, 'rounds', created_rounds,
        'errors', coalesce(payload -> 'errors', '[]'::jsonb), 'duplicates', coalesce(payload -> 'duplicates', '[]'::jsonb)
    );
end;
$$;

-- Monthly discipline helper
create or replace function public.add_daily_progress_month(target_project_id bigint, month_value date, phase_value text default '')
returns setof public.daily_progress
language plpgsql
security definer
set search_path = ''
as $$
begin
    if not public.can_access_project($1, true) or not public.has_permission('discipline_write') then raise exception 'permission denied'; end if;
    insert into public.daily_progress(project_id, discipline_name, record_date, phase, days, actual_percent, planned_percent, created_by)
    select $1, d.name, date_trunc('month', $2)::date, coalesce($3, ''), 0, 0, 0, auth.uid()
    from public.project_disciplines d where d.project_id = $1 and d.visible
    on conflict (project_id, discipline_name, record_date) do nothing;
    return query select * from public.daily_progress where project_id = $1 and record_date = date_trunc('month', $2)::date order by discipline_name;
end;
$$;

-- Notification generation preserves the desktop 10/25 day and month-start rules.
create or replace function public.current_notifications()
returns setof jsonb
language sql
stable
security definer
set search_path = ''
as $$
    with today_value as (select public.app_today() value), candidates as (
        select 'monthly:timesheet:' || to_char(t.value, 'YYYY-MM') alert_key, 0::bigint project_id,
               'Általános' project_name, 'Belső szakágak' subject,
               'Havi emlékeztető: jelenléti ívek lezárása' message, 'monthly' alert_type
        from today_value t
        where extract(day from t.value) <= 5 and public.current_role() in ('admin', 'editor')
        union all
        select 'sub:' || w.id || ':' || to_char(w.updated_at, 'YYYYMMDDHH24MISS'), w.project_id, p.name, w.company_name,
               (public.app_today() - w.updated_at::date) || ' napja áll az alvállalkozói folyamat', 'sub'
        from public.subcontractor_workflows w join public.projects p on p.id = w.project_id, today_value t
        where not w.is_deleted and w.signature_status <> 'Aláírva' and public.can_access_project(w.project_id, false)
          and extract(day from t.value) <= 5 and t.value - w.updated_at::date >= 10
        union all
        select 'eng:' || a.id || ':' || to_char(coalesce(a.last_date, a.updated_at::date), 'YYYYMMDD'), a.project_id, p.name,
               coalesce(ep.name, d.name),
               'Engedélyezés: ' || (public.app_today() - coalesce(a.last_date, a.updated_at::date)) || ' napja nincs előrelépés. ' || et.name || ' | ' || s.code || ' - ' || s.name,
               'eng'
        from public.eng_assignments a
        join public.projects p on p.id = a.project_id
        join public.eng_disciplines d on d.id = a.discipline_id
        join public.eng_tasks et on et.id = a.task_id
        join public.eng_statuses s on s.code = a.status_code
        left join public.eng_partners ep on ep.id = a.partner_id, today_value t
        where not a.is_deleted and not s.is_closed and public.can_access_project(a.project_id, false)
          and extract(day from t.value) <= 5 and t.value - coalesce(a.last_date, a.updated_at::date) >= 25
    )
    select to_jsonb(c)
    from candidates c
    where not exists (
        select 1 from public.notification_dismissals d
        where d.profile_id = auth.uid() and d.alert_key = c.alert_key
          and (d.dismiss_mode = 'forever' or d.snooze_until > now())
    )
    order by c.project_name, c.alert_type, c.subject;
$$;

create or replace function public.dismiss_notification(alert_key text, dismiss_mode text, snooze_days integer default null)
returns public.notification_dismissals
language plpgsql
security definer
set search_path = ''
as $$
declare result public.notification_dismissals;
begin
    if auth.uid() is null then raise exception 'authentication required'; end if;
    if $2 not in ('snooze', 'forever') then raise exception 'invalid dismiss mode'; end if;
    if $2 = 'snooze' and coalesce($3, 0) <= 0 then raise exception 'snooze days required'; end if;
    insert into public.notification_dismissals(profile_id, alert_key, dismissed_at, snooze_until, dismiss_mode)
    values (auth.uid(), $1, now(), case when $2 = 'snooze' then now() + make_interval(days => $3) else null end, $2)
    on conflict (profile_id, alert_key) do update set
        dismissed_at = excluded.dismissed_at, snooze_until = excluded.snooze_until, dismiss_mode = excluded.dismiss_mode
    returning * into result;
    return result;
end;
$$;

-- Private Supabase Storage bucket for engagement attachments.
insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values (
    'engagement-attachments', 'engagement-attachments', false, 20971520,
    array[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-excel.sheet.macroenabled.12',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'image/jpeg', 'image/png'
    ]
)
on conflict (id) do update set
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists engagement_storage_insert on storage.objects;
create policy engagement_storage_insert on storage.objects for insert to authenticated
with check (
    bucket_id = 'engagement-attachments'
    and public.has_permission('eng_write')
    and name ~ '^assignments/[0-9]+/'
    and exists (
        select 1 from public.eng_assignments a
        where a.id = split_part(name, '/', 2)::bigint
          and public.can_access_project(a.project_id, true)
    )
);
drop policy if exists engagement_storage_read on storage.objects;
create policy engagement_storage_read on storage.objects for select to authenticated
using (
    bucket_id = 'engagement-attachments'
    and name ~ '^assignments/[0-9]+/'
    and exists (
        select 1 from public.eng_assignments a
        where a.id = split_part(name, '/', 2)::bigint
          and public.can_access_project(a.project_id, false)
    )
);
drop policy if exists engagement_storage_delete on storage.objects;
create policy engagement_storage_delete on storage.objects for delete to authenticated
using (
    bucket_id = 'engagement-attachments'
    and name ~ '^assignments/[0-9]+/'
    and (owner_id = (select auth.uid()::text) or public.has_permission('eng_admin'))
    and exists (
        select 1 from public.eng_assignments a
        where a.id = split_part(name, '/', 2)::bigint
          and public.can_access_project(a.project_id, true)
    )
);

grant usage on schema public to authenticated;
grant select, insert, update, delete on all tables in schema public to authenticated;
grant usage, select on all sequences in schema public to authenticated;
revoke all on all tables in schema public from anon;

revoke all on function public.review_partner_change_request(bigint, jsonb) from public, anon;
revoke all on function public.create_engagement_assignment(jsonb) from public, anon;
revoke all on function public.update_engagement_assignment(bigint, jsonb) from public, anon;
revoke all on function public.create_engagement_round(bigint, jsonb) from public, anon;
grant execute on all functions in schema public to authenticated;
revoke execute on function public.set_updated_at() from public, anon, authenticated;
revoke execute on function public.handle_new_auth_user() from public, anon, authenticated;
revoke execute on function public.write_audit_log() from public, anon, authenticated;
revoke execute on function public.write_eng_audit_log() from public, anon, authenticated;
revoke execute on function public.refresh_assignment_from_rounds(bigint) from public, anon, authenticated;

commit;
