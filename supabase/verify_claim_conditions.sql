-- Read-only configuration audit after manually applying the approved migration.
-- This does not prove live two-user isolation; test that separately.
begin transaction read only;
do $$
declare table_name text;
        function_name regprocedure;
begin
    foreach table_name in array array['claim_condition_runs', 'claim_conditions'] loop
        if not (select relrowsecurity from pg_class
                where oid = ('public.' || table_name)::regclass)
            or has_table_privilege('anon', 'public.' || table_name,
                'SELECT,INSERT,UPDATE,DELETE')
            or not has_table_privilege('authenticated', 'public.' || table_name, 'SELECT')
            or has_table_privilege('authenticated', 'public.' || table_name,
                'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER,REFERENCES')
            or not (has_table_privilege('service_role', 'public.' || table_name, 'SELECT')
                and has_table_privilege('service_role', 'public.' || table_name, 'INSERT')
                and has_table_privilege('service_role', 'public.' || table_name, 'UPDATE')
                and has_table_privilege('service_role', 'public.' || table_name, 'DELETE'))
            or (select count(*) from pg_policies
                where schemaname = 'public' and tablename = table_name
                and cmd = 'SELECT' and roles = '{authenticated}') <> 1 then
            raise exception 'Unexpected claim condition RLS/grants for %', table_name;
        end if;
    end loop;
    foreach function_name in array array[
        'public.start_condition_discovery(uuid,uuid,uuid)'::regprocedure,
        'public.mark_condition_processing(uuid,uuid)'::regprocedure,
        'public.finish_condition_discovery(uuid,uuid,jsonb,boolean,text,integer,text)'::regprocedure
    ] loop
        if has_function_privilege('anon', function_name, 'EXECUTE')
            or has_function_privilege('authenticated', function_name, 'EXECUTE')
            or not has_function_privilege('service_role', function_name, 'EXECUTE')
            or (select prosecdef from pg_proc where oid = function_name) then
            raise exception 'Unexpected condition RPC privileges/security mode';
        end if;
    end loop;
end $$;
select tablename, policyname, roles, cmd, qual
from pg_policies
where schemaname = 'public'
  and tablename in ('claim_condition_runs', 'claim_conditions')
order by tablename, policyname;
select conrelid::regclass as table_name, conname, pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid in ('public.claim_condition_runs'::regclass,
                   'public.claim_conditions'::regclass)
order by table_name, conname;
rollback;
