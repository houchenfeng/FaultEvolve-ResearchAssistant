# E0 版本差异

`BLOCKED: 需要 NAS 只读副本 /home/hcf/nas_hcf_data/.../work/code_aligned（当前 Cloud Agent 环境不可访问）。`

本地钉住提交：实施时以 `git rev-parse HEAD` 为准。工作树应在记录前保持干净。

## 受保护文件

- `tests/test_hdd_protected_files.py` 应在本地通过。
- NAS `benchmark/hdd_mvp/data` 符号链接 realpath：**未核对（BLOCKED）**。

## 差异清单

待 NAS 可读后按计划 §3.2 填写迁移/拒绝/未知分类。
