# Domain Docs

说明 engineering skills 在探索代码库时应如何读取本仓库的 domain documentation。

## Before exploring, read these

- 根目录的 **`CONTEXT.md`**，或者
- 如果存在根目录 **`CONTEXT-MAP.md`**，则优先读取它，再按它的指引读取相关 context 的 `CONTEXT.md`
- **`docs/adr/`** 中与当前改动区域相关的 ADR；如果是 multi-context 仓库，也要检查 `src/<context>/docs/adr/` 下的 context-scoped 决策

如果这些文件不存在，**proceed silently**。不要专门提示缺失，也不要主动建议先创建。`/domain-modeling` skill 会在真正需要沉淀术语或决策时再创建它们。

## File structure

Single-context 仓库（大多数仓库）：

```text
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

Multi-context 仓库（根目录存在 `CONTEXT-MAP.md`）：

```text
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← system-wide decisions
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← context-specific decisions
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## Use the glossary's vocabulary

当输出中需要引用某个 domain concept 时，例如 issue 标题、重构提案、问题假设、测试命名，优先使用 `CONTEXT.md` 中定义过的术语，不要随意换成别的同义词。

如果你需要的概念还没有出现在 glossary 中，这通常说明两种情况之一：
1. 你正在引入项目里并不使用的语言，需要重新判断
2. 这里确实缺少一个术语定义，可以后续交给 `/domain-modeling` 补齐

## Flag ADR conflicts

如果你的输出与已有 ADR 冲突，要显式指出，而不是静默覆盖，例如：

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_
