"""SQL helpers for Row-Level Security, used by migrations.

Every new tenant table MUST call ``enable_tenant_rls`` in its migration.
``tests/tenancy/test_rls.py`` fails if a table with an ``org_id`` column has no policy.
"""

import os

APP_ROLE = os.environ.get("DB_APP_ROLE", "vms_app")

ORG_SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"


def enable_tenant_rls(table: str, column: str = "org_id") -> list[str]:
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS tenant_isolation ON {table}",
        f"CREATE POLICY tenant_isolation ON {table} TO {APP_ROLE} "
        f"USING ({column} = {ORG_SETTING}) WITH CHECK ({column} = {ORG_SETTING})",
    ]


def grant_app_role(table: str, privileges: str = "SELECT, INSERT, UPDATE, DELETE") -> list[str]:
    return [f"GRANT {privileges} ON {table} TO {APP_ROLE}"]
