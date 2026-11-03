---
description: Plan a feature or change: tasks, owners, contracts, acceptance checks
argument-hint: "<feature or change>"
---

Plan this change: $ARGUMENTS

Use the `planner` agent, which follows the `task-planning` skill. When the design adds a module, endpoint, table, or dependency, also ask the `architect` agent for contracts, and for an ADR if there are real trade-offs.

Present the plan and the blocking questions to the user. Do not start implementing until the user approves.
