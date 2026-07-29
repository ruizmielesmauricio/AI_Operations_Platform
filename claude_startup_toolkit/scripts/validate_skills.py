from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
skills_root = root / ".claude" / "skills"
errors = []
count = 0

for skill_file in sorted(skills_root.glob("*/SKILL.md")):
    count += 1
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        errors.append(f"{skill_file}: missing YAML front matter")
        continue
    parts = text.split("---", 2)
    if len(parts) < 3:
        errors.append(f"{skill_file}: malformed YAML front matter")
        continue
    front = parts[1]
    name_match = re.search(r"^name:\s*(.+)$", front, re.M)
    desc_match = re.search(r"^description:\s*(.+)$", front, re.M)
    if not name_match:
        errors.append(f"{skill_file}: missing name")
    else:
        expected = skill_file.parent.name
        actual = name_match.group(1).strip()
        if actual != expected:
            errors.append(f"{skill_file}: name '{actual}' != directory '{expected}'")
    if not desc_match:
        errors.append(f"{skill_file}: missing description")
    if len(text) < 500:
        errors.append(f"{skill_file}: unexpectedly short")

if count == 0:
    errors.append("No Skills found")

if errors:
    print("Validation failed:")
    for error in errors:
        print(f"- {error}")
    sys.exit(1)

print(f"Validated {count} Claude Skills successfully.")
