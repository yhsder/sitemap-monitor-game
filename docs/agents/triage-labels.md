# Triage Labels

这些 skills 使用 5 个固定的 canonical triage roles。这个文件用于把这些 roles 映射到本仓库 issue tracker 中实际使用的 label 字符串。

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | 维护者需要先评估这个 issue               |
| `needs-info`               | `needs-info`         | 等待 reporter 补充更多信息               |
| `ready-for-agent`          | `ready-for-agent`    | 规格已完整，可以直接交给 AFK agent       |
| `ready-for-human`          | `ready-for-human`    | 需要人工实现                             |
| `wontfix`                  | `wontfix`            | 不会处理                                 |

当某个 skill 提到某个 role 时，例如 “apply the AFK-ready triage label”，就使用这张表右侧对应的 label 字符串。

如果以后你修改了自己的 label vocabulary，只需要更新右侧这一列。
