# Verified live evidence — GitHub Actions run 39799552734

Source: user-provided Actions artifact ZIP, verified 22 October 2026 (Asia/Bangkok).
Workflow: https://github.com/68056056-crypto/Sushi_Budgeteer_Shiro-Jung/actions/runs/39799552734
Live source commit: `426b48a8300dc341ad83dd0005ba638d5600304e`; configured model: `gpt-4o-mini`.

- `live-sessions.json` and `original-live-trace.md`: byte-for-byte contents of the uploaded artifact, preserved for audit.
- `verified-summary.json`: independently recounted sessions/turns/responses and matched candidate/verification IDs; includes original SHA256 hashes.
- `live-trace.md`: presentation extract regenerated from the same real events. Its historical constraints come from the same run's `build_set.arguments`, not the original mutable per-turn state lists.

Result: 5 sessions, 12/12 gold expectations passed (6 recommendations, 4 blocks, 2 clarifications); 18 actual chat turns including confirmations; 31 successful model responses; 6 successful live model-selected build/verify pairs; 0 model errors. Usage: 113459 input + 2548 output = 116007 tokens. No monetary cost is inferred without the applicable provider price.

Known artifact issue: the original runner stored references to mutable state lists, so earlier `turn.state` lists may include restrictions from later turns. The original first trace therefore reports future raw-food/context restrictions in its state block even though its actual `build_set` arguments contain only pork exclusion. The source artifact is not edited to hide this. Reporting now deep-copies snapshots; the exporter derives historical constraints from matching build/verify events. The parser also stops before “เงื่อนไขอื่นเหมือนเดิม” instead of treating this conversational phrase as food.

The live result belongs to commit 426b48a. Subsequent reporting/parser fixes are tested offline; they are not a new live API run. Gold success uses the application runner and shared validation helpers; raw final menu payloads are not fully included for independent replay. This is not a human preference study, restaurant recipe/price confirmation, or a guarantee across all possible prompts. The 42 menu allergen/price records remain unknown/unverified.
