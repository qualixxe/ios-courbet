#!/usr/bin/env python3
"""Print the compiler/patch errors from the latest (or given) xnu.yml run.

The artifacts API 401s for us, and `gh` picks an invalid GH_TOKEN before the
working keyring login, so both have to be worked around.

Usage:  python research/ci-log.py [run-id]          # finished run, failing job
        python research/ci-log.py [run-id] --live    # the job running right now
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
    live = '--live' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--live']
    run_id = args[0] if args else latest_run('xnu.yml')
    r = gh('run', 'view', run_id, '--json', 'status,conclusion,jobs')
    if r.returncode:
        sys.exit(r.stderr.strip())
    info = json.loads(r.stdout)
    # a run in progress has no conclusion yet: watch the job it is running now
    job = next((j for j in info['jobs'] if j.get('conclusion') == 'failure'), None)
    if job is None:
        job = next((j for j in info['jobs'] if j.get('status') != 'completed'), None)
    if job is None:
        print(f"run {run_id}: {info['conclusion']}, no failed job")
        return
    job_id = job['databaseId']
    print(f"run {run_id} job {job['name']} ({job_id}) {job.get('conclusion') or job['status']}")
    if live:
        # gh run view --log only serves completed jobs; the REST endpoint streams
        # the in-progress one, which is how you catch the error before the run dies
        log = gh('api', f'repos/{REPO}/actions/jobs/{job_id}/logs')
    else:
        log = gh('run', 'view', '--job', str(job_id), '--log')
    if log.returncode:
        sys.exit('log fetch failed: ' + log.stderr[:300])
    hits = [re.sub(r'\x1b\[[0-9;]*m', '', re.sub(r'^\S+\t\S+\t[\dT:.\-]*Z?\s*', '', l))
            for l in log.stdout.splitlines()
            if re.search(r'\berror:|corrupt patch|hunk FAILED|Error [0-9]+$', l)]
    noise = sum(1 for l in hits if 'already exists in working directory' in l or 'does not apply' in l)
    print(f"{len(log.stdout.splitlines())} log lines, {len(hits)} error lines ({noise} are blacktop's known skips)")
    for l in hits:
        if 'already exists in working directory' not in l and 'does not apply' not in l:
            print(l)


if __name__ == '__main__':
    main()
