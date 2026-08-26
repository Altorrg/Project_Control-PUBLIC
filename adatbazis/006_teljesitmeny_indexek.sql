-- Project Control - gyakori projekt- es folyamatlekerdezesek indexei
-- Adatot nem modosit; tobbszor is biztonsagosan futtathato.

begin;

create index if not exists idx_subcontractor_folders_project_order
    on public.subcontractor_folders(project_id, display_order, id);

create index if not exists idx_offer_parts_workflow
    on public.offer_parts(workflow_id, id);

create index if not exists idx_contract_parts_workflow
    on public.contract_parts(workflow_id, id);

create index if not exists idx_contract_changes_workflow_date
    on public.contract_changes(workflow_id, change_date, id);

create index if not exists idx_contract_stages_project_order
    on public.contract_stages(project_id, sort_order, id);

create index if not exists idx_payments_project_status
    on public.payments(project_id, status);

create index if not exists idx_payments_project_reference
    on public.payments(project_id, reference);

commit;
