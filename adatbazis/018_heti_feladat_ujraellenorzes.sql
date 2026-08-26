begin;

-- Csak az ertesitesbol letrehozott teendok kapnak forraskulcsot.
-- A kezzel rogzitett egyedi feladatok erteke NULL marad, ezert a heti
-- automatikus ellenorzes biztosan nem dolgozza fel oket.
alter table public.notification_tasks
    add column if not exists source_alert_key text;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'public.notification_tasks'::regclass
          and conname = 'notification_tasks_source_alert_key_length'
    ) then
        alter table public.notification_tasks
            add constraint notification_tasks_source_alert_key_length
            check (source_alert_key is null or char_length(source_alert_key) between 1 and 500);
    end if;
end;
$$;

create index if not exists notification_tasks_source_alert_idx
    on public.notification_tasks(profile_id, source_alert_key, completed_at)
    where source_alert_key is not null;

create or replace function public.weekly_completed_task_notifications()
returns setof jsonb
language sql
stable
security definer
set search_path = ''
as $$
    with today_value as (
        select public.app_today() value
    ),
    month_values as (
        select
            value,
            (date_trunc('month', value)::date - interval '1 month')::date previous_month,
            date_trunc('month', value)::date current_month
        from today_value
    ),
    project_quality as (
        select
            p.id,
            p.name,
            m.value,
            not exists (
                select 1 from public.project_daily_rates rate
                where rate.project_id = p.id
                  and rate.year = extract(year from m.value)::integer
            ) missing_daily_rate,
            not exists (
                select 1 from public.project_contract_sections section
                where section.project_id = p.id
            ) missing_contract_section,
            exists (
                select 1 from public.project_contract_sections section
                where section.project_id = p.id
            ) and not exists (
                select 1 from public.project_milestones milestone
                where milestone.project_id = p.id
            ) missing_milestone
        from public.projects p
        cross join month_values m
        where not p.is_deleted
          and public.can_access_project(p.id, false)
    ),
    active_sources as (
        -- Az idokaput itt szandekosan nem alkalmazzuk: penteken azt kell
        -- ellenorizni, hogy a korabbi problema tenylegesen fennall-e meg.
        select
            'monthly:timesheet:' || p.id || ':' || d.id || ':' || to_char(m.previous_month, 'YYYY-MM') alert_key,
            p.id project_id,
            p.name project_name,
            d.name || ' - előző havi munkaidő' subject,
            'A(z) ' || to_char(m.previous_month, 'YYYY. MM.') || ' havi munkaidő még nincs rögzítve.' message,
            'disciplines' target_module,
            d.id target_id
        from public.projects p
        join public.project_disciplines d on d.project_id = p.id and d.visible
        cross join month_values m
        where not p.is_deleted
          and public.can_access_project(p.id, false)
          and not exists (
              select 1
              from public.daily_progress progress
              where progress.project_id = p.id
                and progress.discipline_name = d.name
                and progress.record_date >= m.previous_month
                and progress.record_date < m.current_month
          )

        union all

        select
            'quality:project:' || quality.id || ':' || extract(year from quality.value)::integer || ':' ||
                quality.missing_daily_rate::integer || quality.missing_contract_section::integer || quality.missing_milestone::integer,
            quality.id,
            quality.name,
            'Projektadatok kiegészítése',
            concat_ws(' ',
                case when quality.missing_daily_rate then 'Nincs aktuális éves napidíj beállítva.' end,
                case when quality.missing_contract_section then 'Nincs főszerződéses pénzügyi fázis rögzítve.' end,
                case when quality.missing_milestone then 'A pénzügyi fázisokhoz nincs pénzügyi mérföldkő.' end
            ),
            'settings',
            null::bigint
        from project_quality quality
        where quality.missing_daily_rate or quality.missing_contract_section or quality.missing_milestone

        union all

        select
            'quality:subcontractor-mapping:' || p.id || ':' || count(*) || ':' || max(w.id),
            p.id,
            p.name,
            'Hiányzó pénzügyi összerendelés',
            count(*) || ' elfogadott alvállalkozói szerződés nincs belső szakághoz rendelve.',
            'finance',
            null::bigint
        from public.subcontractor_workflows w
        join public.projects p on p.id = w.project_id
        where not w.is_deleted
          and w.acceptance = 'Elfogadva'
          and public.can_access_project(w.project_id, false)
          and not exists (
              select 1 from public.finance_mappings mapping
              where mapping.project_id = w.project_id and mapping.workflow_id = w.id
          )
        group by p.id, p.name

        union all

        select
            'review:schedule-row:' || p.id || ':' || count(*) || ':' || max(review.id),
            p.id,
            p.name,
            'Ütemtervi besorolás ellenőrzése',
            count(*) || ' régi ütemtervi elem pénzügyi fázisát kell ellenőrizni.',
            'schedule',
            null::bigint
        from public.schedule_rows_financial_phase_review review
        join public.projects p on p.id = review.project_id
        where public.can_access_project(review.project_id, false)
        group by p.id, p.name

        union all

        select
            'review:subcontractor-key:' || p.id || ':' || count(*) || ':' || max(review.workflow_id),
            p.id,
            p.name,
            'Alvállalkozói tervezési mérföldkövek ellenőrzése',
            count(*) || ' alvállalkozói folyamat tervezési mérföldkő-hozzárendelését kell ellenőrizni.',
            'subcontractors',
            null::bigint
        from public.subcontractor_workflow_schedule_key_review review
        join public.projects p on p.id = review.project_id
        where public.can_access_project(review.project_id, false)
        group by p.id, p.name

        union all

        select
            'sub:' || w.id || ':' || to_char(w.updated_at, 'YYYYMMDDHH24MISS'),
            w.project_id,
            p.name,
            w.company_name,
            (m.value - w.updated_at::date) || ' napja áll az alvállalkozói folyamat',
            'subcontractors',
            w.id
        from public.subcontractor_workflows w
        join public.projects p on p.id = w.project_id
        cross join month_values m
        where not w.is_deleted
          and w.signature_status <> 'Aláírva'
          and public.can_access_project(w.project_id, false)
          and m.value - w.updated_at::date >= 10

        union all

        select
            'eng:' || a.id || ':' || to_char(coalesce(a.last_date, a.updated_at::date), 'YYYYMMDD'),
            a.project_id,
            p.name,
            coalesce(ep.name, d.name),
            'Engedélyezés: ' || (m.value - coalesce(a.last_date, a.updated_at::date)) ||
                ' napja nincs előrelépés. ' || et.name || ' | ' || s.code || ' - ' || s.name,
            'engagements',
            a.id
        from public.eng_assignments a
        join public.projects p on p.id = a.project_id
        join public.eng_disciplines d on d.id = a.discipline_id
        join public.eng_tasks et on et.id = a.task_id
        join public.eng_statuses s on s.code = a.status_code
        left join public.eng_partners ep on ep.id = a.partner_id
        cross join month_values m
        where not a.is_deleted
          and not s.is_closed
          and public.can_access_project(a.project_id, false)
          and m.value - coalesce(a.last_date, a.updated_at::date) >= 25
    ),
    completed_sources as (
        select distinct on (task.source_alert_key)
            task.id,
            task.source_alert_key,
            task.priority
        from public.notification_tasks task
        where task.profile_id = auth.uid()
          and task.source_alert_key is not null
          and task.completed_at is not null
        order by task.source_alert_key, task.completed_at desc, task.id desc
    ),
    rechecks as (
        select
            'weekly:task-recheck:' || task.id || ':' || to_char(today.value, 'IYYY-IW') alert_key,
            task.source_alert_key,
            source.project_id,
            source.project_name,
            'Újra ellenőrizendő: ' || source.subject subject,
            'A teendőt korábban készre jelölted, de az alapadatok szerint a probléma továbbra is fennáll. ' ||
                source.message message,
            source.target_module,
            source.target_id,
            today.value due_date,
            task.priority
        from completed_sources task
        join active_sources source on source.alert_key = task.source_alert_key
        cross join today_value today
        where extract(isodow from today.value) = 5
          and (current_timestamp at time zone 'Europe/Budapest')::time >= time '09:00'
    )
    select jsonb_build_object(
        'alert_key', recheck.alert_key,
        'source_alert_key', recheck.source_alert_key,
        'project_id', recheck.project_id,
        'project_name', recheck.project_name,
        'subject', recheck.subject,
        'message', recheck.message,
        'alert_type', 'weekly_recheck',
        'target_module', recheck.target_module,
        'target_id', recheck.target_id,
        'due_date', recheck.due_date,
        'priority', recheck.priority
    )
    from rechecks recheck
    left join public.notification_dismissals dismissal
      on dismissal.profile_id = auth.uid() and dismissal.alert_key = recheck.alert_key
    where dismissal.alert_key is null or (
        dismissal.dismiss_mode <> 'forever'
        and (dismissal.snooze_until is null or dismissal.snooze_until <= now())
    )
    order by recheck.priority, recheck.project_name, recheck.subject;
$$;

revoke all on function public.weekly_completed_task_notifications() from public, anon;
grant execute on function public.weekly_completed_task_notifications() to authenticated;

notify pgrst, 'reload schema';

commit;

select
    exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'notification_tasks'
          and column_name = 'source_alert_key'
    ) as notification_task_source_ready,
    to_regprocedure('public.weekly_completed_task_notifications()') is not null
        as weekly_task_recheck_ready;
