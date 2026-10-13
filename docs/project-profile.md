# 项目档案（Bootstrap 后维护）

> 这是目标项目事实的索引，不是模板默认值。初始化 agent 必须从本仓库的源码、配置、CI、历史文档中查证填写。没有证据的字段保持 `UNKNOWN`；需要产品或权限决定的字段记录为待维护者确认。

## 身份与约定

- 项目名称 / 一句话用途：`UNKNOWN`
- 默认分支：`UNKNOWN`
- 文档语言：`UNKNOWN`（跟随项目维护者与仓库惯例）
- 时区（复盘与排期）：`UNKNOWN`
- 技术栈与受支持平台：`UNKNOWN`
- 主要运行入口与部署形态：`UNKNOWN`

## 架构与验证

- 子系统索引：见 [`subsystems/README.md`](subsystems/README.md)
- 格式化 / 静态检查命令：`UNKNOWN`
- 快速定向测试：`UNKNOWN`
- 全量测试：`UNKNOWN`
- 构建 / 打包：`UNKNOWN`
- CI 工作流与必需检查：`UNKNOWN`
- 集成/真实环境验证：`UNKNOWN`（说明凭证、隔离和可运行的安全方式）
- 已知不运行于 CI 的验证：`UNKNOWN`

## 风险与权限边界

- 敏感路径、秘密和用户数据：`UNKNOWN`
- 高风险文件/操作（如发布、迁移、权限、CI）：`UNKNOWN`
- 明确的产品/兼容性决定及其来源：`UNKNOWN`
- Agent 可执行的写入边界：`UNKNOWN`
- 是否允许直接合并、发布、部署：`UNKNOWN`；未确认时不得假定已授权。
- 外部贡献的拒收 / 升级维护者规则：见 [`contributors.md`](contributors.md)，按实际项目政策填写。

## 复盘调度与水位

- 每日复盘运行方式 / agent：`UNKNOWN`
- 运行时间 / 时区：`UNKNOWN`
- 最近完成复盘的 reviewed-through SHA：`UNKNOWN`（同时更新 `LESSONS.md` 顶部标记）
- 最后复盘日期：`UNKNOWN`
- Lesson 晋升门槛：默认 3 个不同复盘日期，见 [`LESSONS.md`](../LESSONS.md)。仅由维护者明确调整。

## 更新要求

- Bootstrap、CI/脚本或发布方式变化时，核实相关字段并更新本文件。
- 改动只写已验证事实；保留来源链接或命令路径（如 `package.json`、工作流文件、配置 schema）。
- 未知项不得因为重复被抄写成事实；被维护者确认的决定记录决策出处，并同步路由入口。
