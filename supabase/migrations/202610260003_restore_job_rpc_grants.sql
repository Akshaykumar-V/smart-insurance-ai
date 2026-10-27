-- Correct deployed EXECUTE privilege drift after the first three migrations.
-- No function bodies, table grants, RLS policies, or Storage settings change.
-- PUBLIC privileges are inherited by anon even without an explicit anon grant.
begin;

revoke execute on function public.create_pdf_upload(uuid,uuid,uuid,boolean,text,text,text,text,integer)
    from public, anon;
revoke execute on function public.start_pdf_extraction(uuid) from public, anon;
revoke execute on function public.finish_pdf_extraction(uuid,jsonb,text,text) from public, anon;

-- Restore only the application's existing intended authenticated execution rights.
grant execute on function public.create_pdf_upload(uuid,uuid,uuid,boolean,text,text,text,text,integer)
    to authenticated;
grant execute on function public.start_pdf_extraction(uuid) to authenticated;
grant execute on function public.finish_pdf_extraction(uuid,jsonb,text,text) to authenticated;

-- Fail atomically if inherited role privileges or a different security mode remain.
do $$
declare f regprocedure;
begin
    foreach f in array array[
        'public.create_pdf_upload(uuid,uuid,uuid,boolean,text,text,text,text,integer)'::regprocedure,
        'public.start_pdf_extraction(uuid)'::regprocedure,
        'public.finish_pdf_extraction(uuid,jsonb,text,text)'::regprocedure
    ] loop
        if has_function_privilege('anon', f, 'EXECUTE')
            or not has_function_privilege('authenticated', f, 'EXECUTE')
            or (select prosecdef from pg_proc where oid = f) then
            raise exception 'RPC privileges/security mode require investigation: %', f;
        end if;
    end loop;
end $$;

notify pgrst, 'reload schema';
commit;
