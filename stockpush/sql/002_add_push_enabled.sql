-- F51/sql/002_add_push_enabled.sql
-- 为 tb_signal_functions 添加 push_enabled 字段
-- 控制单个函数是否推送飞书预警

ALTER TABLE tb_signal_functions
    ADD COLUMN IF NOT EXISTS push_enabled BOOLEAN DEFAULT TRUE;

-- 默认所有函数都推送，需要关闭推送的函数手动设置
-- UPDATE tb_signal_functions SET push_enabled = FALSE WHERE name IN ('tf05', 'mf05');
