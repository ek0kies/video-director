# Normalization Plan

## Requirement Summary

The project has working runtime pieces, but the repository surface is not yet clean enough for repeatable Skill use and public sharing. This pass focuses on repository hygiene, naming boundaries, and command-entry consistency.

## Scope

| Area | Action |
| --- | --- |
| Governance | Add project `AGENTS.md`, architecture, and decision records |
| Git | Initialize the current directory as a Git repository |
| Naming | Use `Video Director` for user-facing text and runtime module naming |
| Entrypoints | Keep Python router as the single public command owner |
| Dependencies | Keep root `pyproject.toml` as dependency source |
| Config templates | Treat committed JSON as internal Agent/runtime scaffolding |
| Generated files | Keep local demo/config/output artifacts out of default source tracking |

## Non-goals

| Area | Reason |
| --- | --- |
| Add new dependencies | Not required for normalization |
| Add cloud/TTS/avatar behavior | Outside contest-safe baseline |
| Publish or push repository | Requires remote URL and user confirmation |

## Plan

| Step | Files | Expected result | Verification |
| --- | --- | --- | --- |
| Add governance docs | `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` | Future agents have stable rules | Read docs and check paths |
| Tighten ignores | `.gitignore` | Local generated state is excluded | `git status --short` |
| Remove legacy wrappers | compatibility shell scripts and helper CLIs | Public surface is only router plus OS launchers | Search old entrypoints |
| Flatten runtime directory | `runtime/`, launcher imports, docs | No nested runtime package remains | Search old runtime names |
| Move config templates | `runtime/templates/` | Users are not exposed to example config files as setup steps | Search old template paths |
| Rename user-facing text | `runtime/doctor.py`, runtime helpers, docs | Public messages say Video Director | Command output inspection |
| Remove duplicate dependency source | runtime-level pyproject removal | Root dependency source is authoritative | `find . -name pyproject.toml` |
| Clean template/demo residue | `runtime/templates/*.template.json`, `demo/contest/*` generated files | Templates no longer carry old test-topic semantics; generated demo artifacts remain local-only | Search old sample strings, run demo/doctor/dry-run/render |
