# Documentation

Reference material for SANAD.AI. The code lives in [`apps/`](../apps) and
[`packages/`](../packages); these documents are the authority on intent.

Start with [spec/SPEC.md](spec/SPEC.md) for what the system may and may not do,
then [spec/ARCHITECTURE.md](spec/ARCHITECTURE.md) for how it is put together.

## spec/ — what the system is

| Document | Covers |
| --- | --- |
| [SPEC.md](spec/SPEC.md) | Product definition, epistemic boundaries, acceptance criteria |
| [ARCHITECTURE.md](spec/ARCHITECTURE.md) | Component map, control flow, provider adapter contract |
| [SCHEMAS.md](spec/SCHEMAS.md) | Response schema and validation-flag invariants |

## policy/ — the rules

| Document | Covers |
| --- | --- |
| [SOURCE_POLICY.md](policy/SOURCE_POLICY.md) | Source tiers, promotion rules, forbidden behaviour |
| [CREDENTIALS_AND_ACCESS.md](policy/CREDENTIALS_AND_ACCESS.md) | Credential handling and provider access |

## process/ — how work proceeds

| Document | Covers |
| --- | --- |
| [PHASE_GATE.md](process/PHASE_GATE.md) | Current phase and the gates blocking later work |
| [TEST_PLAN.md](process/TEST_PLAN.md) | Test groups and quality metrics |
| [BUILD_CHECK.md](process/BUILD_CHECK.md) | Historical build verification output |
| [HANDOFF_BUILD_CHECK.md](process/HANDOFF_BUILD_CHECK.md) | Historical handoff build output |

## integration/ — live providers

| Document | Covers |
| --- | --- |
| [LIVE_INTEGRATION_PLAN.md](integration/LIVE_INTEGRATION_PLAN.md) | Credential bring-up and go/no-go criteria |

## handoff/ — working notes

| Document | Covers |
| --- | --- |
| [WORK_HANDOFF.md](handoff/WORK_HANDOFF.md) | Non-negotiable product rules and handoff checklist |
| [WORK_PROMPT.txt](handoff/WORK_PROMPT.txt) | Task prompt given to the implementation agent |
| [TRANSFER_TO_WORK.md](handoff/TRANSFER_TO_WORK.md) | Acceptance checklist for transferring work |

> **Note:** `process/BUILD_CHECK.md` and `process/HANDOFF_BUILD_CHECK.md` are
> historical artifacts — records of a verification run made before the monorepo
> split. They are kept for provenance and are not a description of the current
> tree.
