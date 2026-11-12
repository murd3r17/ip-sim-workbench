USE sim_workspace;

ALTER TABLE topology_link
    ADD COLUMN source_type VARCHAR(32) NOT NULL DEFAULT 'baseline',
    ADD COLUMN source_ip VARCHAR(64) NULL,
    ADD COLUMN target_ip VARCHAR(64) NULL;

CREATE TABLE topology_version (
    id INT AUTO_INCREMENT PRIMARY KEY,
    topology_id INT NOT NULL,
    version INT NOT NULL,
    batch_id VARCHAR(36) NOT NULL,
    source_name VARCHAR(255) NOT NULL,
    source_type VARCHAR(32) NOT NULL DEFAULT 'excel',
    snapshot_json TEXT NOT NULL,
    summary_json TEXT,
    created_by INT,
    rollback_of_id INT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (topology_id) REFERENCES topology(id),
    FOREIGN KEY (created_by) REFERENCES user(id),
    FOREIGN KEY (rollback_of_id) REFERENCES topology_version(id),
    UNIQUE KEY uq_topology_version (topology_id, version),
    INDEX ix_topology_version_topology (topology_id, version)
) ENGINE=InnoDB;

CREATE TABLE topology_runtime_check (
    id INT AUTO_INCREMENT PRIMARY KEY,
    topology_id INT NOT NULL,
    version_id INT,
    status VARCHAR(16) NOT NULL,
    ssh_success INT DEFAULT 0,
    ssh_failed INT DEFAULT 0,
    observed_links_json TEXT NOT NULL,
    diff_json TEXT NOT NULL,
    errors_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (topology_id) REFERENCES topology(id),
    FOREIGN KEY (version_id) REFERENCES topology_version(id),
    INDEX ix_runtime_check_topology (topology_id, created_at)
) ENGINE=InnoDB;
