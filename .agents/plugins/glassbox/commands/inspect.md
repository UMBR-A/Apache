---
description: Decide and inspect one browser action with a probability receipt.
argument-hint: <goal>
---

Use a connected browser tool to capture a fresh observation of the current page for the goal: `$ARGUMENTS`.

Do not infer or fabricate page controls. Exclude passwords and secrets. If no browser tool is connected, stop and ask the user to attach an observation.

Call the GlassBox `page_decide` MCP tool with the goal and observation. Then show the selected operation, selected target if any, probability receipt, and strongest alternatives. These values describe model preferences, not explanations or guarantees.

Do not execute the selected operation. The browser controller remains responsible for execution and its confirmation gates.
