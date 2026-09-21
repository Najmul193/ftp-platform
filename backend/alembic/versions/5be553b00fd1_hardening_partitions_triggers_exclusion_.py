"""hardening: partitions, triggers, exclusion constraints, audit chain

The DDL here is what autogenerate cannot express, and it is the part that makes
the schema enforce its own invariants rather than trusting the application:

* range partitions plus a helper that creates them ahead of time
* a trigger deriving branches.division_id, so the denormalisation cannot drift
* exclusion constraints making overlapping approved rate periods impossible
* an append-only, hash-chained audit log the app role cannot rewrite
* UNLOGGED staging, safe because it is rebuildable from the stored original

Revision ID: 2a1f5c9d8e31
Revises: c0d0ce0f0e74
"""
from typing import Sequence, Union

from alembic import op

revision: str = "2a1f5c9d8e31"
down_revision: Union[str, None] = "c0d0ce0f0e74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # btree_gist lets an exclusion constraint mix equality (product_id) with
    # range overlap (the effective period) in one constraint.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------ #
    # Partition management
    # ------------------------------------------------------------------ #
    # Monthly at pilot volume; the interval becomes daily at T2+ by calling
    # this with a one-day span. Idempotent, so the nightly maintenance job can
    # run it unconditionally.
    op.execute("""
    CREATE OR REPLACE FUNCTION ensure_ftp_partition(p_from date, p_to date)
    RETURNS text LANGUAGE plpgsql AS $$
    DECLARE
        part_name text := 'ftp_calculation_results_' || to_char(p_from, 'YYYYMM');
    BEGIN
        IF to_char(p_to, 'YYYYMM') <> to_char(p_from, 'YYYYMM') THEN
            part_name := 'ftp_calculation_results_'
                      || to_char(p_from, 'YYYYMMDD') || '_'
                      || to_char(p_to,   'YYYYMMDD');
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = part_name) THEN
            EXECUTE format(
                'CREATE TABLE %I PARTITION OF ftp_calculation_results '
                'FOR VALUES FROM (%L) TO (%L)', part_name, p_from, p_to);
        END IF;
        RETURN part_name;
    END $$;
    """)

    # Create 24 months around the seeded data so a backfill or an early
    # future-dated file never fails for want of a partition.
    op.execute("""
    DO $$
    DECLARE m date := date_trunc('month', DATE '2026-01-01');
    BEGIN
        WHILE m < DATE '2028-01-01' LOOP
            PERFORM ensure_ftp_partition(m, (m + INTERVAL '1 month')::date);
            m := (m + INTERVAL '1 month')::date;
        END LOOP;
    END $$;
    """)

    # A future-dated row must never fail the load. It lands here and raises an
    # alert instead -- see plan §15.11.
    op.execute("""
    CREATE TABLE IF NOT EXISTS ftp_calculation_results_overflow
        PARTITION OF ftp_calculation_results DEFAULT
    """)

    # ------------------------------------------------------------------ #
    # branches.division_id is derived, never supplied
    # ------------------------------------------------------------------ #
    op.execute("""
    CREATE OR REPLACE FUNCTION branches_derive_division()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        SELECT d.division_id INTO NEW.division_id
          FROM districts d WHERE d.id = NEW.district_id;
        IF NEW.division_id IS NULL THEN
            RAISE EXCEPTION 'district % has no division', NEW.district_id;
        END IF;
        RETURN NEW;
    END $$;
    """)
    op.execute("""
    CREATE TRIGGER trg_branches_derive_division
    BEFORE INSERT OR UPDATE OF district_id ON branches
    FOR EACH ROW EXECUTE FUNCTION branches_derive_division();
    """)

    # ------------------------------------------------------------------ #
    # No overlapping APPROVED rate periods
    # ------------------------------------------------------------------ #
    # Open-ended periods map effective_to NULL to 'infinity'. Only APPROVED
    # rows participate, so drafts and rejected versions may overlap freely.
    op.execute("""
    ALTER TABLE product_rate_config
      ADD CONSTRAINT product_rate_no_overlap
      EXCLUDE USING gist (
        product_id WITH =,
        daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[)') WITH &&
      ) WHERE (status = 'APPROVED');
    """)
    op.execute("""
    ALTER TABLE global_rate_config
      ADD CONSTRAINT global_rate_no_overlap
      EXCLUDE USING gist (
        daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[)') WITH &&
      ) WHERE (status = 'APPROVED');
    """)

    # ------------------------------------------------------------------ #
    # Audit log: append-only and hash-chained
    # ------------------------------------------------------------------ #
    # The chain is computed in the database, so a row cannot be inserted with a
    # forged hash by any client.
    op.execute("""
    CREATE OR REPLACE FUNCTION audit_log_chain()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE prev bytea;
    BEGIN
        SELECT row_hash INTO prev FROM audit_log ORDER BY id DESC LIMIT 1;
        NEW.prev_hash := prev;
        NEW.row_hash := digest(
            coalesce(NEW.occurred_at::text,'')   || '|' ||
            coalesce(NEW.actor_username,'')      || '|' ||
            coalesce(NEW.action,'')              || '|' ||
            coalesce(NEW.entity_type,'')         || '|' ||
            coalesce(NEW.entity_id,'')           || '|' ||
            coalesce(NEW.before::text,'')        || '|' ||
            coalesce(NEW.after::text,'')         || '|' ||
            encode(coalesce(prev, ''::bytea), 'hex'),
            'sha256');
        RETURN NEW;
    END $$;
    """)
    op.execute("""
    CREATE TRIGGER trg_audit_log_chain
    BEFORE INSERT ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_chain();
    """)

    # Verification job (plan §15.11: "audit chain verification").
    op.execute("""
    CREATE OR REPLACE FUNCTION verify_audit_chain()
    RETURNS TABLE(broken_at bigint, expected bytea, found bytea)
    LANGUAGE plpgsql AS $$
    DECLARE r record; prev bytea := NULL; calc bytea;
    BEGIN
        FOR r IN SELECT * FROM audit_log ORDER BY id LOOP
            calc := digest(
                coalesce(r.occurred_at::text,'') || '|' ||
                coalesce(r.actor_username,'')    || '|' ||
                coalesce(r.action,'')            || '|' ||
                coalesce(r.entity_type,'')       || '|' ||
                coalesce(r.entity_id,'')         || '|' ||
                coalesce(r.before::text,'')      || '|' ||
                coalesce(r.after::text,'')       || '|' ||
                encode(coalesce(prev, ''::bytea), 'hex'),
                'sha256');
            IF calc IS DISTINCT FROM r.row_hash THEN
                broken_at := r.id; expected := calc; found := r.row_hash;
                RETURN NEXT;
            END IF;
            prev := r.row_hash;
        END LOOP;
    END $$;
    """)

    # Blocks UPDATE and DELETE for every role including the owner, which a
    # REVOKE alone would not do. Retention is handled by detaching partitions,
    # never by deleting rows.
    op.execute("""
    CREATE OR REPLACE FUNCTION audit_log_immutable()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'audit_log is append-only; % is not permitted', TG_OP;
    END $$;
    """)
    op.execute("""
    CREATE TRIGGER trg_audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
    """)

    # ------------------------------------------------------------------ #
    # Staging is rebuildable, so it does not need WAL
    # ------------------------------------------------------------------ #
    op.execute("ALTER TABLE staging_account_data SET UNLOGGED")


def downgrade() -> None:
    op.execute("ALTER TABLE staging_account_data SET LOGGED")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_chain ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")
    op.execute("DROP FUNCTION IF EXISTS verify_audit_chain()")
    op.execute("DROP FUNCTION IF EXISTS audit_log_chain()")
    op.execute("ALTER TABLE global_rate_config DROP CONSTRAINT IF EXISTS global_rate_no_overlap")
    op.execute("ALTER TABLE product_rate_config DROP CONSTRAINT IF EXISTS product_rate_no_overlap")
    op.execute("DROP TRIGGER IF EXISTS trg_branches_derive_division ON branches")
    op.execute("DROP FUNCTION IF EXISTS branches_derive_division()")
    op.execute("DROP FUNCTION IF EXISTS ensure_ftp_partition(date, date)")
