-- =========================================================
-- Sonificación 4D Flow MRI - esquema Supabase/Postgres
-- =========================================================

create extension if not exists pgcrypto;

create table if not exists public.invite_tokens (
    id uuid primary key default gen_random_uuid(),
    token_hash text not null unique,
    is_active boolean not null default true,
    note text,
    used_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists public.responses (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    assignments jsonb not null,
    assignment_summary text[] not null,
    correct_count integer not null,
    utilidad_opinion text not null,
    aporte_opinion text not null,
    comentarios text not null default '',
    rating integer not null check (rating between 1 and 10)
);

alter table public.invite_tokens enable row level security;
alter table public.responses enable row level security;

-- Bloquea acceso directo desde clientes públicos.
drop policy if exists "deny all invite_tokens" on public.invite_tokens;
create policy "deny all invite_tokens"
on public.invite_tokens
for all
to public
using (false)
with check (false);

drop policy if exists "deny all responses" on public.responses;
create policy "deny all responses"
on public.responses
for all
to public
using (false)
with check (false);

-- =========================================================
-- RPC atómica: consume token + guarda respuesta
-- No guarda nombre, email ni identificador personal.
-- Tampoco vincula la respuesta con una identidad.
-- =========================================================
create or replace function public.submit_sonification_response(
    token_hash_input text,
    result_rows_input jsonb,
    utilidad_opinion_input text,
    aporte_opinion_input text,
    comentarios_input text,
    rating_input integer
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
    v_token invite_tokens%rowtype;
    v_correct_count integer := 0;
    v_summary text[] := '{}';
    v_row jsonb;
begin
    if rating_input < 1 or rating_input > 10 then
        return jsonb_build_object('ok', false, 'message', 'La nota debe estar entre 1 y 10.');
    end if;

    select *
    into v_token
    from invite_tokens
    where token_hash = token_hash_input
    for update;

    if not found then
        return jsonb_build_object('ok', false, 'message', 'Token inválido.');
    end if;

    if v_token.is_active is distinct from true then
        return jsonb_build_object('ok', false, 'message', 'Token deshabilitado.');
    end if;

    if v_token.used_at is not null then
        return jsonb_build_object('ok', false, 'message', 'Este link ya fue utilizado.');
    end if;

    for v_row in
        select * from jsonb_array_elements(result_rows_input)
    loop
        if coalesce((v_row ->> 'is_correct')::boolean, false) then
            v_correct_count := v_correct_count + 1;
        end if;

        v_summary := array_append(v_summary, coalesce(v_row ->> 'assignment_summary', ''));
    end loop;

    insert into responses (
        assignments,
        assignment_summary,
        correct_count,
        utilidad_opinion,
        aporte_opinion,
        comentarios,
        rating
    )
    values (
        result_rows_input,
        v_summary,
        v_correct_count,
        utilidad_opinion_input,
        aporte_opinion_input,
        coalesce(comentarios_input, ''),
        rating_input
    );

    update invite_tokens
    set used_at = now()
    where id = v_token.id;

    return jsonb_build_object('ok', true, 'message', 'saved');
end;
$$;

revoke all on function public.submit_sonification_response(
    text, jsonb, text, text, text, integer
) from public;

grant execute on function public.submit_sonification_response(
    text, jsonb, text, text, text, integer
) to anon, authenticated, service_role;
