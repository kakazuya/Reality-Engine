# agy-workers: Hydrogen worker band

One above-prompt row per running agy (Gemini Hydrogen) job, next to the dsh-workers band:
`◆ agy <brief title>  <tools> tools · <steps> steps · <out> out · <cached> cached · idle <m>m · <elapsed>`.
It reads `plugins/agy-worker/runtime/jobs/<id>/job.json`, `brief.md` and `events.jsonl` every 15 s
(counts `step_update` DONE events and their `usage`; re-parses only when the log grew). Hooks only; no
model, network or tool calls. A job drops off when `exit.json` appears.

Install (user scope, once): `claude plugin install agy-workers --marketplace C:\Users\warri\Downloads\Info_Diffusion_Model`,
then `/reload-plugins`. After an edit: bump `version` in `.claude-plugin/plugin.json`, then
`claude plugin marketplace update reality-engine` and `claude plugin update agy-workers@reality-engine`.
