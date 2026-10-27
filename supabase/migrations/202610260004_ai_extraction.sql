-- Milestone 3A: apply after 202610260003. No existing migration is edited.
-- MVP payload stores the existing v0.1 Finding shape; owner/document FKs stay relational.
begin;
create table public.findings (
    id uuid primary key,
    owner_id uuid not null references auth.users(id) on delete cascade,
    policy_id uuid not null,
    document_id uuid not null,
    analysis_version text not null default 'v0.1' check (analysis_version = 'v0.1'),
    payload jsonb not null check (jsonb_typeof(payload) = 'object'),
    created_at timestamptz not null default now(),
    foreign key (document_id, owner_id, policy_id)
        references public.documents(id, owner_id, policy_id) on delete cascade,
    check (payload->>'id' = id::text),
    check (payload->>'condition_type' in ('co_payment','sub_limit')),
    check (payload->>'verification_status' in ('needs_review','insufficient_evidence')),
    check (payload->>'review_required' = 'true')
);
create index findings_owner_policy on public.findings(owner_id, policy_id);
alter table public.findings enable row level security;
create policy findings_owner_only on public.findings for all to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
revoke all on public.findings from public, anon, authenticated;
grant select, insert, update, delete on public.findings to authenticated;

-- Atomically save extracted pages and keep the job nonterminal for AI.
-- This wrapper preserves the original ingestion-only RPC and its behavior.
create function public.prepare_pdf_analysis(p_job_id uuid, p_pages jsonb)
returns void language plpgsql security invoker set search_path = public, pg_temp as $$
begin
    perform public.finish_pdf_extraction(p_job_id, p_pages, null, 'PDF text extracted.');
    update public.analysis_jobs set status='processing', stage='analyzing',
        message='Extracting two supported health clause types', updated_at=now()
        where id=p_job_id and owner_id=auth.uid();
    update public.policies set analysis_status='processing', updated_at=now()
        where owner_id=auth.uid() and id=(
            select policy_id from public.analysis_jobs where id=p_job_id and owner_id=auth.uid()
        );
end;
$$;

create function public.get_analysis_document(p_job_id uuid)
returns jsonb language plpgsql security invoker set search_path = public, pg_temp as $$
declare v_job public.analysis_jobs; v_count integer;
begin
    select * into v_job from public.analysis_jobs where id=p_job_id
        and owner_id=auth.uid() and status='processing' and stage='analyzing';
    if not found then raise sqlstate 'PT404' using message='Job not found.'; end if;
    select page_count into strict v_count from public.documents
        where id=v_job.document_id and owner_id=auth.uid();
    return jsonb_build_object('document_id', v_job.document_id, 'page_count', v_count);
end;
$$;

create function public.finish_pdf_analysis(
    p_job_id uuid, p_findings jsonb, p_error_code text, p_message text
) returns void language plpgsql security invoker set search_path = public, pg_temp as $$
declare v_job public.analysis_jobs; v_item jsonb; v_text text;
begin
    select * into v_job from public.analysis_jobs where id=p_job_id
        and owner_id=auth.uid() and status='processing' and stage='analyzing' for update;
    if not found then raise sqlstate 'PT404' using message='Job not found.'; end if;
    if p_findings is null or jsonb_typeof(p_findings) <> 'array' then
        raise exception 'Expected findings array';
    end if;
    if jsonb_array_length(p_findings) > 32 then raise exception 'Too many findings'; end if;
    delete from public.findings where document_id=v_job.document_id and owner_id=auth.uid();
    if p_error_code is null then
        for v_item in select value from jsonb_array_elements(p_findings) loop
            if v_item->'source' is distinct from 'null'::jsonb then
                if v_item->'source'->>'document_id' is distinct from v_job.document_id::text then
                    raise exception 'Invalid source scope';
                end if;
                select text into strict v_text from public.document_pages
                    where document_id=v_job.document_id and owner_id=auth.uid()
                    and page_number=(v_item->'source'->>'page')::integer;
                if coalesce(length(v_item->'source'->>'quote'),0)=0
                    or position((v_item->'source'->>'quote') in v_text)=0 then
                    raise exception 'Unverified source quote';
                end if;
            elsif v_item->'rule' is distinct from 'null'::jsonb then
                raise exception 'Unsupported rule without source';
            end if;
            insert into public.findings(id, owner_id, policy_id, document_id, payload)
                values ((v_item->>'id')::uuid, auth.uid(), v_job.policy_id,
                    v_job.document_id, v_item);
        end loop;
    end if;
    update public.analysis_jobs set status='needs_review', stage='verifying',
        message=p_message, error_code=p_error_code, updated_at=now()
        where id=v_job.id and owner_id=auth.uid();
    update public.policies set analysis_status='needs_review', updated_at=now()
        where id=v_job.policy_id and owner_id=auth.uid();
end;
$$;
revoke all on function public.prepare_pdf_analysis(uuid,jsonb) from public, anon, authenticated;
revoke all on function public.get_analysis_document(uuid) from public, anon, authenticated;
revoke all on function public.finish_pdf_analysis(uuid,jsonb,text,text)
    from public, anon, authenticated;
grant execute on function public.prepare_pdf_analysis(uuid,jsonb) to authenticated;
grant execute on function public.get_analysis_document(uuid) to authenticated;
grant execute on function public.finish_pdf_analysis(uuid,jsonb,text,text) to authenticated;
notify pgrst, 'reload schema';
commit;
