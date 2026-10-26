-- Apply after 202610250001_pdf_ingestion.sql in the disposable development project.
-- Explicit grants avoid inheriting broader Supabase project defaults.
begin;

revoke all on public.policies, public.documents, public.document_pages,
    public.analysis_jobs from public, anon, authenticated;
grant select, insert, update, delete on public.policies, public.documents,
    public.document_pages, public.analysis_jobs to authenticated;

revoke all on function public.create_pdf_upload(uuid,uuid,uuid,boolean,text,text,text,text,integer)
    from public, anon, authenticated;
revoke all on function public.start_pdf_extraction(uuid) from public, anon, authenticated;
revoke all on function public.finish_pdf_extraction(uuid,jsonb,text,text)
    from public, anon, authenticated;
grant execute on function public.create_pdf_upload(uuid,uuid,uuid,boolean,text,text,text,text,integer)
    to authenticated;
grant execute on function public.start_pdf_extraction(uuid) to authenticated;
grant execute on function public.finish_pdf_extraction(uuid,jsonb,text,text) to authenticated;

-- Direct owner writes must preserve the same path invariant as the upload RPC.
alter table public.documents add constraint documents_storage_scope check (
    storage_path = owner_id::text || '/' || policy_id::text || '/' || id::text || '.pdf'
);

-- Do not silently accept a pre-existing bucket with different upload restrictions.
-- Raise and roll back instead of altering an existing bucket's configuration.
do $$ begin
    if not exists (
        select 1 from storage.buckets where id = 'policy-documents'
        and public = false and file_size_limit = 20971520
        and allowed_mime_types = array['application/pdf']::text[]
    ) then
        raise exception 'Expected private policy-documents bucket, 20 MiB limit, application/pdf only';
    end if;
end $$;

commit;
