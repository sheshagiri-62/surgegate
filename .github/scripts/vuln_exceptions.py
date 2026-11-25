"""Print the CVE ids in .trivyignore.yaml whose expired_at is today or later (one per line).

Used by the ECR scan gate so it honours the same exceptions as Trivy. No PyYAML on purpose
(not guaranteed on the runner): the file's simple "- id: / expired_at:" layout is parsed
line by line. An entry without expired_at is NOT accepted (every exception must expire).
"""

import re
import sys
from datetime import date


def accepted(text: str, today: date) -> list[str]:
    out, cur = [], {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].rstrip()
        if m := re.match(r"\s*-\s*id:\s*(\S+)", line):
            if cur:
                out.append(cur)
            cur = {"id": m.group(1).strip("\"'")}
        elif m := re.match(r"\s*expired_at:\s*(\S+)", line):
            cur["expired_at"] = m.group(1).strip("\"'")
    if cur:
        out.append(cur)
    return [
        e["id"] for e in out if "expired_at" in e and date.fromisoformat(e["expired_at"]) >= today
    ]


if __name__ == "__main__":
    print("\n".join(accepted(open(sys.argv[1], encoding="utf-8").read(), date.today())))
