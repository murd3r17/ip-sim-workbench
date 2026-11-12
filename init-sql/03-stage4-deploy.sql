USE sim_workspace;

CREATE TABLE IF NOT EXISTS deploy_batch (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  description TEXT NULL,
  source VARCHAR(32) NOT NULL DEFAULT 'manual',
  planned_at DATETIME NULL,
  operator_id INT NOT NULL,
  created_at DATETIME NOT NULL,
  CONSTRAINT fk_deploy_batch_operator FOREIGN KEY (operator_id) REFERENCES user(id)
) ENGINE=InnoDB;

SET @migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.columns
   WHERE table_schema = DATABASE() AND table_name = 'config_version' AND column_name = 'source') = 0,
  'ALTER TABLE config_version ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT ''post_readback''',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = IF(
  (SELECT COLUMN_TYPE FROM information_schema.columns
   WHERE table_schema = DATABASE() AND table_name = 'deploy_task' AND column_name = 'status')
   NOT LIKE '%awaiting_confirmation%',
  'ALTER TABLE deploy_task MODIFY COLUMN status ENUM(''pending'', ''awaiting_confirmation'', ''confirmed'', ''validating'', ''deploying'', ''verifying'', ''success'', ''failed'', ''rolled_back'', ''cancelled'') NOT NULL DEFAULT ''pending''',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.columns
   WHERE table_schema = DATABASE() AND table_name = 'deploy_task' AND column_name = 'batch_id') = 0,
  'ALTER TABLE deploy_task ADD COLUMN batch_id INT NULL',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.statistics
   WHERE table_schema = DATABASE() AND table_name = 'deploy_task' AND index_name = 'ix_deploy_batch') = 0,
  'CREATE INDEX ix_deploy_batch ON deploy_task(batch_id)',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.columns
   WHERE table_schema = DATABASE() AND table_name = 'deploy_task' AND column_name = 'confirmed_by') = 0,
  'ALTER TABLE deploy_task ADD COLUMN confirmed_by INT NULL',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.columns
   WHERE table_schema = DATABASE() AND table_name = 'deploy_task' AND column_name = 'confirmed_at') = 0,
  'ALTER TABLE deploy_task ADD COLUMN confirmed_at DATETIME NULL',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.columns
   WHERE table_schema = DATABASE() AND table_name = 'deploy_task' AND column_name = 'risk_confirmed_by') = 0,
  'ALTER TABLE deploy_task ADD COLUMN risk_confirmed_by INT NULL',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

SET @migration_sql = IF(
  (SELECT COUNT(*) FROM information_schema.columns
   WHERE table_schema = DATABASE() AND table_name = 'deploy_task' AND column_name = 'risk_confirmed_at') = 0,
  'ALTER TABLE deploy_task ADD COLUMN risk_confirmed_at DATETIME NULL',
  'SELECT 1'
);
PREPARE migration_stmt FROM @migration_sql;
EXECUTE migration_stmt;
DEALLOCATE PREPARE migration_stmt;

CREATE TABLE IF NOT EXISTS device_write_lock (
  device_id INT NOT NULL PRIMARY KEY,
  task_id INT NOT NULL,
  created_at DATETIME NOT NULL,
  CONSTRAINT fk_device_write_lock_device FOREIGN KEY (device_id) REFERENCES device(id),
  CONSTRAINT fk_device_write_lock_task FOREIGN KEY (task_id) REFERENCES deploy_task(id)
) ENGINE=InnoDB;
