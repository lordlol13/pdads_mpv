#!/usr/bin/env python3
import subprocess
import re
import os
import sys
import time

import requests

BASE = "https://pdadsmpv-production.up.railway.app"


def get_internal_key_from_railway():
    try:
        out = subprocess.check_output(["railway", "variables", "--service", "pdads_mpv"], stderr=subprocess.DEVNULL)
        text = out.decode("utf-8", errors="replace")
    except Exception:
        return None

    for line in text.splitlines():
        if "INTERNAL_API_KEY" in line:
            # Try to parse after the box separator '│' (Unicode) or '|' (ASCII)
            if "│" in line:
                parts = line.split("│")
                if len(parts) >= 2:
                    val = parts[-1].strip()
                    if val:
                        return val
            if "|" in line:
                parts = line.split("|")
                if len(parts) >= 2:
                    val = parts[-1].strip()
                    if val:
                        return val
            # fallback: last whitespace-separated token
            tokens = line.split()
            if tokens:
                return tokens[-1].strip()
    return None


if __name__ == '__main__':
    key = os.environ.get("INTERNAL_API_KEY") or get_internal_key_from_railway()
    if not key:
        print("ERROR: INTERNAL_API_KEY not found in environment or Railway variables")
        sys.exit(2)

    url = f"{BASE}/api/admin/delete-smoke-users"
    print("Calling:", url)
    for attempt in range(1, 7):
        try:
            r = requests.post(url, headers={"X-Internal-Api-Key": key}, timeout=10)
            print("Attempt", attempt, "status", r.status_code)
            print(r.text)
            if r.status_code == 200:
                print("Done")
                sys.exit(0)
        except Exception as exc:
            print("Attempt", attempt, "error", exc)
        time.sleep(5)

    print("Failed to call admin endpoint: endpoint may not be deployed yet or key is invalid")
    sys.exit(1)
