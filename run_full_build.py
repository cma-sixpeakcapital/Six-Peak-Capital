"""
Run the full database build using content from Box.

This is a one-time build script. The content strings are injected
at runtime from the Claude Code session.
"""
import sys
import json
sys.path.insert(0, r"C:\Users\cma\Dropbox (Personal)\Claude Code")

from test_full_build import build_and_test

# Read Francis from saved tool result
francis_path = (
    r"C:\Users\cma\.claude\projects\C--Users-cma-Dropbox--Personal--Claude-Code"
    r"\5af4c53f-032e-4f94-b999-72f9681be4f2\tool-results"
    r"\toolu_01CuRZvyYoAmbnuKNXqUA9mj.json"
)
with open(francis_path, "r") as f:
    francis_content = json.load(f)[0]["text"]

# All Projects and Ramsgate content will be read from saved files
all_projects_path = r"C:\Users\cma\Dropbox (Personal)\Claude Code\_temp_all_projects.txt"
ramsgate_path = r"C:\Users\cma\Dropbox (Personal)\Claude Code\_temp_ramsgate.txt"

with open(all_projects_path, "r", encoding="utf-8") as f:
    all_projects_content = f.read()

with open(ramsgate_path, "r", encoding="utf-8") as f:
    ramsgate_content = f.read()

print(f"Content sizes: All Projects={len(all_projects_content)}, "
      f"Ramsgate={len(ramsgate_content)}, Francis={len(francis_content)}")

db = build_and_test(all_projects_content, ramsgate_content, francis_content)
