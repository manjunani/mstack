# Provider notes (UNVERIFIED)

Checked: 2026-11-22. Verified: **no**. Written from memory, not from the providers' current documentation or CLI
help. Platform commands change. Before using anything here, read the provider's own CLI help (`<tool> --help`,
`<tool> <command> --help`) and use what it says. The scripts in this pack contain no provider commands.

| Platform | Where the previous deployments are listed | How a return to one is usually made |
|---|---|---|
| Vercel | The project's deployments page, or its CLI's list of deployments | Promote an earlier deployment to production; the CLI has a rollback or promote command |
| Railway | The service's deployments tab, or its CLI | Redeploy an earlier deployment from the dashboard; check the CLI help for a matching command |
| A container host | The image tags or digests the host keeps | Deploy the earlier image by digest, not by a moving tag such as `latest` |
| A git-push host | The repository's deploy history | Deploy the earlier commit; avoid rewriting the branch's history |

What to confirm in the provider's help before step 3 of the skill:

1. Does the command take an exact deployment id, or does it mean "the one before the current"? Prefer the exact id.
2. Does it also change environment variables or only the code? A return to old code with new variables can fail.
3. Does it run a build, or reuse the old build? A rebuild of old code can pull different dependencies.
4. Does it stop automatic deploys from the branch afterwards? If not, the next push brings the bad version back.
