-- Read-only deployment audit. Run as postgres in the disposable project's SQL Editor
-- AFTER both migrations. This does not replace the two-user HTTP integration test.
begin transaction read only;
do $$
declare
    t text;
    f regprocedure;
begin
    foreach t in array array['policies','documents','document_pages','analysis_jobs'] loop
        if not exists (select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relname = t and c.relrowsecurity) then
            raise exception 'Missing table or disabled RLS: %', t;
        end if;
        if has_table_privilege('anon', 'public.' || t, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
            or has_table_privilege('authenticated', 'public.' || t, 'TRUNCATE,TRIGGER,REFERENCES') then
            raise exception 'Unexpected table grants: %', t;
        end if;
        if not (has_table_privilege('authenticated', 'public.' || t, 'SELECT')
            and has_table_privilege('authenticated', 'public.' || t, 'INSERT')
            and has_table_privilege('authenticated', 'public.' || t, 'UPDATE')
            and has_table_privilege('authenticated', 'public.' || t, 'DELETE')) then
            raise exception 'Missing authenticated CRUD grants: %', t;
        end if;
        if (select count(*) from pg_policies where schemaname = 'public' and tablename = t) <> 1 then
            raise exception 'Expected exactly one owner policy: %', t;
        end if;
    end loop;
    foreach f in array array[
        'public.create_pdf_upload(uuid,uuid,uuid,boolean,text,text,text,text,integer)'::regprocedure,
        'public.start_pdf_extraction(uuid)'::regprocedure,
        'public.finish_pdf_extraction(uuid,jsonb,text,text)'::regprocedure
    ] loop
        if has_function_privilege('anon', f, 'EXECUTE')
            or not has_function_privilege('authenticated', f, 'EXECUTE')
            or (select prosecdef from pg_proc where oid = f) then
            raise exception 'Unexpected RPC privileges/security mode: %', f;
        end if;
    end loop;
    if not exists (select 1 from storage.buckets where id = 'policy-documents'
        and public = false and file_size_limit = 20971520
        and allowed_mime_types = array['application/pdf']::text[]) then
        raise exception 'Missing or incorrectly configured document bucket';
    end if;
    if not (select relrowsecurity from pg_class where oid = 'storage.objects'::regclass) then
        raise exception 'Storage RLS is disabled';
    end if;
    -- This strict count is intentional for a fresh disposable project. Additional
    -- permissive policies can OR with ours and defeat isolation; review them first.
    if (select count(*) from pg_policies where schemaname = 'storage' and tablename = 'objects') <> 3 then
        raise exception 'Expected exactly three Storage policies; review additional/missing policies';
    end if;
end $$;

-- Inspect definitions too: counts alone do not prove policy predicates are correct.
select schemaname, tablename, policyname, roles, cmd, qual, with_check
from pg_policies where (schemaname = 'public' and tablename in
    ('policies','documents','document_pages','analysis_jobs'))
    or (schemaname = 'storage' and tablename = 'objects')
order by schemaname, tablename, policyname;

select conrelid::regclass as table_name, conname, pg_get_constraintdef(oid) as definition
from pg_constraint where conrelid in ('public.policies'::regclass, 'public.documents'::regclass,
    'public.document_pages'::regclass, 'public.analysis_jobs'::regclass)
order by table_name, conname;
rollback;
