# Security Policy

## Reporting a Vulnerability

If you discover a security issue in any tool in this repo, please report it privately rather than opening a public issue.

**How to report:**

- **Preferred**: GitHub's [private vulnerability reporting](https://github.com/christophecapel/claude-mechanisms-tools/security/advisories/new)
- **Alternative**: DM [@christophecapel](https://github.com/christophecapel) on GitHub

Include:

- A description of the vulnerability
- The tool / hook / skill affected
- Steps to reproduce
- Potential impact
- Suggested mitigation if you have one

## Response timeline

- **Acknowledgment**: within 7 days
- **Initial assessment**: within 14 days
- **Fix or mitigation**: aimed for 90 days from acknowledgment (responsible-disclosure default)

## Scope

This policy covers tools in this repo: hooks (`hooks/`), skills (`skills/`), shared libraries (`lib/`), and install scripts.

It does NOT cover:

- Third-party tools the hooks invoke (`gh`, `git`, `python3`, `jq`)
- Claude Code itself (report via [Anthropic's security channels](https://www.anthropic.com/security))
- User configurations in `~/.claude/settings.json` (operational, not project-side)

## Disclosure

After a fix ships, the vulnerability is disclosed via:

- A GitHub Security Advisory
- A note in `CHANGELOG.md`
- The reporter is credited (with permission) in the advisory and changelog

No bug bounty program — this is a personal-scale project. Reports are appreciated regardless.
