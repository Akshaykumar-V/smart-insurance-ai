-- Milestone 1 only. Run against a disposable Supabase project before starting uploads.
begin;

create table public.policies (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete cascade,
    category text not null default 'other'
        check (category in ('health','life','vehicle','animal','property','other')),
    policy_type text not null default 'unknown'
        check (policy_type in ('individual','family_floater','other','unknown')),
    insurer text, product_name text, uin text, policyholder_name text,
    sum_insured_paise bigint check (sum_insured_paise >= 0),
    start_date date, end_date date,
    analysis_status text not null default 'not_started'
        check (analysis_status in ('not_started','processing','ready','needs_review','failed','unsupported')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (id, owner_id)
);

create table public.documents (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete cascade,
    policy_id uuid not null,
    type text not null check (type in ('policy_wording','policy_schedule','cis','endorsement','other')),
    file_name text not null check (char_length(file_name) between 1 and 255),
    storage_path text not null unique,
    sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
    page_count integer not null check (page_count between 1 and 200),
    processing_status text not null default 'uploaded'
        check (processing_status in ('uploaded','extracting','extracted','needs_review','failed')),
    version_label text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (policy_id, owner_id) references public.policies(id, owner_id) on delete cascade,
    unique (id, owner_id),
    unique (id, owner_id, policy_id)
);

create table public.document_pages (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete cascade,
    document_id uuid not null,
    page_number integer not null check (page_number between 1 and 200),
    text text not null,
    extraction_quality text not null
        check (extraction_quality in ('text_present','no_text','needs_review')),
    method text not null check (method = 'pymupdf'),
    foreign key (document_id, owner_id) references public.documents(id, owner_id) on delete cascade,
    unique (document_id, page_number)
);

create table public.analysis_jobs (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete cascade,
    policy_id uuid not null,
    document_id uuid not null,
    status text not null default 'queued'
        check (status in ('queued','processing','completed','failed','needs_review')),
    stage text not null default 'uploaded'
        check (stage in ('uploaded','extracting','classifying','indexing','retrieving','analyzing','verifying','completed')),
    message text, error_code text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    foreign key (policy_id, owner_id) references public.policies(id, owner_id) on delete cascade,
    foreign key (document_id, owner_id, policy_id)
        references public.documents(id, owner_id, policy_id) on delete cascade
);

create index policies_owner on public.policies(owner_id);
create index documents_owner_policy on public.documents(owner_id, policy_id);
create index document_pages_owner_document on public.document_pages(owner_id, document_id);
create index analysis_jobs_owner_policy on public.analysis_jobs(owner_id, policy_id);

alter table public.policies enable row level security;
alter table public.documents enable row level security;
alter table public.document_pages enable row level security;
alter table public.analysis_jobs enable row level security;

create policy policies_owner_only on public.policies for all to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy documents_owner_only on public.documents for all to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy pages_owner_only on public.document_pages for all to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy jobs_owner_only on public.analysis_jobs for all to authenticated
    using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);

revoke all on public.policies, public.documents, public.document_pages, public.analysis_jobs from anon;
grant select, insert, update, delete on public.policies, public.documents,
    public.document_pages, public.analysis_jobs to authenticated;

-- Atomic DB creation; the HTTP adapter compensates the preceding Storage upload on failure.
create function public.create_pdf_upload(
    p_policy_id uuid, p_document_id uuid, p_job_id uuid, p_new_policy boolean,
    p_name text, p_hint text, p_path text, p_sha256 text, p_page_count integer
) returns void language plpgsql security invoker set search_path = public, pg_temp as $$
begin
    if auth.uid() is null then raise exception 'Unauthenticated'; end if;
    if p_path <> auth.uid()::text || '/' || p_policy_id::text || '/' || p_document_id::text || '.pdf'
        then raise exception 'Invalid storage scope'; end if;
    if p_new_policy then
        insert into public.policies(id, owner_id, analysis_status)
            values (p_policy_id, auth.uid(), 'processing');
    elsif not exists (select 1 from public.policies where id = p_policy_id and owner_id = auth.uid()) then
        raise exception 'Policy not found';
    end if;
    insert into public.documents(id, owner_id, policy_id, type, file_name, storage_path, sha256, page_count)
        values (p_document_id, auth.uid(), p_policy_id, p_hint, p_name, p_path, p_sha256, p_page_count);
    insert into public.analysis_jobs(id, owner_id, policy_id, document_id, message)
        values (p_job_id, auth.uid(), p_policy_id, p_document_id, 'PDF accepted; waiting for text extraction.');
    update public.policies set analysis_status = 'processing', updated_at = now()
        where id = p_policy_id and owner_id = auth.uid();
end;
$$;

create function public.start_pdf_extraction(p_job_id uuid)
returns void language plpgsql security invoker set search_path = public, pg_temp as $$
declare v_job public.analysis_jobs;
begin
    select * into strict v_job from public.analysis_jobs
        where id = p_job_id and owner_id = auth.uid() and status = 'queued' for update;
    update public.analysis_jobs set status = 'processing', stage = 'extracting',
        message = 'Reading policy pages', updated_at = now() where id = v_job.id;
    update public.documents set processing_status = 'extracting', updated_at = now()
        where id = v_job.document_id and owner_id = auth.uid();
end;
$$;

create function public.finish_pdf_extraction(
    p_job_id uuid, p_pages jsonb, p_error_code text, p_message text
) returns void language plpgsql security invoker set search_path = public, pg_temp as $$
declare
    v_job public.analysis_jobs;
    v_count integer;
    v_review boolean;
begin
    select * into strict v_job from public.analysis_jobs
        where id = p_job_id and owner_id = auth.uid() and status in ('queued','processing') for update;
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

revoke all on function public.create_pdf_upload(uuid,uuid,uuid,boolean,text,text,text,text,integer) from public;
revoke all on function public.start_pdf_extraction(uuid) from public;
revoke all on function public.finish_pdf_extraction(uuid,jsonb,text,text) from public;
grant execute on function public.create_pdf_upload(uuid,uuid,uuid,boolean,text,text,text,text,integer) to authenticated;
grant execute on function public.start_pdf_extraction(uuid) to authenticated;
grant execute on function public.finish_pdf_extraction(uuid,jsonb,text,text) to authenticated;

insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
    values ('policy-documents', 'policy-documents', false, 20971520, array['application/pdf'])
    on conflict (id) do nothing;
do $$ begin
    if exists (select 1 from storage.buckets where id = 'policy-documents' and public) then
        raise exception 'policy-documents must be private';
    end if;
end $$;

create policy policy_pdf_upload on storage.objects for insert to authenticated
    with check (bucket_id = 'policy-documents' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy policy_pdf_read on storage.objects for select to authenticated
    using (bucket_id = 'policy-documents' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy policy_pdf_delete on storage.objects for delete to authenticated
    using (bucket_id = 'policy-documents' and (storage.foldername(name))[1] = (select auth.uid())::text);

commit;
