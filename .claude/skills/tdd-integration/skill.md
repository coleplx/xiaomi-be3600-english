---
name: tdd-integration
description: Enforce Test-Driven Development with a strict Red-Green-Refactor cycle. Auto-triggers when implementing new features or functionality. Trigger phrases include "implement", "add feature", "build", "create functionality", or any request to add new behavior. Does NOT trigger for bug fixes, documentation, or configuration changes.
---

# TDD Integration

Enforce strict Test-Driven Development using the Red-Green-Refactor cycle with dedicated subagents.

Each phase runs in an **isolated subagent context** on purpose. The test writer must not see how
the feature will be implemented, or it will subconsciously design tests around the planned code
instead of the actual requirement. Keeping phases isolated is what makes the test-first discipline real.

## Mandatory Workflow

Every new feature MUST follow this strict 3-phase cycle. Do NOT skip phases.

### Phase 1: RED - Write Failing Test

🔴 RED PHASE: Delegating to tdd-test-writer...

Invoke the `tdd-test-writer` subagent with:
- Feature requirement from user request
- Expected behavior to test

The subagent returns:
- Test file path
- Failure output confirming the test fails
- Summary of what the test verifies

**Do NOT proceed to the Green phase until test failure is confirmed.**

### Phase 2: GREEN - Make It Pass

🟢 GREEN PHASE: Delegating to tdd-implementer...

Invoke the `tdd-implementer` subagent with:
- Test file path from the RED phase
- Feature requirement context

The subagent returns:
- Files modified
- Success output confirming the test passes
- Implementation summary

**Do NOT proceed to the Refactor phase until the test passes.**

### Phase 3: REFACTOR - Improve

🔵 REFACTOR PHASE: Delegating to tdd-refactorer...

Invoke the `tdd-refactorer` subagent with:
- Test file path
- Implementation files from the GREEN phase

The subagent returns either:
- Changes made + test success output, OR
- "No refactoring needed" with reasoning

**Cycle complete when the refactor phase returns.**

## Multiple Features

Complete the full cycle for EACH feature before starting the next:

```
Feature 1: 🔴 → 🟢 → 🔵 ✓
Feature 2: 🔴 → 🟢 → 🔵 ✓
Feature 3: 🔴 → 🟢 → 🔵 ✓
```

## Phase Violations

Never:
- Write implementation before the test
- Proceed to Green without seeing Red fail
- Skip Refactor evaluation
- Start a new feature before completing the current cycle
