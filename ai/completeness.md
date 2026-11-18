# AI evidence and candidate declarations

**Evidence status: incomplete.** The original Work chat excerpt and commit history cover only part of that session. The assessment requires complete transcripts, including rejected suggestions, failed runs and file edits.

## Known activity

- ChatGPT Work / Codex coordinated planning, coding, verification and documentation. Delegated threads inspected the repository, checked startup dependencies, implemented and verified the application, and reviewed edge cases. Known thread IDs are in [the index](session-index.csv).
- The candidate explicitly invoked the requirements interview instructions. Their two original files are preserved under [instructions](instructions). Project-specific implementation instructions are in [AGENTS.md](../AGENTS.md).
- Git commit timestamps, observed command outputs, a failed thread lookup and worker status messages appear in [the partial activity record](observed-activity.md).
- Project discussions were in Chinese and English. Preserve the original language when attaching the project-only exports.
- Earlier project discussions titled `总结面试需求` and `总结文档需求` concerned the assessment brief. Their exports are outstanding. Confirm whether either discussion contributed to planning and include each applicable session.
- Model version, exact start/end times and export paths are blank in the index wherever a native source has not supplied them. The index uses UTC for available timestamps. A missing path denotes a missing export. The initial Work session points to a partial transcript.
- Targeted searches of the local native session files and activity databases did not find the original Work project thread (`6afd70b6-50bc-8191-8392-7bfe29d2a08d`). The app's thread reader returned an error for it. Its complete export remains outstanding.

## Follow-up Codex evidence

The indexed JSONL files in [sessions](sessions) use native Codex activity. They preserve timestamps, model identifiers, project messages, tool inputs and outputs, and observed errors. The filtered worker files omit duplicated parent history. The filtered files also omit internal account and runtime records, injected system and developer content, and private reasoning. Personal profile prefixes and email addresses are narrowly redacted where present.

The follow-up parent export is a snapshot through `2026-11-18T10:29:06.353Z`, and the packaging worker export ends after its completed first turn at `2026-11-18T10:11:21.880Z`. Their remaining delivery activity falls after those cutoffs. The delivery verification worker's completed turn is indexed separately. The original Work session and any other earlier sessions without linked exports remain incomplete.

## Candidate-only confirmations before submission

- Add the complete project-only exports to `ai/sessions/` and update each index row. If the conversation export omits commands, edits or errors, attach the corresponding chronological activity record. Redact only credentials or unrelated private data with `[REDACTED: reason]`.
- Disclose any additional AI tools, chats and inline autocomplete used, with export limitations. Their use outside the observed project threads is unconfirmed.
- Section 6 independent authorship: pending confirmation by the candidate after completing all three answers personally. No declaration is made on the candidate's behalf.
