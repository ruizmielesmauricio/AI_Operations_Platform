# Installation

## A. Add to an existing repository

Copy `.claude/`, `docs/`, and `scripts/` into the repository root. Merge the supplied root `CLAUDE.md` with any existing one.

macOS/Linux example:

```bash
cp -R .claude /path/to/your-saas/
cp -R docs /path/to/your-saas/
cp -R scripts /path/to/your-saas/
```

Then:

```bash
cd /path/to/your-saas
python3 scripts/validate_skills.py
git status
git add .claude CLAUDE.md docs scripts
git commit -m "Add Claude engineering skills"
git push
claude
```

## B. Use in GitHub Codespaces

Upload/copy the folders into the repository, commit them, open a Codespace at repository root, and launch Claude Code there.

## C. Verify discovery

Inside Claude Code:

```text
What project skills are available?
```

Then test:

```text
/saas-database-architect review the repository database architecture without editing files.
```

## D. Safe first session

```text
Read CLAUDE.md and all accepted ADRs. Summarise the current architecture,
identify contradictions, and recommend which Skills should be used for the
next milestone. Do not modify files.
```
