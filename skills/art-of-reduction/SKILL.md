---
name: art-of-reduction
description: Use when simplifying or reviewing code changes. Remove concepts, not lines.
---

# Instructions

Reduce what the code makes you think about. Fewer concepts — not fewer characters.

Work on the current change set (the diff), not the whole repo.

## The four questions

Ask them in order, stop when one applies:

1. **Can this be deleted?** Unused parameters, dead branches, re-exports, flags nobody reads.
2. **Is this two things doing one job?** Merge them, or split the one that has two jobs.
3. **Can a dependency be dropped?** See "Dependencies" below.
4. **Does anything here only restate the code?** Narration comments, docs for private helpers, types the code already guarantees. Delete those. Comments that say *why* stay.

## Rules

- **Never change behavior as part of a reduction.** Same inputs, same outputs, same errors.
- **Never remove error handling, validation, or resource cleanup as "noise."** That is not noise.
- **Never inline an abstraction to shorten a function.** If a helper has a name and is used twice, it stays. Line count is not the measure; concepts are.
- **Never optimize for speed here.** Caching, indexing, and early exits add code. Do that as a separate change, driven by a profile.
- **Verify before claiming done.** Run the project's tests, or the smallest command that exercises the change, and report the result.

## Dependencies

Before adding one, in order: is it already in the project; is it in the language's standard library; can you write it in fewer lines than its own import? If none hold, say what you want to add, what it costs (install surface, transitive dependencies, update treadmill), and ask before adding it.

Some things you do not hand-roll at any line count: cryptography, authentication, date and timezone handling, parsers for real formats, TLS. Use the standard library or a maintained library.

## Report

Per file: what you removed, what you merged, what you kept and why. Finding nothing to reduce is a valid result — say so instead of inventing work.
