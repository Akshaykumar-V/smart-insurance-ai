-- Apply after the original ingestion and security migrations.
-- A hidden/missing/ineligible job is an expected lookup miss, not P0002 / HTTP 500.
-- CREATE OR REPLACE preserves signatures and existing grants. RLS, owner filters,
-- state preconditions, row locks and SECURITY INVOKER remain unchanged.
-- Only the initial lookup uses PT404; unexpected errors still propagate normally.
begin;

create or replace function public.start_pdf_extraction(p_job_id uuid)
returns void language plpgsql security invoker set search_path = public, pg_temp as $$
declare v_job public.analysis_jobs;
begin
    select * into v_job from public.analysis_jobs
        where id = p_job_id and owner_id = auth.uid() and status = 'queued' for update;
    if not found then
        raise sqlstate 'PT404' using message = 'Job not found.';
    end if;
    update public.analysis_jobs set status = 'processing', stage = 'extracting',
        message = 'Reading policy pages', updated_at = now() where id = v_job.id;
    update public.documents set processing_status = 'extracting', updated_at = now()
        where id = v_job.document_id and owner_id = auth.uid();
end;
$$;

create or replace function public.finish_pdf_extraction(
    p_job_id uuid, p_pages jsonb, p_error_code text, p_message text
) returns void language plpgsql security invoker set search_path = public, pg_temp as $$
declare
    v_job public.analysis_jobs;
    v_count integer;
    v_review boolean;
begin
    select * into v_job from public.analysis_jobs
        where id = p_job_id and owner_id = auth.uid() and status in ('queued','processing') for update;
    if not found then
        raise sqlstate 'PT404' using message = 'Job not found.';
    end if;
    if p_error_code is null then
        select page_count into strict v_count from public.documents
            where id = v_job.document_id and owner_id = auth.uid();
        if p_pages is null or jsonb_typeof(p_pages) <> 'array' then
            raise exception 'Missing page array';
        end if;
        if jsonb_array_length(p_pages) <> v_count or exists (
            select 1 from jsonb_array_elements(p_pages) with ordinality as e(page, n)
            where (page->>'page_number')::integer is distinct from n::integer
        ) then raise exception 'Invalid page sequence'; end if;
        if (select sum(length(page->>'text')) from jsonb_array_elements(p_pages) as e(page)) > 2000000
            then raise exception 'Text limit exceeded'; end if;
        insert into public.document_pages(owner_id, document_id, page_number, text, extraction_quality, method)
            select auth.uid(), v_job.document_id, (page->>'page_number')::integer,
                page->>'text', page->>'extraction_quality', page->>'method'
            from jsonb_array_elements(p_pages) as e(page);
        select exists (select 1 from jsonb_array_elements(p_pages) as e(page)
            where page->>'extraction_quality' <> 'text_present') into v_review;
        update public.documents set processing_status = case when v_review then 'needs_review' else 'extracted' end,
            updated_at = now() where id = v_job.document_id and owner_id = auth.uid();
    else
        update public.documents set processing_status = 'failed', updated_at = now()
            where id = v_job.document_id and owner_id = auth.uid();
    end if;
    -- Extraction never claims that the deferred AI analysis has completed.
    update public.analysis_jobs set status = case when p_error_code is null then 'needs_review' else 'failed' end,
        stage = 'extracting', error_code = p_error_code, message = p_message, updated_at = now()
        where id = v_job.id and owner_id = auth.uid();
    update public.policies set analysis_status = case when p_error_code is null then 'needs_review' else 'failed' end,
        updated_at = now() where id = v_job.policy_id and owner_id = auth.uid();
end;
$$;

notify pgrst, 'reload schema';
commit;
