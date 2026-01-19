# 项目概览

## 项目目标
- 监控多个站点的 sitemap 更新，发现新增 URL 并记录
- 保存每次抓取的全量快照，同时按天归档新增数据
- 在有新增时通过飞书 Webhook 发送通知

## 技术栈与架构设计
- 语言/运行时：Python（CI 使用 3.10）
- 依赖库：requests、cloudscraper、beautifulsoup4、lxml、pyyaml、gzip
- 配置驱动：`config.yaml` 定义站点列表与通知参数
- 结构：单脚本 `main.py` + 数据目录 `latest/`、`diff/`
- 自动化：GitHub Actions 定时运行并提交数据变更

## 关键业务逻辑
- `load_config` 读取 `config.yaml`，遍历 `sites` 中 `active: true` 的站点
- `process_sitemap` 请求 `sitemap_urls`，识别 gzip（magic number），按 `<urlset` 分流 `parse_xml`/`parse_txt`
- `parse_xml` 抽取 `<loc>`；`parse_txt` 按行拆分 URL
- `compare_data` 读取 `latest/<site>.json` 做差集，仅保留新增 URL
- `save_latest` 写入最新全量；`save_diff` 写入当日新增并用分隔线追加
- `send_feishu_notification` 发送飞书卡片，最多展示前 10 条新增
- `cleanup_old_data` 按保留天数清理 `diff/` 下过期日期目录

## 数据与目录结构
- `latest/<site>.json`：按行保存全量 URL（实际为文本列表，并非 JSON）
- `diff/YYYYMMDD/<site>.json`：按行保存新增 URL；同日多次运行会追加分隔线
- `diff/` 以日期目录归档；数据文件会被 CI 自动提交到仓库

## 运行与部署
- 本地运行：`python main.py`（仓库无 `requirements.txt`，需自行安装依赖）
- CI：`.github/workflows/sitemap-check.yml` 每天 UTC 22:00 运行；有变更即提交并 push（依赖 `GH_TOKEN`）

## 已知/待澄清点
- `config.yaml` 中 `storage.retention_days` 与 `storage.data_dir` 未被使用；清理逻辑读取的是顶层 `retention_days`
- `feishu.secret` 被读取但未用于签名校验
