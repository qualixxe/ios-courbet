#!/usr/bin/env python3
"""Print the compiler/patch errors from the latest (or given) xnu.yml run.

The artifacts API 401s for us, and `gh` picks an invalid GH_TOKEN before the
working keyring login, so both have to be worked around.

Usage:  python research/ci-log.py [run-id]
"""
import json, os, re, subprocess, sys

REPO = 'qualixxe/ios-courbet'


def gh(*args):
    e = dict(os.environ)
    e.pop('GH_TOKEN', None)
    e.pop('GITHUB_TOKEN', None)
    return subprocess.run(['gh', '-R', REPO, *args], env=e, capture_output=True,
                          text=True, encoding='utf-8', errors='replace')


def latest_run(workflow):
    r = gh('run', 'list', '-w', workflow, '--json', 'databaseId,headSha,conclusion', '-L', '1')
    if r.returncode:
        sys.exit(r.stderr.strip())
    runs = json.loads(r.stdout)
    if not runs:
        sys.exit(f'no {workflow} runs found')
    return str(runs[0]['databaseId'])


def main():
    run_id = sys.argv[1] if len(sys.argv) > 1 else latest_run('xnu.yml')
    r = gh('run', 'view', run_id, '--json', 'conclusion,jobs')
    if r.returncode:
        sys.exit(r.stderr.strip())
    info = json.loads(r.stdout)
    failed = [j for j in info['jobs'] if j.get('conclusion') == 'failure']
    if not failed:
        print(f"run {run_id}: {info['conclusion']}, no failed job")
        return
    job = failed[0]
    print(f"run {run_id} job {job['name']} ({job['databaseId']}) {job['conclusion']}")
    log = gh('run', 'view', '--job', str(job['databaseId']), '--log')
    if log.returncode:
        sys.exit('log fetch failed: ' + log.stderr[:300])
    hits = [re.sub(r'\x1b\[[0-9;]*m', '', re.sub(r'^\S+\t\S+\t[\dT:.\-]*Z?\s*', '', l))
            for l in log.stdout.splitlines()
            if re.search(r'\berror:|corrupt patch|hunk FAILED|Error [0-9]+$', l)]
    print(f"{len(log.stdout.splitlines())} log lines, {len(hits)} error lines")
    for l in hits[:40]:
        print(l)


if __name__ == '__main__':
    main()
