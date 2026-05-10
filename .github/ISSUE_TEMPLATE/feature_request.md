---
name: Feature request / new tool proposal
about: Propose a new tool or extension
title: "[feature] "
labels: feature
---

## Failure mode this prevents

<!-- What real failure does this tool catch? Behavioral rules without a structural backstop don't count. -->

## Mechanism it implements

<!-- Which mechanism(s) from claude-mechanisms does this tool implement? Link the mechanism file. If the mechanism doesn't exist yet, propose it in claude-mechanisms first. -->

## Proposed shape

<!-- Hook (Pre/PostToolUse on which matcher? SessionStart?), skill (slash command), or library? -->

## Battle-test evidence

<!-- Tools should be extracted from real use, not built speculatively. How long has this been running in your private setup? Where's the evidence it works? -->

## Decoupling

<!-- What myOS-specific (or other private) concerns need to be removed? Any env vars / .file overrides needed? -->

## Alternatives considered

<!-- What else did you try? Why didn't a behavioral rule + memory work? -->
