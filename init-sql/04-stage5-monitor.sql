USE sim_workspace;

CREATE TABLE IF NOT EXISTS monitor_job (
    id INT AUTO_INCREMENT PRIMARY KEY,
    topology_id INT NOT NULL,
    job_type ENUM('collection', 'inspection') NOT NULL,
    trigger_mode ENUM('manual', 'scheduled') NOT NULL,
    status ENUM('pending', 'running', 'success', 'failed') NOT NULL DEFAULT 'pending',
    triggered_by INT NULL,
    device_count INT DEFAULT 0,
    success_count INT DEFAULT 0,
    failure_count INT DEFAULT 0,
    summary_json TEXT NULL,
    report_json TEXT NULL,
    error_message TEXT NULL,
    started_at DATETIME NULL,
    finished_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_monitor_job_topology FOREIGN KEY (topology_id) REFERENCES topology(id),
    CONSTRAINT fk_monitor_job_user FOREIGN KEY (triggered_by) REFERENCES user(id),
    INDEX ix_monitor_job_topology (topology_id),
    INDEX ix_monitor_job_kind (job_type),
    INDEX ix_monitor_job_status (status)
) ENGINE=InnoDB;
