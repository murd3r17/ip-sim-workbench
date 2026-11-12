-- 初始化数据库
CREATE DATABASE IF NOT EXISTS sim_workspace CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE sim_workspace;

-- 用户表
CREATE TABLE IF NOT EXISTS user (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    hashed_password VARCHAR(256) NOT NULL,
    display_name VARCHAR(128),
    role ENUM('admin', 'user') NOT NULL DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_user_username (username)
) ENGINE=InnoDB;

-- 审计日志表
CREATE TABLE IF NOT EXISTS audit_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    username VARCHAR(64) NOT NULL,
    module VARCHAR(32) NOT NULL,
    action VARCHAR(64) NOT NULL,
    resource_type VARCHAR(64),
    resource_id VARCHAR(64),
    detail TEXT,
    ip_address VARCHAR(45),
    result VARCHAR(16) NOT NULL DEFAULT 'success',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user(id),
    INDEX ix_audit_user_time (user_id, created_at),
    INDEX ix_audit_module (module)
) ENGINE=InnoDB;

-- 拓扑表
CREATE TABLE IF NOT EXISTS topology (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    topology_type ENUM('main', 'lab') NOT NULL DEFAULT 'main',
    parent_id INT,
    owner_id INT,
    device_count INT DEFAULT 0,
    status VARCHAR(16) DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_id) REFERENCES topology(id),
    FOREIGN KEY (owner_id) REFERENCES user(id)
) ENGINE=InnoDB;

-- 设备表
CREATE TABLE IF NOT EXISTS device (
    id INT AUTO_INCREMENT PRIMARY KEY,
    hostname VARCHAR(128) NOT NULL,
    mgmt_ip VARCHAR(45) NOT NULL,
    ssh_port INT DEFAULT 22,
    device_type ENUM('router', 'switch_l2', 'switch_l3', 'firewall', 'server', 'other') NOT NULL,
    vendor ENUM('huawei', 'h3c', 'other') DEFAULT 'huawei',
    model VARCHAR(64),
    vrp_version VARCHAR(64),
    username_encrypted VARCHAR(512),
    password_encrypted VARCHAR(512),
    enable_encrypted VARCHAR(512),
    status ENUM('unknown', 'online', 'offline', 'maintenance') DEFAULT 'unknown',
    last_seen_at DATETIME,
    status_changed_at DATETIME,
    topology_id INT NOT NULL,
    network_role VARCHAR(32) DEFAULT 'access',
    notes TEXT,
    tags VARCHAR(512),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (topology_id) REFERENCES topology(id),
    INDEX ix_device_mgmt_ip (mgmt_ip),
    INDEX ix_device_topology (topology_id),
    INDEX ix_device_status (status)
) ENGINE=InnoDB;

-- 拓扑链路表
CREATE TABLE IF NOT EXISTS topology_link (
    id INT AUTO_INCREMENT PRIMARY KEY,
    topology_id INT NOT NULL,
    source_device_id INT NOT NULL,
    source_interface VARCHAR(64) NOT NULL,
    target_device_id INT NOT NULL,
    target_interface VARCHAR(64) NOT NULL,
    link_type VARCHAR(32) DEFAULT 'physical',
    bandwidth VARCHAR(32),
    status VARCHAR(16) DEFAULT 'up',
    discovery_source VARCHAR(32),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (topology_id) REFERENCES topology(id),
    FOREIGN KEY (source_device_id) REFERENCES device(id),
    FOREIGN KEY (target_device_id) REFERENCES device(id),
    INDEX ix_link_topology (topology_id)
) ENGINE=InnoDB;

-- 站点表
CREATE TABLE IF NOT EXISTS site (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    address VARCHAR(256),
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 设备组表
CREATE TABLE IF NOT EXISTS device_group (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    parent_id INT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_id) REFERENCES device_group(id)
) ENGINE=InnoDB;

-- 插入默认管理员占位记录
-- 注意：本 SQL 无法读取环境变量；真实口令由 backend/scripts/bootstrap_local*.py 写入
--       （读根 .env 的 ADMIN_USERNAME/ADMIN_PASSWORD，未配置则生成随机口令并只打印一次）。
--       历史注释提到的 POST /api/v1/auth/setup 接口并不存在（已更正）。
INSERT INTO user (username, hashed_password, display_name, role) VALUES
('admin', '$2b$04$placeholder_need_password_setup', '系统管理员', 'admin')
ON DUPLICATE KEY UPDATE username=username;
