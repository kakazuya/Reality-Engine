# Cloud task: re-read 903 hard deck pages with Claude Haiku 5.5

Pages where the deck pipeline's first and second readings DISAGREE (under 50% of numbers in common). Folders
`cloud_batches/cloud_hard_20261015_141615/b000` ... `b075` each hold up to 12 pairs `NNNNN_image.jpg` + `NNNNN_prompt.txt`.

## Context budget (hard rule: every model call must stay under 100K tokens of context; above that Haiku bills 5x)

- You (the orchestrator) NEVER open, read or list the contents of images, prompts or answer files. You only launch agents
  and read their one-line replies. Your own context must stay small: launch agents in parallel waves of up to 10 per
  message, and do not repeat instructions back.
- One helper agent per folder, model **haiku**, with exactly this prompt:
  "Follow cloud_batches/cloud_hard_20261015_141615/AGENT_INSTRUCTIONS.md for the folder cloud_batches/cloud_hard_20261015_141615/<bNNN>. Read the pairs one at a time. Write each answer file, do not
  re-open files you already handled, do not explain. Reply with one line: how many files you wrote."
- Do not give an agent more than one folder. Do not resume or message an agent after it replies.

## Steps

1. Read `cloud_batches/cloud_hard_20261015_141615/AGENT_INSTRUCTIONS.md` once (it is short).
2. Launch the agents in waves of 10 (folders in order) until every folder has an agent.
3. When all have replied, check that every folder has a `.txt` for each image (count files with one shell command;
   do not open them). Re-launch an agent only for folders with missing answers.
4. Commit all `.txt` answer files to this branch and push. Reply with the number of answers written.
