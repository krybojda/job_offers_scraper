CREATE DATABASE IF NOT EXISTS jobs;

USE jobs;

CREATE TABLE IF NOT EXISTS jobs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,

    portal VARCHAR(50) NOT NULL,
    source_id VARCHAR(255) NOT NULL,

    title VARCHAR(500) NOT NULL,
    company VARCHAR(255) DEFAULT NULL,
    location VARCHAR(500) DEFAULT NULL,
    work_mode VARCHAR(100) DEFAULT NULL,
    salary VARCHAR(255) DEFAULT NULL,

    url TEXT NOT NULL,
    keyword VARCHAR(255) DEFAULT NULL,

    published_at DATETIME DEFAULT NULL,

    first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    is_active TINYINT(1) NOT NULL DEFAULT 1,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),

    UNIQUE KEY uq_portal_source_id (portal, source_id),

    KEY idx_portal (portal),
    KEY idx_keyword (keyword),
    KEY idx_is_active (is_active),
    KEY idx_published_at (published_at),
    KEY idx_last_seen_at (last_seen_at)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;