# Invocation examples

## Inspect one chat

```text
$chatgpt-conversation-rename Inspect the identified ChatGPT chat in Chrome.
Suggest an English title using project/topic | concrete task. Do not edit.
```

## Optimize a bounded batch

```text
$chatgpt-conversation-rename Optimize the first ten recent ChatGPT conversations,
excluding pinned chats. Freeze their exact URLs once, read sufficient context,
keep good names, and verify every changed title in the same conversation.
```

## Add research metadata

```text
Use my configured private dataset. I authorize storing titles, URLs, topic tags,
short naming rationales and verification metadata, but not conversation bodies.
After this batch, update the journal, CSV exports, graph, and configured Obsidian vault.
```

## Recover an interrupted run

```text
Resume the specified run from its original frozen list. Verify unknown saves
without submitting again. If a blocked page now loads, append a correction to
that run and refresh exports. Keep the old blocked record and any sent snapshot.
```

An invocation without a target or identifiable current conversation needs scope clarification. These examples are instructions for the user to invoke; merely reading this file does not authorize a browser action, schedule, or message.
