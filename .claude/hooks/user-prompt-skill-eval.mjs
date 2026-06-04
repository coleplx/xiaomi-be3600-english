#!/usr/bin/env node
// Forces Claude Code to evaluate available skills before responding.
// Injected on every prompt via the UserPromptSubmit hook (see .claude/settings.json).
//
// Why: even with a well-written skill, Claude sometimes skips evaluation and jumps
// straight to implementation. Forcing an explicit eval step raises activation
// reliability dramatically (the source article measured ~20% -> ~84%).
//
// Written in plain Node (no tsx/ts-node dependency) so it runs in any project.

import { readFileSync } from 'node:fs'
import { stdout } from 'node:process'

function main() {
  // Consume stdin (Claude Code passes prompt context in); we don't need it.
  try {
    readFileSync(0, 'utf-8')
  } catch {
    // No stdin available; safe to ignore.
  }

  const instruction = `
INSTRUCTION: MANDATORY SKILL ACTIVATION SEQUENCE

Step 1 - EVALUATE:
For each skill in <available_skills>, state: [skill-name] - YES/NO - [reason]

Step 2 - ACTIVATE:
IF any skills are YES -> Use the Skill(skill-name) tool for EACH relevant skill NOW
IF no skills are YES -> State "No skills needed" and proceed

Step 3 - IMPLEMENT:
Only after Step 2 is complete, proceed with implementation.

CRITICAL: You MUST call the Skill() tool in Step 2. Do NOT skip to implementation.
`

  stdout.write(instruction.trim())
}

main()
