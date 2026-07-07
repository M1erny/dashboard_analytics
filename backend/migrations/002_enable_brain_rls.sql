-- Lock public Investment Brain tables behind Row-Level Security.
-- The app backend connects with the private Postgres role; browser clients should
-- not be able to read or mutate these tables through the Supabase public API.

ALTER TABLE IF EXISTS public.memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.ideas ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.theses ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.brain_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.brain_index ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM authenticated;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM authenticated;
    END IF;
END $$;
