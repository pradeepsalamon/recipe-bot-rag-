# Support drill - "the dairy-free swap that wasn't"

Complaint given to the finder, word for word: *"Someone said it recommended a dairy-free substitution that wasn't dairy-free, sometime last week."*

Times come from `drill.py` (clock starts on `start`, stops on `found`); the slice is
read from `logs/search_history.jsonl`, i.e. the first `logq.py find` whose results
contained the planted trace. Correctness is checked against a sha256 the squadmate's
`plant` stored, so the finder never sees the answer key.

| Drill | Finder | Timed by | Log schema | Time-to-find | Slice that found it | Correct |
|---|---|---|---|---|---|---|
| 1 | rehearsal (Claude, tooling check) | nobody - not a timed drill | v1 | **00:08** | time, input_type, text(both) | yes |

## Drill 1 - 00:08

- Found trace: `d125333e-1309-4adf-a43c-5eea52988a25`
- Winning search: `python logq.py find --since 8d --input-type dietary_swap,swap --text dairy`
- Searches made: 1

  1. `python logq.py find --since 8d --input-type dietary_swap,swap --text dairy` -> 1 matches
