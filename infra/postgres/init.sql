-- Runs once when the Postgres volume is first created.
-- `vms` (POSTGRES_USER) owns the tables and runs migrations.
-- `vms_app` is what the API uses for tenant requests: no superuser, no BYPASSRLS,
-- so Row-Level Security always applies to it.
CREATE ROLE vms_app LOGIN PASSWORD 'vms_app' NOSUPERUSER NOBYPASSRLS;
GRANT CONNECT ON DATABASE vms TO vms_app;

CREATE DATABASE vms_test OWNER vms;
GRANT CONNECT ON DATABASE vms_test TO vms_app;
