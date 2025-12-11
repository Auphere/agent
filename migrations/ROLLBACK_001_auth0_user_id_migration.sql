-- Rollback Migration: Change user_id back from VARCHAR to UUID
-- Date: 2024-12-11
-- WARNING: This will fail if there are non-UUID user_id values in the database!
--          Only run this if you need to revert before Auth0 users are created.

BEGIN;

-- 1. Rollback conversation_turns table
ALTER TABLE conversation_turns 
    ALTER COLUMN user_id TYPE UUID USING user_id::UUID;

-- 2. Rollback user_preferences table
ALTER TABLE user_preferences 
    ALTER COLUMN user_id TYPE UUID USING user_id::UUID;

-- 3. Rollback chats table
ALTER TABLE chats 
    ALTER COLUMN user_id TYPE UUID USING user_id::UUID;

COMMIT;
