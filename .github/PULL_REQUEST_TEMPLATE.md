<!-- See CONTRIBUTING.md for the full PR shape. -->

## Summary

<!-- 1-3 bullets: what the PR does and why. -->

## Implements

<!-- Which mechanism(s) does this PR implement or extend? Link the mechanism file in claude-mechanisms. -->

- Mechanism #N — [title](https://github.com/christophecapel/claude-mechanisms/blob/main/mechanisms/NN-name.md)

## Test plan

- [ ] `python3 -m unittest discover tests` passes locally
- [ ] CI matrix passes (Python 3.9–3.12)
- [ ] New / modified tests cover the failure mode the tool prevents
- [ ] Hook is silent on pass (mechanism #20)
- [ ] Hook fail-closes on unhandled exceptions

## Mechanism cross-link checklist

- [ ] Entry added/updated in `tools.yaml` with `mechanism_ids:` field
- [ ] Every `mechanism_id` resolves in `claude-mechanisms/mechanisms.yaml`
- [ ] `## Implementations` table extended in the relevant mechanism file (paired PR in `claude-mechanisms`)
- [ ] `CHANGELOG.md` entry added
- [ ] `README.md` row added in the relevant version section
- [ ] `install.md` install snippet (if a hook)
