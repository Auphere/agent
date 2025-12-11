-- Migration: Change user_id from UUID to VARCHAR to support Auth0 IDs
-- Date: 2024-12-11
-- Description: Auth0 uses IDs like "auth0|123456" or "google-oauth2|123456" 
--              which are not UUIDs. This migration changes user_id columns 
--              to VARCHAR(255) across all tables.

BEGIN;

-- 1. Alter conversation_turns table
ALTER TABLE conversation_turns 
    ALTER COLUMN user_id TYPE VARCHAR(255);

-- 2. Alter user_preferences table
ALTER TABLE user_preferences 
    ALTER COLUMN user_id TYPE VARCHAR(255);

-- 3. Alter chats table
ALTER TABLE chats 
    ALTER COLUMN user_id TYPE VARCHAR(255);

-- Note: Indexes on user_id columns will be automatically updated

COMMIT;

-- Verification queries (run these after migration):
-- SELECT user_id, COUNT(*) FROM conversation_turns GROUP BY user_id;
-- SELECT user_id FROM user_preferences;
-- SELECT user_id, COUNT(*) FROM chats GROUP BY user_id;
