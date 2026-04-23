#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess
import sys
import re
import urllib.request


def run_cmd(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return p.returncode, (p.stdout or '').strip(), (p.stderr or '').strip()
    except Exception as e:
        return 1, '', str(e)


def main():
    print('--- RAILWAY SERVICES ---')
    rc, out, err = run_cmd(['railway.cmd', 'services'])
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)

    print('\n--- RAILWAY VARIABLES ---')
    rc, out, err = run_cmd(['railway.cmd', 'variables', '--service', 'pdads_mpv'])
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)

    print('\n--- LAST 1000 LOG LINES ---')
    rc, out, err = run_cmd(['railway.cmd', 'logs', '--service', 'pdads_mpv', '--limit', '1000'])
    if rc != 0:
        rc, out, err = run_cmd(['railway.cmd', 'logs', '--service', 'pdads_mpv'])
    logs = (out or '') + '\n' + (err or '')
    print(logs)

    print('\n--- FILTERED ERRORS / TASKS ---')
    error_re = re.compile(r'error|exception|traceback|failed|redis|celery|process_raw_news|recommender\.refresh_user_embedding|embedd|scheduled_ingestion', re.I)
    filtered = [l for l in logs.splitlines() if error_re.search(l)]
    if filtered:
        print('\n'.join(filtered))
    else:
        print('(no matches)')

    print('\n--- RECENT CELERY/TASK MESSAGES ---')
    task_re = re.compile(r'\bTask\b|\btasks\b|celery|worker|beat|process_raw_news', re.I)
    tasks = [l for l in logs.splitlines() if task_re.search(l)]
    if tasks:
        print('\n'.join(tasks))
    else:
        print('(no matches)')

    print('\n--- LOCAL HEALTH CHECKS ---')
    urls = ['http://localhost:8000/health', 'http://localhost:8000/api/health/ready']
    for u in urls:
        print(u)
        try:
            req = urllib.request.Request(u)
            with urllib.request.urlopen(req, timeout=5) as r:
                body = r.read().decode('utf-8', errors='replace')
                status = getattr(r, 'status', None) or r.getcode()
                print('HTTP', status)
                print(body[:4000])
        except Exception as e:
            print('ERROR', e)


if __name__ == '__main__':
    main()


