#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The public/private split of reac-lab, and the one reader of the freereac-ops checkout.

The lab notebook -- dated design specs and plans, the working journal, the on-rig runbooks -- lives
in the private FreeREAC/freereac-ops repository under reac-lab/<same path>. This tree keeps the
README, the licence and the captures. tools/ops-moves.txt lists every path that moved (and the
commit it was taken from); a public file cites one by its SLUG, the path without its extension
(runbooks/rig-parked-state), never by file name, and never names a directory that moved out whole.

  freereac_ops.py check            the public tree is clean; with the ops checkout present, every
                                   moved path resolves in it
  freereac_ops.py resolve <slug>   the ops file a slug names, or OPS-ABSENT
  freereac_ops.py export <ops-checkout> [<branch>]
                                   commit the moved files, byte-identical, onto <branch> of an ops
                                   checkout (one commit on its main, or a root commit); never pushes

The ops checkout is found by one rule: $FREEREAC_OPS, else the sibling ../freereac-ops, else
absent. Absent, `check` reports OPS-ABSENT and skips that half by name; FREEREAC_REQUIRE_OPS=1
makes it fail instead (a desk or a lane that must not merge a half-done move).
"""
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOVES = 'tools/ops-moves.txt'
OPS_SUBDIR = 'reac-lab'
BRANCH = 'lane/docs-reac-lab'

# What stays public: these files, and everything under these directories.
KEEP_FILES = {'README.md', 'BUILDING.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'LICENSE', 'NOTICE',
              'captures/README.md'}
KEEP_DIRS = ('tools/', '.github/')
# The notebook: specs, plans, ADRs, journals, runbooks, notes, audits and agent tooling.
INTERNAL_DIRS = ('design-specs/', 'runbooks/', 'journal/', 'plans/', 'notes/', 'audits/', 'adr/',
                 '.claude/')
# A moved file whose BARE name is a citation too.
BARE_CITED_EXT = ('.md',)
# Files that name the moved paths by necessity.
SCAN_EXEMPT = {MOVES, 'tools/freereac_ops.py', 'tools/test_freereac_ops.py'}
CAPTURE = re.compile(r'\.(pcap(ng)?\d*|cap)$')


def belongs_in_ops(path):
    """True when <path> is lab-notebook material: it lives in freereac-ops."""
    if path in KEEP_FILES or path.startswith(KEEP_DIRS):
        return False
    return path.startswith(INTERNAL_DIRS) or path.endswith('.md')


def slug(path):
    return os.path.splitext(path)[0]


def git(*args, cwd=REPO, check=True, data=None):
    p = subprocess.run(['git', *args], cwd=cwd, capture_output=True, input=data)
    if check and p.returncode != 0:
        raise SystemExit('git %s: %s' % (' '.join(args), p.stderr.decode(errors='replace').strip()))
    return p.stdout


def read_moves(repo=REPO):
    """(base sha, [moved paths]) from tools/ops-moves.txt."""
    base, paths = None, []
    with open(os.path.join(repo, MOVES)) as f:
        for line in f:
            line = line.strip()
            if line.startswith('# base '):
                base = line.split()[2]
            elif line and not line.startswith('#'):
                paths.append(line)
    if not base:
        raise SystemExit('%s has no "# base <sha>" line' % MOVES)
    return base, paths


def ops_root(repo=REPO):
    """The freereac-ops checkout: $FREEREAC_OPS, else ../freereac-ops beside this repo, else None."""
    env = os.environ.get('FREEREAC_OPS')
    if env:
        return env if os.path.isdir(env) else None
    sib = os.path.join(os.path.dirname(os.path.abspath(repo)), 'freereac-ops')
    return sib if os.path.isdir(sib) else None


def ops_path(rel, repo=REPO):
    """The ops copy of moved path <rel>, or None when the checkout or the file is absent."""
    root = ops_root(repo)
    if root is None:
        return None
    p = os.path.join(root, OPS_SUBDIR, rel)
    return p if os.path.isfile(p) else None


def resolve(name, repo=REPO):
    """A slug (or a moved path) -> the ops file it names, or None."""
    _, paths = read_moves(repo)
    hits = [p for p in paths if p == name or slug(p) == name]
    return ops_path(hits[0], repo) if len(hits) == 1 else None


def gone_dirs(paths, kept):
    """Directories every file of which moved: a public file naming one points at nothing."""
    dirs = {p.rsplit('/', 1)[0] for p in paths if '/' in p}
    return sorted(d for d in dirs if not any(k.startswith(d + '/') for k in kept))


def citation_patterns(paths, kept):
    kept_names = {k.rsplit('/', 1)[-1] for k in kept}
    out = []
    for d in gone_dirs(paths, kept):
        # `journal/`, not the word journal and not a slug inside it (journal/<slug> is a citation)
        out.append((d + '/', re.compile((r'(?<![\w./-])%s/(?![\w.-])' % re.escape(d)).encode())))
    for p in paths:
        pats = [re.escape(p)]
        base = p.rsplit('/', 1)[-1]
        if base.endswith(BARE_CITED_EXT) and base not in kept_names:
            pats.append(r'(?<![\w./-])' + re.escape(base))
        out.append((p, re.compile(('(?:%s)(?![\\w-])' % '|'.join(pats)).encode())))
    return out


def check(repo=REPO, out=sys.stdout):
    """Every failure on its own line; returns the count."""
    fails = 0

    def fail(msg):
        nonlocal fails
        fails += 1
        print(msg, file=out)

    _, paths = read_moves(repo)
    tracked = git('ls-files', '-z', cwd=repo).decode().split('\0')
    tracked = [t for t in tracked if t]
    present = set(tracked)
    for p in paths:
        if p in present:
            fail('STILL-PUBLIC %s: listed as moved to freereac-ops' % p)
    for t in tracked:
        if t not in paths and belongs_in_ops(t):
            fail('INTERNAL %s: lab-notebook material belongs in freereac-ops (%s)' % (t, MOVES))
    pats = citation_patterns(paths, [t for t in tracked if t not in paths])
    for t in tracked:
        if t in SCAN_EXEMPT or CAPTURE.search(t) or t in paths:
            continue
        try:
            with open(os.path.join(repo, t), 'rb') as f:
                data = f.read()
        except OSError:
            continue
        for p, rx in pats:
            for m in rx.finditer(data):
                line = data.count(b'\n', 0, m.start()) + 1
                if p.endswith('/'):
                    fail('CITES %s:%d %s: a directory that moved to freereac-ops' % (t, line, p))
                else:
                    fail('CITES %s:%d %s: cite the slug %s, not the file' % (t, line, p, slug(p)))
    root = ops_root(repo)
    if root is None:
        if os.environ.get('FREEREAC_REQUIRE_OPS') == '1':
            fail('OPS-ABSENT moves-resolve: FREEREAC_REQUIRE_OPS=1 and no freereac-ops checkout '
                 '($FREEREAC_OPS or ../freereac-ops)')
        else:
            print('OPS-ABSENT moves-resolve: skipped (no freereac-ops checkout)', file=out)
    else:
        missing = [p for p in paths if ops_path(p, repo) is None]
        for p in missing:
            fail('UNRESOLVED %s: not at %s/%s/%s' % (slug(p), root, OPS_SUBDIR, p))
        if not missing:
            print('OPS OK %d moved paths resolve in %s' % (len(paths), root), file=out)
    print('CHECK OK' if fails == 0 else 'CHECK FAILED %d' % fails, file=out)
    return fails


def export(ops, branch=BRANCH, repo=REPO, out=sys.stdout):
    """Commit the moved files at the list's base, byte-identical, onto <branch> of <ops>."""
    base, paths = read_moves(repo)
    entries = []
    for p in paths:
        row = git('ls-tree', base, '--', p, cwd=repo).decode().strip()
        if not row:
            raise SystemExit('EXPORT REFUSED: %s is not in %s' % (p, base))
        mode, _, sha = row.split('\t')[0].split()
        blob = git('cat-file', 'blob', sha, cwd=repo)
        if git('hash-object', '-w', '--stdin', cwd=ops, data=blob).decode().strip() != sha:
            raise SystemExit('EXPORT REFUSED: %s changed in transit' % p)
        entries.append((mode, sha, '%s/%s' % (OPS_SUBDIR, p)))
    start = None
    for ref in ('refs/remotes/origin/main', 'refs/heads/main'):
        r = git('rev-parse', '-q', '--verify', ref + '^{commit}', cwd=ops, check=False).decode().strip()
        if r:
            start = r
            break
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(d, 'index'))

        def g(*args, data=None):
            p = subprocess.run(['git', *args], cwd=ops, env=env, capture_output=True, input=data)
            if p.returncode != 0:
                raise SystemExit('git %s: %s' % (' '.join(args), p.stderr.decode(errors='replace')))
            return p.stdout.decode().strip()

        g('read-tree', start) if start else g('read-tree', '--empty')
        for mode, sha, dest in entries:
            have = g('ls-files', '-s', '--', dest)
            if have and have.split()[1] != sha:
                raise SystemExit('EXPORT REFUSED: %s already in the ops tree with other content' % dest)
            g('update-index', '--add', '--cacheinfo', '%s,%s,%s' % (mode, sha, dest))
        tree = g('write-tree')
        msg = ('reac-lab: design specs, runbooks and journal\n\n'
               'From FreeREAC/reac-lab@%s, byte-identical (%d files, %s).\n'
               'Their history before the move: git log %s -- <path> in reac-lab.\n'
               % (base[:12], len(entries), MOVES, base[:12]))
        args = ['commit-tree', tree, '-m', msg] + (['-p', start] if start else [])
        # commit-tree never reads commit.gpgSign itself; every ops commit is signed when it is set
        if git('config', '--bool', 'commit.gpgsign', cwd=ops, check=False).strip() == b'true':
            args.append('-S')
        existing = git('rev-parse', '-q', '--verify', 'refs/heads/' + branch, cwd=ops,
                       check=False).decode().strip()
        if existing:
            if g('rev-parse', existing + '^{tree}') == tree:
                print('EXPORT EXISTS %s %s %d files' % (branch, existing, len(entries)), file=out)
                return existing
            raise SystemExit('EXPORT REFUSED: %s exists at %s with another tree' % (branch, existing))
        commit = g(*args)
        g('update-ref', 'refs/heads/' + branch, commit, '0' * 40)
    print('EXPORT %s %s %d files' % (branch, commit, len(entries)), file=out)
    return commit


def main(argv):
    if len(argv) >= 1 and argv[0] == 'check':
        return 1 if check() else 0
    if len(argv) == 2 and argv[0] == 'resolve':
        p = resolve(argv[1])
        if p is None:
            print('OPS-ABSENT %s' % argv[1])
            return 3
        print(p)
        return 0
    if len(argv) in (2, 3) and argv[0] == 'export':
        export(os.path.abspath(argv[1]), *argv[2:])
        return 0
    print(__doc__.split('\n\n')[2], file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
