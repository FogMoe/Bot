-- Schema definition for the Telegram AI assistant platform
-- Target database: MySQL 8.0+
-- Character set: utf8mb4

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE TABLE IF NOT EXISTS subscription_plans (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(32) NOT NULL,
    name VARCHAR(64) NOT NULL,
    description TEXT NULL,
    hourly_message_limit SMALLINT UNSIGNED NOT NULL,
    monthly_price DECIMAL(10,2) NOT NULL DEFAULT 0,
    is_default TINYINT(1) NOT NULL DEFAULT 0,
    priority SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    features JSON NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_subscription_plans_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS users (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    telegram_id BIGINT UNSIGNED NOT NULL,
    username VARCHAR(32) NULL,
    first_name VARCHAR(64) NULL,
    last_name VARCHAR(64) NULL,
    language_code VARCHAR(8) NULL,
    role ENUM('user','admin','service') NOT NULL DEFAULT 'user',
    status ENUM('active','blocked','deleted','pending') NOT NULL DEFAULT 'active',
    timezone VARCHAR(64) NULL,
    last_seen_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_users_telegram_id (telegram_id),
    UNIQUE KEY uq_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_settings (
    user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    preferred_model VARCHAR(64) NULL,
    markdown_mode ENUM('auto','force_markdown','force_plain') NOT NULL DEFAULT 'auto',
    split_newlines TINYINT(1) NOT NULL DEFAULT 1,
    memory_opt_in TINYINT(1) NOT NULL DEFAULT 1,
    notification_opt_in TINYINT(1) NOT NULL DEFAULT 1,
    extra_settings JSON NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_settings_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_impressions (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    impression TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_impressions_user (user_id),
    CONSTRAINT fk_user_impressions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS subscription_cards (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(64) NOT NULL,
    plan_id BIGINT UNSIGNED NOT NULL,
    status ENUM('new','redeemed','expired','disabled') NOT NULL DEFAULT 'new',
    expires_at DATETIME NULL,
    valid_days INT UNSIGNED NULL,
    redeemed_by_user_id BIGINT UNSIGNED NULL,
    redeemed_at DATETIME NULL,
    metadata JSON NULL,
    created_by_admin_id BIGINT UNSIGNED NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_subscription_cards_code (code),
    KEY idx_subscription_cards_plan (plan_id),
    KEY idx_subscription_cards_status (status),
    CONSTRAINT fk_subscription_cards_plan FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE RESTRICT,
    CONSTRAINT fk_subscription_cards_redeemed_user FOREIGN KEY (redeemed_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT fk_subscription_cards_admin FOREIGN KEY (created_by_admin_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    plan_id BIGINT UNSIGNED NOT NULL,
    source_card_id BIGINT UNSIGNED NULL,
    status ENUM('active','cancelled','expired','pending') NOT NULL DEFAULT 'active',
    priority SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    activated_at DATETIME NULL,
    starts_at DATETIME NULL,
    expires_at DATETIME NULL,
    cancelled_at DATETIME NULL,
    notes TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_user_subscriptions_user (user_id),
    KEY idx_user_subscriptions_plan (plan_id),
    KEY idx_user_subscriptions_status (status),
    KEY idx_user_subscriptions_priority (user_id, priority),
    CONSTRAINT fk_user_subscriptions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_user_subscriptions_plan FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE RESTRICT,
    CONSTRAINT fk_user_subscriptions_card FOREIGN KEY (source_card_id) REFERENCES subscription_cards(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS usage_hourly_quota (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    window_start DATETIME NOT NULL,
    message_count INT UNSIGNED NOT NULL DEFAULT 0,
    tool_call_count INT UNSIGNED NOT NULL DEFAULT 0,
    last_reset_at DATETIME NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_usage_hourly_quota_user_window (user_id, window_start),
    CONSTRAINT fk_usage_hourly_quota_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS conversations (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    title VARCHAR(191) NULL,
    context_tokens INT UNSIGNED NOT NULL DEFAULT 0,
    status ENUM('active','archived','closed') NOT NULL DEFAULT 'active',
    memory_state ENUM('in_sync','needs_compress','compressed') NOT NULL DEFAULT 'in_sync',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_interaction_at TIMESTAMP NULL,
    KEY idx_conversations_user (user_id),
    KEY idx_conversations_status (status),
    CONSTRAINT fk_conversations_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS messages (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    conversation_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NULL,
    history JSON NOT NULL,
    total_tokens INT UNSIGNED NULL,
    message_count INT UNSIGNED NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_messages_conversation (conversation_id),
    KEY idx_messages_user (user_id),
    CONSTRAINT fk_messages_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_messages_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agent_runs (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    conversation_id BIGINT UNSIGNED NOT NULL,
    trigger_message_id BIGINT UNSIGNED NULL,
    status ENUM('running','succeeded','failed','cancelled') NOT NULL DEFAULT 'running',
    model VARCHAR(64) NULL,
    latency_ms INT UNSIGNED NULL,
    token_usage_prompt INT UNSIGNED NULL,
    token_usage_completion INT UNSIGNED NULL,
    result_summary TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    KEY idx_agent_runs_conversation (conversation_id),
    KEY idx_agent_runs_status (status),
    CONSTRAINT fk_agent_runs_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_runs_trigger_message FOREIGN KEY (trigger_message_id) REFERENCES messages(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS conversation_archives (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    conversation_id BIGINT UNSIGNED NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    summary_text MEDIUMTEXT NULL,
    history JSON NOT NULL,
    token_count INT UNSIGNED NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_conversation_archives_conversation (conversation_id),
    KEY idx_conversation_archives_user (user_id),
    CONSTRAINT fk_conversation_archives_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_conversation_archives_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS long_term_memories (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    conversation_id BIGINT UNSIGNED NULL,
    source_message_id BIGINT UNSIGNED NULL,
    memory_type ENUM('fact','preference','summary','other') NOT NULL DEFAULT 'fact',
    content MEDIUMTEXT NOT NULL,
    embedding_vector_id VARCHAR(191) NULL,
    token_estimate INT UNSIGNED NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    expires_at DATETIME NULL,
    KEY idx_long_term_memories_user (user_id),
    KEY idx_long_term_memories_conversation (conversation_id),
    CONSTRAINT fk_long_term_memories_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_long_term_memories_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL,
    CONSTRAINT fk_long_term_memories_message FOREIGN KEY (source_message_id) REFERENCES messages(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS memory_chunks (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    conversation_id BIGINT UNSIGNED NOT NULL,
    start_message_id BIGINT UNSIGNED NULL,
    end_message_id BIGINT UNSIGNED NULL,
    token_count INT UNSIGNED NOT NULL,
    state ENUM('raw','needs_compress','compressed') NOT NULL DEFAULT 'raw',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_memory_chunks_conversation (conversation_id),
    KEY idx_memory_chunks_state (state),
    CONSTRAINT fk_memory_chunks_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_memory_chunks_start_message FOREIGN KEY (start_message_id) REFERENCES messages(id) ON DELETE SET NULL,
    CONSTRAINT fk_memory_chunks_end_message FOREIGN KEY (end_message_id) REFERENCES messages(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS memory_compressions (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    memory_chunk_id BIGINT UNSIGNED NOT NULL,
    compressed_by_model VARCHAR(64) NULL,
    compressed_content MEDIUMTEXT NULL,
    compression_ratio DECIMAL(5,2) NULL,
    status ENUM('pending','succeeded','failed') NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_memory_compressions_chunk FOREIGN KEY (memory_chunk_id) REFERENCES memory_chunks(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS vector_index_snapshots (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    long_term_memory_id BIGINT UNSIGNED NOT NULL,
    provider VARCHAR(64) NOT NULL,
    vector_id VARCHAR(191) NULL,
    status ENUM('pending','synced','failed','deleted') NOT NULL DEFAULT 'pending',
    metadata JSON NULL,
    last_synced_at DATETIME NULL,
    error_message TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_vector_index_snapshot_memory FOREIGN KEY (long_term_memory_id) REFERENCES long_term_memories(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS redis_cache_hooks (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    cache_key_pattern VARCHAR(191) NOT NULL,
    purpose VARCHAR(128) NULL,
    ttl_seconds INT UNSIGNED NULL,
    schema_version VARCHAR(32) NULL,
    last_synced_at DATETIME NULL,
    notes TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_redis_cache_hooks_pattern (cache_key_pattern)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NULL,
    action_type VARCHAR(64) NOT NULL,
    payload_json JSON NULL,
    ip_address VARCHAR(64) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_audit_logs_user (user_id),
    KEY idx_audit_logs_action (action_type),
    CONSTRAINT fk_audit_logs_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;
