-- Feature 1 additive migration. Prepared for review; do not apply automatically.
-- Server writes require a backend-only Supabase secret/service key. Authenticated
-- users can read only their own runs and clauses; they cannot forge result rows.
begin;

alter table public.analysis_jobs
    add constraint analysis_jobs_condition_scope_unique
    unique (id, owner_id, policy_id, document_id);

create table public.claim_condition_runs (
    job_id uuid primary key,
    owner_id uuid not null references auth.users(id) on delete cascade,
    policy_id uuid not null,
    document_id uuid not null,
    analysis_state text check (analysis_state in ('complete', 'incomplete')),
    warning text,
    rejected_candidate_count integer not null default 0
        check (rejected_candidate_count >= 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (job_id, owner_id, policy_id, document_id)
        references public.analysis_jobs(id, owner_id, policy_id, document_id)
        on delete cascade,
    unique (job_id, owner_id, policy_id, document_id),
    unique (owner_id, document_id),
    check (analysis_state <> 'incomplete' or warning is not null)
);
create index claim_condition_runs_owner_policy
    on public.claim_condition_runs(owner_id, policy_id, created_at desc);

create table public.claim_conditions (
    job_id uuid not null,
    id text not null check (id ~ '^condition_[a-f0-9]{20}$'),
    owner_id uuid not null,
    policy_id uuid not null,
    document_id uuid not null,
    payload jsonb not null check (jsonb_typeof(payload) = 'object'),
    created_at timestamptz not null default now(),
    primary key (job_id, id),
    foreign key (job_id, owner_id, policy_id, document_id)
        references public.claim_condition_runs(job_id, owner_id, policy_id, document_id)
        on delete cascade,
    check (payload->>'id' = id),
    check (payload->>'job_id' = job_id::text),
    check (payload->>'document_id' = document_id::text),
    check (payload->>'source_verified' = 'true'),
    check (payload->>'review_required' = 'true')
);
create index claim_conditions_owner_policy_job
    on public.claim_conditions(owner_id, policy_id, job_id);

alter table public.claim_condition_runs enable row level security;
alter table public.claim_conditions enable row level security;
create policy claim_condition_runs_owner_read on public.claim_condition_runs
    for select to authenticated using ((select auth.uid()) = owner_id);
create policy claim_conditions_owner_read on public.claim_conditions
    for select to authenticated using ((select auth.uid()) = owner_id);

revoke all on public.claim_condition_runs, public.claim_conditions
    from public, anon, authenticated;
grant select on public.claim_condition_runs, public.claim_conditions
    to authenticated;
grant select, insert, update, delete
    on public.claim_condition_runs, public.claim_conditions to service_role;
grant select, update on public.documents to service_role;
grant select on public.document_pages to service_role;
grant select, insert, update on public.analysis_jobs to service_role;

-- Invoker functions run only as service_role. The backend authenticates the
-- request first; the database independently checks owner/policy/document scope.
create function public.start_condition_discovery(
    p_owner_id uuid, p_policy_id uuid, p_document_id uuid
) returns jsonb language plpgsql security invoker set search_path = public, pg_temp as $$
declare v_job_id uuid; v_status text;
begin
    -- Lock the document so simultaneous requests cannot create duplicate runs.
    perform 1 from public.documents
        where id = p_document_id and owner_id = p_owner_id
          and policy_id = p_policy_id and processing_status = 'extracted'
        for update;
    if not found then raise sqlstate 'PT404' using message = 'Document not found.'; end if;
    if not exists (select 1 from public.document_pages
                   where document_id = p_document_id and owner_id = p_owner_id) then
        raise exception 'No extracted pages';
    end if;
    select r.job_id, j.status into v_job_id, v_status
        from public.claim_condition_runs r
        join public.analysis_jobs j on j.id = r.job_id
        where r.owner_id = p_owner_id and r.document_id = p_document_id;
    if found then
        return jsonb_build_object('job_id', v_job_id, 'created', false, 'status', v_status);
    end if;
    v_job_id := gen_random_uuid();
    insert into public.analysis_jobs
        (id, owner_id, policy_id, document_id, status, stage, message)
        values (v_job_id, p_owner_id, p_policy_id, p_document_id,
                'queued', 'uploaded', 'Claim-condition discovery queued.');
    insert into public.claim_condition_runs(job_id, owner_id, policy_id, document_id)
        values (v_job_id, p_owner_id, p_policy_id, p_document_id);
    return jsonb_build_object('job_id', v_job_id, 'created', true, 'status', 'queued');
end;
$$;

create function public.mark_condition_processing(p_job_id uuid, p_owner_id uuid)
returns void language plpgsql security invoker set search_path = public, pg_temp as $$
begin
    update public.analysis_jobs set status = 'processing', stage = 'analyzing',
        message = 'Discovering review-only policy conditions.', updated_at = now()
        where id = p_job_id and owner_id = p_owner_id and status = 'queued'
          and exists (select 1 from public.claim_condition_runs r
                      where r.job_id = p_job_id and r.owner_id = p_owner_id);
    if not found then raise sqlstate 'PT404' using message = 'Job not found.'; end if;
end;
$$;

create function public.finish_condition_discovery(
    p_job_id uuid, p_owner_id uuid, p_items jsonb, p_incomplete boolean,
    p_warning text, p_rejected_count integer, p_error_code text
) returns void language plpgsql security invoker set search_path = public, pg_temp as $$
declare v_run public.claim_condition_runs; v_item jsonb; v_evidence jsonb;
        v_page integer; v_start integer; v_end integer; v_quote text;
begin
    select * into v_run from public.claim_condition_runs
        where job_id = p_job_id and owner_id = p_owner_id for update;
    if not found then raise sqlstate 'PT404' using message = 'Job not found.'; end if;
    perform 1 from public.analysis_jobs
        where id = p_job_id and owner_id = p_owner_id and status = 'processing' for update;
    if not found then raise sqlstate 'PT404' using message = 'Job not processing.'; end if;
    if p_items is null or jsonb_typeof(p_items) <> 'array'
        or jsonb_array_length(p_items) > 128
        or p_rejected_count is null or p_rejected_count < 0
        or p_incomplete is null
        or (jsonb_array_length(p_items) = 0 and not p_incomplete)
        or (p_incomplete and (p_warning is null or length(p_warning) > 500)) then
        raise exception 'Invalid condition result';
    end if;
    if p_error_code is null then
        for v_item in select value from jsonb_array_elements(p_items) loop
            if jsonb_typeof(v_item->'evidence') <> 'array'
                or jsonb_array_length(v_item->'evidence') not between 1 and 6
                or v_item->>'source_verified' is distinct from 'true'
                or v_item->>'review_required' is distinct from 'true'
                or v_item->>'document_id' is distinct from v_run.document_id::text
                or v_item->>'job_id' is distinct from p_job_id::text then
                raise exception 'Invalid condition evidence';
            end if;
            for v_evidence in select value from jsonb_array_elements(v_item->'evidence') loop
                v_page := (v_evidence->>'page')::integer;
                v_start := (v_evidence->>'start')::integer;
                v_end := (v_evidence->>'end')::integer;
                v_quote := v_evidence->>'quote';
                if v_page not between 1 and 200 or v_start < 0 or v_end <= v_start
                    or length(v_quote) < 12 or v_end - v_start <> length(v_quote)
                    or coalesce(length(v_evidence->>'passage_id'), 0) = 0
                    or not exists (
                        select 1 from public.document_pages p
                        where p.document_id = v_run.document_id
                          and p.owner_id = p_owner_id and p.page_number = v_page
                          and v_end <= length(p.text)
                          and substr(p.text, v_start + 1, v_end - v_start) = v_quote
                    ) then
                    raise exception 'Unverified condition quotation';
                end if;
            end loop;
            insert into public.claim_conditions
                (job_id, id, owner_id, policy_id, document_id, payload)
                values (p_job_id, v_item->>'id', p_owner_id, v_run.policy_id,
                        v_run.document_id, v_item);
        end loop;
    elsif jsonb_array_length(p_items) <> 0 then
        raise exception 'Failed run cannot contain conditions';
    end if;
    update public.claim_condition_runs
        set analysis_state = case when p_incomplete or p_error_code is not null
                                  then 'incomplete' else 'complete' end,
            warning = case when p_incomplete or p_error_code is not null
                           then p_warning else null end,
            rejected_candidate_count = p_rejected_count, updated_at = now()
        where job_id = p_job_id and owner_id = p_owner_id;
    update public.analysis_jobs
        set status = case when p_error_code is null then 'needs_review' else 'failed' end,
            stage = 'verifying',
            message = case when p_error_code is null
                           then coalesce(p_warning, 'Source-backed conditions need review.')
                           else 'Condition extraction did not complete.' end,
            error_code = p_error_code, updated_at = now()
        where id = p_job_id and owner_id = p_owner_id;
end;
$$;

revoke all on function public.start_condition_discovery(uuid,uuid,uuid)
    from public, anon, authenticated;
revoke all on function public.mark_condition_processing(uuid,uuid)
    from public, anon, authenticated;
revoke all on function public.finish_condition_discovery(
    uuid,uuid,jsonb,boolean,text,integer,text) from public, anon, authenticated;
grant execute on function public.start_condition_discovery(uuid,uuid,uuid) to service_role;
grant execute on function public.mark_condition_processing(uuid,uuid) to service_role;
grant execute on function public.finish_condition_discovery(
    uuid,uuid,jsonb,boolean,text,integer,text) to service_role;

notify pgrst, 'reload schema';
commit;
