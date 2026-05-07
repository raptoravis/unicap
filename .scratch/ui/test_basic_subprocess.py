"""Pure subprocess test (no Qt) — confirm Popen + line buffering works."""

import subprocess, sys, signal

CREATE_NEW_PROCESS_GROUP = subprocess.CREATE_NEW_PROCESS_GROUP

p = subprocess.Popen(
    [sys.executable, "-u", "main.py", "--version"],
    cwd=".",
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    bufsize=1,
    text=True,
    encoding="utf-8",
    errors="replace",
    creationflags=CREATE_NEW_PROCESS_GROUP,
)

print("spawned pid=%d" % p.pid, flush=True)

assert p.stdout
for line in p.stdout:
    print("RAW:", repr(line.rstrip()), flush=True)

rc = p.wait()
print("rc=%d" % rc, flush=True)
