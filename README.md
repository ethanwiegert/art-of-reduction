# art-of-reduction skills repo
Skills to reduce dependencies, **even the agent that runs them**.

## Install

One command to access the skills in your favorite agent/harness:

```
npx skills add ethanwiegert/art-of-reduction
```

## Goal
Reduce dependencies, and dependency on AI for your workflows.

This skill repo aims to keep code changes and projects your agents work on simple while also looking for ways to optimize the overall workflow.

While this is catered to writing code, the skills aim to mainly target how you use AI and give you the tools to improve the way you use it.

### art-of-reduction
This is the key skill that aims to force the agent into a 'state of mind' to reduce wherever possible and aim for the simple functional output.

### strong-foundation
Builds on the `art-of-reduction` skill to focus on only the goal without introducing more complexity or dependencies.

### lazy-automate
Senior dev energy that aims to automate a problem where possible so you never have to deal with it again. Targets most used tools from `tool-tracking` data when present, reducing repeated work to scripts or new skills.

### crafting-code
A skill that combines `art-of-reduction`, `strong-foundation`, and `lazy-automate` with the goal of finishing a task and leaving it in a state better than it was before (in both the work and workflow).

### tool-tracking
Sets up a local database plus a post-tool hook that records every tool call, so you can see what your agents actually spend their turns on.

### tool-dashboard
Builds a simple dashboard on top of the `tool-tracking` database to make that usage data actionable.