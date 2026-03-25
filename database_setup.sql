CREATE DATABASE IF NOT EXISTS sleep_ai;
USE sleep_ai;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) UNIQUE,
    password VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    username VARCHAR(100),
    input_data TEXT,
    result VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO users (username, password)
SELECT 'demo', 'demo123'
WHERE NOT EXISTS (
    SELECT 1 FROM users WHERE username = 'demo'
);
