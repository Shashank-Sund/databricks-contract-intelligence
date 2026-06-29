-- ============================================================================
-- Governance recipe: column masking by group (Unity Catalog)
-- ============================================================================
-- Make sensitive columns visible to one group and REDACTED for everyone else.
-- Because the mask lives in Unity Catalog, it is enforced everywhere the data is
-- read: the Genie space, the agent, the SQL editor, dashboards. Nothing in the
-- app needs to change.
--
-- Prerequisites:
--   1. Two ACCOUNT-level groups exist (account console -> User management ->
--      Groups). UC's is_account_group_member() only sees account groups, not
--      workspace-local ones. New account groups can take a few minutes to
--      propagate before is_account_group_member() returns true.
--   2. Replace the <PLACEHOLDERS> below with your catalog/schema/table, the
--      privileged group name, and the columns to mask.
--
-- How it works: the mask function returns the real value to members of the
-- privileged group and 'REDACTED' to everyone else. You then attach it to each
-- sensitive column.
-- ============================================================================

-- 1. The mask function: full value for the privileged group, redacted otherwise.
CREATE OR REPLACE FUNCTION <CATALOG>.<SCHEMA>.mask_sensitive(val STRING)
RETURNS STRING
RETURN CASE
  WHEN is_account_group_member('<PRIVILEGED_GROUP>') THEN val
  ELSE 'REDACTED'
END;

-- Anyone querying the masked table needs to be able to run the function.
GRANT EXECUTE ON FUNCTION <CATALOG>.<SCHEMA>.mask_sensitive TO `account users`;

-- 2. Attach the mask to each sensitive column (repeat per column).
ALTER TABLE <CATALOG>.<SCHEMA>.<TABLE>
  ALTER COLUMN <SENSITIVE_COLUMN_1> SET MASK <CATALOG>.<SCHEMA>.mask_sensitive;
ALTER TABLE <CATALOG>.<SCHEMA>.<TABLE>
  ALTER COLUMN <SENSITIVE_COLUMN_2> SET MASK <CATALOG>.<SCHEMA>.mask_sensitive;

-- 3. (Optional) Grant both groups read access to the data + schema.
GRANT USE CATALOG ON CATALOG <CATALOG> TO `<PRIVILEGED_GROUP>`;
GRANT USE SCHEMA  ON SCHEMA  <CATALOG>.<SCHEMA> TO `<PRIVILEGED_GROUP>`;
GRANT SELECT      ON SCHEMA  <CATALOG>.<SCHEMA> TO `<PRIVILEGED_GROUP>`;
-- ...and the same three GRANTs for any non-privileged group that should see the
--    masked data.

-- To remove a mask later:
--   ALTER TABLE <CATALOG>.<SCHEMA>.<TABLE> ALTER COLUMN <COLUMN> DROP MASK;

-- ----------------------------------------------------------------------------
-- Worked example: see examples/healthcare-revenue-cycle/, which masks
-- member_id, patient_id, and check_eft_number on the claims table so a
-- "research analyst" group sees de-identified data while a "BI analyst" group
-- sees everything.
-- ----------------------------------------------------------------------------
