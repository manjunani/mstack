# Security

mstack skills run scripts on your machine, and the core pack installs a hook that sees every shell command before it runs. Security problems here matter, and reports are welcome.

## Reporting a problem

Report privately, not in a public issue:

1. Go to the **Security** tab of this repository.
2. Choose **Report a vulnerability**.

Include what you found, the skill or file, how to reproduce it, and what an attacker could do with it. You will get a first answer within 7 days. A fix and a note in the release are published once the problem is fixed; you are credited unless you ask not to be.

## What counts

- A script that sends data off the machine, reads credentials, or runs something the skill does not say it runs.
- A way to make the guard hook let through a command it is meant to stop, or block normal work in a way that cannot be switched off.
- Text in a skill that tells the agent to ignore the user, hide something, or act outside the skill's job.
- A path, input or file that makes a script overwrite or delete the user's data.
- A secret or personal data committed to this repository.

Out of scope: a skill starting on the wrong request (that is a normal issue: use the "Skill started at the wrong time" form), and problems in tools mstack calls, such as ffmpeg or git.

## What mstack promises, and what it does not

- Scripts use the Python standard library, take no network action unless the skill's job is the network, and never install anything.
- The guard hook in `mstack-core` matches command patterns. It is a seat belt, not a security boundary: a determined command can get past it. Switch it off with `MSTACK_GUARD=off`.
- Read a skill's scripts before you trust it. The `skill-check` skill in the core pack does a first pass for you, and says plainly that a clean result is not proof.

## How this repository is protected

- Changes reach `main` only through a reviewed pull request that passes the checks in `.github/workflows/ci.yml`.
- Secret scanning and push protection are on. The release check in CI also looks for keys, tokens, personal email addresses and home-folder paths.
- Workflows run with a read-only token, may use only GitHub's own actions pinned to exact commits, and need the maintainer's approval before they run for outside contributors.
