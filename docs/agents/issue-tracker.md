# Issue tracker: Local Markdown

本仓库的 issues 和 PRDs 使用 `.scratch/` 中的 markdown 文件管理。

## Conventions

- 每个 feature 使用一个目录：`.scratch/<feature-slug>/`
- PRD 文件路径为 `.scratch/<feature-slug>/PRD.md`
- 实现任务文件放在 `.scratch/<feature-slug>/issues/<NN>-<slug>.md`，编号从 `01` 开始
- triage state 记录在 issue 文件顶部附近的 `Status:` 行中，状态字符串见 `triage-labels.md`
- 评论和对话历史追加在文件底部的 `## Comments` 标题下

## When a skill says "publish to the issue tracker"

在 `.scratch/<feature-slug>/` 下创建新文件；如果目录不存在则一并创建。

## When a skill says "fetch the relevant ticket"

读取对应路径的文件。通常用户会直接提供文件路径或 issue 编号。
