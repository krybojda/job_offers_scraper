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
    work_type VARCHAR(100) DEFAULT NULL,
    experience_level VARCHAR(100) DEFAULT NULL,
    contract_type VARCHAR(255) DEFAULT NULL,
    salary VARCHAR(255) DEFAULT NULL,

    job_description LONGTEXT DEFAULT NULL,
    tech_stack LONGTEXT DEFAULT NULL,
    office_location TEXT DEFAULT NULL,
    about_company LONGTEXT DEFAULT NULL,

    url TEXT NOT NULL,
    keyword VARCHAR(255) DEFAULT NULL,

    published_at DATETIME DEFAULT NULL,
    expires_text VARCHAR(100) DEFAULT NULL,
    expires_at DATETIME DEFAULT NULL,

    first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    is_active TINYINT(1) NOT NULL DEFAULT 1,
    missed_count INT UNSIGNED NOT NULL DEFAULT 0,
    details_scraped_at DATETIME DEFAULT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),

    UNIQUE KEY uq_portal_source_id (portal, source_id),

    KEY idx_portal (portal),
    KEY idx_keyword (keyword),
    KEY idx_is_active (is_active),
    KEY idx_published_at (published_at),
    KEY idx_last_seen_at (last_seen_at),
    KEY idx_details_scraped_at (details_scraped_at),
    KEY idx_expires_at (expires_at)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci;
