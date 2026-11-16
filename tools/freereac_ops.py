#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The public/private split of reac-lab.

The lab notebook -- dated design specs and plans, the working journal, the on-rig runbooks -- is
private and lives in the FreeREAC/freereac-ops repository. This tree keeps the README, the
licence and the captures.

  freereac_ops.py check   the public tree is clean: no Markdown file outside the kept set

One plain rule, no list of moved paths and no read of the private checkout.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# What stays public: these files, and everything under these directories.
KEEP_FILES = {'README.md', 'BUILDING.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'LICENSE', 'NOTICE',
              'captures/README.md'}
KEEP_DIRS = ('tools/', '.github/')


def belongs_in_ops(path):
    """True when <path> is lab-notebook material: Markdown outside the kept set."""
    if path in KEEP_FILES or path.startswith(KEEP_DIRS):
        return False
    return path.endswith('.md')


def git(*args, cwd=REPO):
    p = subprocess.run(['git', *args], cwd=cwd, capture_output=True)
    if p.returncode != 0:
        raise SystemExit('git %s: %s' % (' '.join(args), p.stderr.decode(errors='replace').strip()))
    return p.stdout


def check(repo=REPO, out=sys.stdout):
    """Every failure on its own line; returns the count."""
    tracked = [t for t in git('ls-files', '-z', cwd=repo).decode().split('\0') if t]
    bad = [t for t in tracked if belongs_in_ops(t)]
    for t in bad:
        print('INTERNAL %s: lab-notebook material belongs in the private repository' % t, file=out)
    print('CHECK OK' if not bad else 'CHECK FAILED %d' % len(bad), file=out)
    return len(bad)


def main(argv):
    if len(argv) >= 1 and argv[0] == 'check':
        return 1 if check() else 0
    print(__doc__.split('\n\n')[2], file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
