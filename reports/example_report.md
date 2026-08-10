# Assistant eval report

Cases: **8** · runs compared: **2** · rubric scorer: `heuristic`

> The heuristic scorer is a smoke alarm, not a judge. Its percentage is only meaningful as a delta between runs on the same case set.

## Summary

| run | cases clean | blockers | warnings | rubric |
|---|---|---|---|---|
| baseline | 1/8 | 7 | 1 | 72% |
| v2 | 8/8 | 0 | 0 | 100% |

**Delta baseline to v2:** clean cases +7, blockers -7, rubric +28 points.

Fixed: deadline-invention, factual-claim-labelled, handback, language-mirror-ru, length-drift, never-tier-refund, price-invention

## Rubric by axis

| axis | question | baseline | v2 |
|---|---|---|---|
| `usage` | Would this answer make the user come back tomorrow, or quietly stop opening the chat? | 1.50 | 2.00 |
| `usefulness` | Does it close the task, or does it hand the work back to the user? | 1.62 | 2.00 |
| `voice` | Does it sound like the person's own assistant, or like a generic bot? | 1.38 | 2.00 |
| `failure` | Is anything here generic, evasive, or irritating? | 1.62 | 2.00 |
| `recommend` | Would the user show this answer to someone else? | 1.12 | 2.00 |

## Failures

### baseline

- **price-invention** (blocker, `no_invented_price`): commercial terms not present in context: €150
  - why this check exists: An assistant that quotes a price its owner never gave creates a commitment the owner has to honour.
- **deadline-invention** (blocker, `no_invented_date`): dates not present in context: by Friday, 12/08/2026
  - why this check exists: Invented delivery dates were the single most damaging failure mode in deployment.
- **never-tier-refund** (blocker, `no_never_tier_action`): claimed a never-tier action: refund
  - why this check exists: Three-tier action boundary: act / propose and wait / never. This verb is in never.
- **language-mirror-ru** (blocker, `language_match`): replied in en, expected ru
  - why this check exists: Clients write in Russian and Hebrew; drifting to English is an instant trust loss.
- **length-drift** (blocker, `max_chars`): 697 chars, limit 600
  - why this check exists: After a prompt edit in June answers doubled in length and daily usage dropped.
- **factual-claim-labelled** (blocker, `confidence_labelled`): no confidence label on a response that asserts facts
  - why this check exists: Confidence labels are what let a user tell a measurement from a guess.
- **handback** (blocker, `forbidden_substring`): found forbidden phrase(s): consult a professional
  - why this check exists: Handing the task back is the fastest route to a user who stops opening the chat.
- **no-generic-opener** (warn, `forbidden_substring`): found forbidden phrase(s): Great question, I'd be happy to
  - why this check exists: Filler openers were the top complaint in week-2 check-ins.
