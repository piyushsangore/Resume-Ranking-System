# Resume Ranking System (Flask) — Full Code

This project provides:
- Student dashboard: upload resume (PDF) + CGPA input
- Company dashboard: post jobs (JD PDF) and compute candidate ranking
- Scoring rule (0–100):
  - Skills: 1 pt per skill (max 20)
  - Experience entries: 10 pts per entry (max 20)
  - Certifications: 5 pts each (max 10)
  - CGPA: 2.5 * CGPA (scale 0–10) (max 25)
  - Equivalence: similarity (0–1) scaled to 25

## Setup on macOS / Linux

1. Create and activate venv:
```bash
python3 -m venv venv
source venv/bin/activate
