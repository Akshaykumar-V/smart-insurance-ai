-- READ ONLY. Run in the disposable project's SQL Editor as administrator.
-- Contains no user data, tokens, URLs, object names or uploaded text.
-- Run verify_pdf_ingestion.sql separately to inspect RLS predicates/constraints.
begin transaction read only;

select r.role_name,
    has_schema_privilege(r.role_name, 'public', 'USAGE') as public_schema_usage,
    has_schema_privilege(r.role_name, 'auth', 'USAGE') as auth_schema_usage,
    has_function_privilege(r.role_name, 'auth.uid()', 'EXECUTE') as auth_uid_execute
from (values ('authenticated'), ('anon')) as r(role_name);

-- Exactly one row is expected per function. Compare argument names/types to the
-- HTTP JSON keys; overloaded signatures can cause PostgREST PGRST203 / HTTP 300.
select p.proname, p.oid::regprocedure as signature, p.proargnames as argument_names,
    pg_get_function_arguments(p.oid) as arguments,
    pg_get_function_result(p.oid) as result_type,
    p.prosecdef as security_definer, p.proconfig as function_settings,
    has_function_privilege('authenticated', p.oid, 'EXECUTE') as authenticated_execute,
    has_function_privilege('anon', p.oid, 'EXECUTE') as anon_execute
from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public' and p.proname in
    ('create_pdf_upload', 'start_pdf_extraction', 'finish_pdf_extraction')
order by p.proname, signature;

-- This returns function source, not customer data. Compare with the applied files.
select p.proname, pg_get_functiondef(p.oid) as definition
from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public' and p.proname in
    ('create_pdf_upload', 'start_pdf_extraction', 'finish_pdf_extraction')
order by p.proname;

-- Quick source indicators; the full definitions above remain authoritative.
-- After 202610260002, both job RPCs should have the PT404 guard and no STRICT
-- v_job lookup. finish's separate STRICT document lookup MUST remain unchanged.
select p.proname, p.oid::regprocedure as signature,
    lower(p.prosrc) ~ 'into[[:space:]]+strict[[:space:]]+v_job' as legacy_strict_job_lookup,
    position('PT404' in p.prosrc) > 0 as has_explicit_not_found_code
from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public' and p.proname in
    ('start_pdf_extraction', 'finish_pdf_extraction')
order by p.proname;

select table_name, column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public' and table_name in ('policies', 'documents', 'analysis_jobs')
order by table_name, ordinal_position;

select c.relname as table_name, t.tgname as trigger_name,
    pg_get_triggerdef(t.oid) as trigger_definition
from pg_trigger t join pg_class c on c.oid = t.tgrelid
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname in ('policies', 'documents', 'analysis_jobs')
and not t.tgisinternal;

select id, public, file_size_limit, allowed_mime_types
from storage.buckets where id = 'policy-documents';

select tablename, policyname, roles, cmd, qual, with_check
from pg_policies where schemaname = 'storage' and tablename = 'objects'
order by policyname;
rollback;
