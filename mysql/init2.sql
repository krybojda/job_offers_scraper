ALTER TABLE jobs
    ADD COLUMN missed_count INT UNSIGNED NOT NULL DEFAULT 0 AFTER is_active,
    ADD COLUMN work_type VARCHAR(100) DEFAULT NULL AFTER work_mode,
    ADD COLUMN experience_level VARCHAR(100) DEFAULT NULL AFTER work_type,
    ADD COLUMN contract_type VARCHAR(255) DEFAULT NULL AFTER experience_level,
    ADD COLUMN job_description LONGTEXT DEFAULT NULL AFTER salary,
    ADD COLUMN tech_stack LONGTEXT DEFAULT NULL AFTER job_description,
    ADD COLUMN office_location TEXT DEFAULT NULL AFTER tech_stack,
    ADD COLUMN about_company LONGTEXT DEFAULT NULL AFTER office_location,
    ADD COLUMN expires_text VARCHAR(100) DEFAULT NULL AFTER published_at,
    ADD COLUMN expires_at DATETIME DEFAULT NULL AFTER expires_text,
    ADD COLUMN details_scraped_at DATETIME DEFAULT NULL AFTER expires_at;