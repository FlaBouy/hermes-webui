# Project Review situational awareness

Implemented September 3, 2026 for all Project Reviews, not only 26HOS-006.

## Shared turn context

Both the quick conversational lane and governed review lane receive:

- Fresh server-local date/time, weekday, timezone abbreviation and numeric UTC offset, plus UTC. This is the turn-start clock, not calendar access.
- The configured Galaxy/RAG Library root and the current review's canonical relative and absolute folder paths and ancestry.
- The indexed directory hierarchy, root folders, project child folders, and whether the project folder is present in that index.
- Index modification time and age, with explicit limits: indexed paths do not establish mount health, successful ingestion, document accuracy, or permission to approve.

The source is the same local ingestion ledger used by the Galaxy and RAG directory browser. No NAS walk, document open, extraction, or new Project Reviews folder is introduced. The parsed folder snapshot is cached by ledger path/inode/mtime/size, so an atomic watcher update invalidates the cache. The clock is never cached. Missing or malformed ledgers are reported as unavailable, not as empty corpora. Directory names are quoted data, not instructions.

Folder hierarchy output is bounded to 6,500 characters; omission counts are explicit. Root folder names and the current project binding remain separately provided. The current corpus fits completely: 136 indexed folders across six root branches. Empty or unindexed filesystem folders are not claimed as known.

## Verification

69 focused review/voice/lifecycle tests passed, including clock rollover, summer/winter timezone offsets, two different projects through both context builders, cache reuse and atomic invalidation, malformed/missing indexes, path traversal rejection, and explicit truncation.

Local runtime probe: initial context construction 4.55 ms, average repeated construction 0.51 ms over 100 calls. This is context assembly, not total response latency.

Isolated calls to the actual V6 light model (no writes to Rick's active review session), deliberately supplied with an obsolete assistant claim of no clock or directory access:

- Date/time question: 2.81 seconds; correctly answered Thursday, September 3, 2026, 3:25 AM CDT.
- Corpus/project-location question: 1.32 seconds; correctly identified `Projects/Projects - 2026/26HOS-006` under the configured Library and used indexed root folder names.

These checks establish orientation and routing only. They do not certify the OCR findings, complete the engineering review, or establish live fleet health.
