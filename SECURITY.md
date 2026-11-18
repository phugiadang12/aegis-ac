# Security and responsible use

## Intended use

Aegis AC is a **defensive** learning project: a server-side anti-cheat and SOC workflow
for a game server you run yourself.

The optional lab cheat client in `redteam/` exists only to give the anti-cheat a real
opponent in a private lab:
- it only connects to loopback and private LAN addresses (enforced in code);
- it always shows an `AEGIS LAB BUILD` watermark;
- it's only built when you run its setup script.

Don't use it, or anything derived from it, on public servers, against other people, or
in any commercial game. It doesn't read memory, inject code or bypass any anti-cheat, and
it isn't meant to.

## Secrets

Keys and webhook URLs belong in `.env`, which git ignores. Start from `.env.example`.
Never commit real values. If one leaks, revoke it at the provider (Anthropic console,
Discord channel settings) and create a new one.

## Reporting a problem

If you find a security issue in Aegis AC, please report it privately through GitHub's
**Security → Report a vulnerability** on this repository, not in a public issue.
