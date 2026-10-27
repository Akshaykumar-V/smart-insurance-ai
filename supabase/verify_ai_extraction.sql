-- Read-only configuration audit after 202610260004; not a live RLS test.
begin transaction read only;
do $$
declare f regprocedure;
begin
    if not (select relrowsecurity from pg_class where oid='public.findings'::regclass)
        or has_table_privilege('anon','public.findings','SELECT,INSERT,UPDATE,DELETE')
        or has_table_privilege('authenticated','public.findings','TRUNCATE,TRIGGER,REFERENCES')
        or not (has_table_privilege('authenticated','public.findings','SELECT')
            and has_table_privilege('authenticated','public.findings','INSERT')
            and has_table_privilege('authenticated','public.findings','UPDATE')
            and has_table_privilege('authenticated','public.findings','DELETE'))
        or (select count(*) from pg_policies
            where schemaname='public' and tablename='findings') <> 1 then
        raise exception 'Unexpected findings RLS/grants';
    end if;
    foreach f in array array[
        'public.prepare_pdf_analysis(uuid,jsonb)'::regprocedure,
        'public.get_analysis_document(uuid)'::regprocedure,
        'public.finish_pdf_analysis(uuid,jsonb,text,text)'::regprocedure
    ] loop
        if has_function_privilege('anon',f,'EXECUTE')
            or not has_function_privilege('authenticated',f,'EXECUTE')
            or (select prosecdef from pg_proc where oid=f) then
            raise exception 'Unexpected analysis RPC privileges/security mode';
        end if;
    end loop;
end $$;
select policyname, roles, cmd, qual, with_check from pg_policies
    where schemaname='public' and tablename='findings';
select conname, pg_get_constraintdef(oid) from pg_constraint
    where conrelid='public.findings'::regclass;
rollback;
