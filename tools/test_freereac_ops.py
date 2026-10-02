# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/freereac_ops.py on throwaway git repos: the public-tree guard, the resolver rungs and the
ops export. Run: python3 -m unittest discover -s tools -p 'test_*.py'"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import freereac_ops as fo  # noqa: E402

MOVED = ['design-specs/2026-01-01-x-design.md', 'runbooks/rig-install.md',
         'captures/2026-01-02-y-plan.md']


def sh(cwd, *args):
    subprocess.run(['git', '-c', 'commit.gpgsign=false', *args], cwd=cwd, check=True,
                   capture_output=True)


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        f.write(text)


class Fixture(unittest.TestCase):
    """<tmp>/pub: a repo whose base commit holds MOVED, whose tip moved them out."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pub = os.path.join(self.tmp, 'pub')
        os.makedirs(self.pub)
        sh(self.pub, 'init', '-q', '-b', 'main')
        sh(self.pub, 'config', 'user.email', 't@example.com')
        sh(self.pub, 'config', 'user.name', 'T')
        write(self.pub, 'README.md', 'lab\n')
        write(self.pub, 'captures/README.md', 'captures\n')
        write(self.pub, 'captures/a.pcap', 'pointer\n')
        for p in MOVED:
            write(self.pub, p, 'internal %s\n' % p)
        sh(self.pub, 'add', '-A')
        sh(self.pub, 'commit', '-qm', 'base')
        self.base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.pub, capture_output=True,
                                   text=True).stdout.strip()
        sh(self.pub, 'rm', '-q', *MOVED)
        write(self.pub, fo.MOVES, '# base %s\n%s\n' % (self.base, '\n'.join(MOVED)))
        sh(self.pub, 'add', '-A')
        sh(self.pub, 'commit', '-qm', 'move')
        env = {k: v for k, v in os.environ.items() if not k.startswith('FREEREAC_')}
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp)

    def run_check(self):
        buf = io.StringIO()
        n = fo.check(self.pub, out=buf)
        return n, buf.getvalue()

    def add(self, rel, text):
        write(self.pub, rel, text)
        sh(self.pub, 'add', rel)

    def make_ops(self, root, paths=MOVED):
        for p in paths:
            write(root, os.path.join(fo.OPS_SUBDIR, p), 'internal %s\n' % p)


class Classifier(unittest.TestCase):
    def test_rule(self):
        for p in ('design-specs/2026-05-30-x-design.md', 'runbooks/on-rig-session-runbook.md',
                  'journal/2026-06-10-x.md', 'plans/wave-3.txt', 'notes/x.json', 'adr/0001-x.md',
                  'audits/2026-09-25-x.tsv', '.claude/skills/x/SKILL.md', 'ROADMAP.md',
                  'CLAUDE.md', 'captures/2026-09-01-plan.md', 'x-plan.md'):
            self.assertTrue(fo.belongs_in_ops(p), p)
        for p in ('README.md', 'NOTICE', 'LICENSE', 'BUILDING.md', 'CONTRIBUTING.md',
                  'captures/README.md', 'captures/a.pcap', 'captures/a.notes.txt',
                  'tools/ops-moves.txt', 'tools/freereac_ops.py', '.github/workflows/check.yml'):
            self.assertFalse(fo.belongs_in_ops(p), p)

    def test_slug(self):
        self.assertEqual(fo.slug('runbooks/rig-parked-state.md'), 'runbooks/rig-parked-state')

    def test_gone_dirs(self):
        self.assertEqual(fo.gone_dirs(MOVED, ['README.md', 'captures/README.md']),
                         ['design-specs', 'runbooks'])


class Check(Fixture):
    def test_clean_tree_passes_and_names_the_skip(self):
        n, out = self.run_check()
        self.assertEqual(n, 0, out)
        self.assertIn('OPS-ABSENT moves-resolve: skipped', out)
        self.assertIn('CHECK OK', out)

    def test_moved_path_still_public_fails(self):
        self.add('runbooks/rig-install.md', 'back\n')
        n, out = self.run_check()
        self.assertIn('STILL-PUBLIC runbooks/rig-install.md', out)
        self.assertGreater(n, 0)

    def test_new_notebook_entry_fails(self):
        self.add('journal/2026-10-02-x.md', 'new entry\n')
        n, out = self.run_check()
        self.assertIn('INTERNAL journal/2026-10-02-x.md', out)

    def test_citation_by_file_fails_and_slug_passes(self):
        self.add('captures/README.md', 'see runbooks/rig-install.md and 2026-01-02-y-plan.md\n')
        n, out = self.run_check()
        self.assertIn('CITES captures/README.md:1 runbooks/rig-install.md', out)
        self.assertIn('CITES captures/README.md:1 captures/2026-01-02-y-plan.md', out)
        self.assertEqual(n, 2, out)
        self.add('captures/README.md', 'see runbooks/rig-install and captures/2026-01-02-y-plan\n')
        self.assertEqual(self.run_check()[0], 0)

    def test_naming_a_directory_that_moved_out_fails(self):
        self.add('README.md', 'the dated specs are in `design-specs/`\n')
        n, out = self.run_check()
        self.assertIn('CITES README.md:1 design-specs/: a directory that moved', out)
        self.assertEqual(n, 1, out)
        # the word is prose, and a slug inside the directory is a citation
        self.add('README.md', 'dated design-specs and runbooks; see design-specs/2026-01-01-x-design\n')
        self.assertEqual(self.run_check()[0], 0)
        # a directory that still holds a public file is not gone
        self.add('README.md', 'the captures are in `captures/`\n')
        self.assertEqual(self.run_check()[0], 0)

    def test_require_ops_fails_when_absent(self):
        os.environ['FREEREAC_REQUIRE_OPS'] = '1'
        n, out = self.run_check()
        self.assertIn('OPS-ABSENT moves-resolve: FREEREAC_REQUIRE_OPS=1', out)
        self.assertEqual(n, 1)

    def test_env_rung_resolves_every_move(self):
        ops = os.path.join(self.tmp, 'elsewhere')
        self.make_ops(ops)
        os.environ['FREEREAC_OPS'] = ops
        n, out = self.run_check()
        self.assertEqual(n, 0, out)
        self.assertIn('OPS OK 3 moved paths', out)
        self.assertEqual(fo.resolve('runbooks/rig-install', self.pub),
                         os.path.join(ops, 'reac-lab', 'runbooks', 'rig-install.md'))

    def test_sibling_rung_and_half_moved_fails(self):
        sib = os.path.join(self.tmp, 'freereac-ops')
        self.make_ops(sib, MOVED[:2])
        self.assertEqual(fo.ops_root(self.pub), sib)
        n, out = self.run_check()
        self.assertIn('UNRESOLVED captures/2026-01-02-y-plan', out)
        self.assertEqual(n, 1, out)
        os.environ['FREEREAC_OPS'] = os.path.join(self.tmp, 'nope')
        self.assertIsNone(fo.ops_root(self.pub), 'a set but missing $FREEREAC_OPS never falls through')

    def test_resolve_absent(self):
        self.assertIsNone(fo.resolve('runbooks/rig-install', self.pub))


class Export(Fixture):
    def ops_repo(self, seeded):
        ops = os.path.join(self.tmp, 'freereac-ops')
        os.makedirs(ops)
        sh(ops, 'init', '-q', '-b', 'main')
        sh(ops, 'config', 'user.email', 't@example.com')
        sh(ops, 'config', 'user.name', 'T')
        sh(ops, 'config', 'commit.gpgsign', 'false')
        if seeded:
            write(ops, 'README.md', 'ops\n')
            sh(ops, 'add', '-A')
            sh(ops, 'commit', '-qm', 'seed')
        return ops

    def ls(self, ops, ref):
        return subprocess.run(['git', 'ls-tree', '-r', ref], cwd=ops, capture_output=True,
                              text=True).stdout

    def test_export_onto_main_is_byte_identical_and_idempotent(self):
        ops = self.ops_repo(seeded=True)
        buf = io.StringIO()
        c = fo.export(ops, repo=self.pub, out=buf)
        self.assertIn('EXPORT lane/docs-reac-lab', buf.getvalue())
        tree = self.ls(ops, fo.BRANCH)
        self.assertIn('\tREADME.md\n', tree)
        for p in MOVED:
            src = subprocess.run(['git', 'rev-parse', '%s:%s' % (self.base, p)], cwd=self.pub,
                                 capture_output=True, text=True).stdout.strip()
            self.assertIn('%s\treac-lab/%s\n' % (src, p), tree)
        parent = subprocess.run(['git', 'rev-parse', fo.BRANCH + '^'], cwd=ops,
                                capture_output=True, text=True).stdout.strip()
        main = subprocess.run(['git', 'rev-parse', 'main'], cwd=ops, capture_output=True,
                              text=True).stdout.strip()
        self.assertEqual(parent, main)
        buf = io.StringIO()
        self.assertEqual(fo.export(ops, repo=self.pub, out=buf), c)
        self.assertIn('EXPORT EXISTS', buf.getvalue())
        # the exported checkout is what `check` then resolves through the sibling rung
        subprocess.run(['git', '-c', 'advice.detachedHead=false', 'checkout', '-q', fo.BRANCH],
                       cwd=ops, check=True)
        self.assertEqual(self.run_check()[0], 0)

    def test_export_signs_when_commit_gpgsign_is_set(self):
        ops = self.ops_repo(seeded=True)
        sh(ops, 'config', 'commit.gpgsign', 'true')
        sh(ops, 'config', 'gpg.program', os.path.join(self.tmp, 'no-gpg'))
        with self.assertRaises(SystemExit) as e:
            fo.export(ops, repo=self.pub, out=io.StringIO())
        self.assertIn('commit-tree', str(e.exception), 'the export asked gpg to sign, and gpg failed')

    def test_export_into_empty_ops_is_a_root_commit(self):
        ops = self.ops_repo(seeded=False)
        fo.export(ops, repo=self.pub, out=io.StringIO())
        self.assertEqual(len(self.ls(ops, fo.BRANCH).splitlines()), len(MOVED))

    def test_export_refuses_a_path_missing_at_base(self):
        ops = self.ops_repo(seeded=True)
        write(self.pub, fo.MOVES, '# base %s\nnot/there.md\n' % self.base)
        with self.assertRaises(SystemExit) as e:
            fo.export(ops, repo=self.pub, out=io.StringIO())
        self.assertIn('not/there.md is not in', str(e.exception))

    def test_export_refuses_a_base_the_rewrite_took_away(self):
        ops = self.ops_repo(seeded=True)
        write(self.pub, fo.MOVES, '# base %s\n%s\n' % ('e' * 40, '\n'.join(MOVED)))
        with self.assertRaises(SystemExit) as e:
            fo.export(ops, repo=self.pub, out=io.StringIO())
        self.assertIn('backup/pre-rewrite-2026-10-01', str(e.exception))


class History(Fixture):
    """The rewrite's drop list and the guard that keeps the rewritten history clean."""

    def commit(self, msg):
        sh(self.pub, 'commit', '-qm', msg)

    def drops(self, *revs):
        out, err = io.StringIO(), io.StringIO()
        n = fo.history(revs or ('--all',), self.pub, out=out, err=err)
        return n, out.getvalue().split(), err.getvalue()

    def guard(self, *revs):
        buf = io.StringIO()
        n = fo.history_check(revs or ('HEAD',), self.pub, out=buf)
        return n, buf.getvalue()

    def test_drop_list_is_every_moved_path_even_deleted_ones(self):
        n, paths, err = self.drops()
        self.assertEqual((n, err), (0, ''))
        self.assertEqual(paths, sorted(MOVED))

    def test_an_internal_path_off_the_list_is_refused_by_name(self):
        sh(self.pub, 'checkout', '-q', '-b', 'side')
        self.add('journal/2026-01-03-z.md', 'an entry\n')
        self.commit('entry')
        sh(self.pub, 'rm', '-q', 'journal/2026-01-03-z.md')
        self.commit('drop entry')
        sh(self.pub, 'checkout', '-q', 'main')
        self.assertEqual(self.drops('main')[0], 0, 'the side branch is not in main')
        n, paths, err = self.drops()
        self.assertEqual(n, 1)
        self.assertIn('UNLISTED journal/2026-01-03-z.md', err)
        self.assertIn('journal/2026-01-03-z.md', paths)

    def test_guard_is_red_on_the_old_history_and_names_the_paths(self):
        n, out = self.guard()
        self.assertEqual(n, len(MOVED), out)
        self.assertIn('HISTORY-INTERNAL runbooks/rig-install.md: added in %s' % self.base[:12], out)
        self.assertIn('HISTORY FAILED 3', out)

    def test_guard_is_green_on_a_clean_history_and_red_on_an_add_and_delete(self):
        sh(self.pub, 'checkout', '-q', '--orphan', 'clean')
        sh(self.pub, 'rm', '-rq', '--cached', '.')
        self.add('README.md', 'lab\n')
        self.add(fo.MOVES, '# base %s\n%s\n' % (self.base, '\n'.join(MOVED)))
        self.add('a' * 40, 'a 40-hex file name is a file, not a commit\n')
        self.commit('rewritten')
        n, out = self.guard()
        self.assertEqual(n, 0, out)
        self.assertIn('HISTORY OK 1 commits', out)
        self.add('runbooks/new-runbook.md', 'back\n')
        self.commit('oops')
        sh(self.pub, 'rm', '-q', 'runbooks/new-runbook.md')
        self.commit('undo')
        n, out = self.guard()
        self.assertIn('HISTORY-INTERNAL runbooks/new-runbook.md', out)
        self.assertEqual(n, 1, out)

    def test_a_file_a_merge_adds_is_seen(self):
        sh(self.pub, 'checkout', '-q', '-b', 'side')
        self.add('side.txt', 'x\n')
        self.commit('side')
        sh(self.pub, 'checkout', '-q', 'main')
        sh(self.pub, 'merge', '-q', '--no-ff', '--no-commit', 'side')
        self.add('plans/p.md', 'only the merge adds this\n')
        self.commit('merge')
        self.assertIn('plans/p.md', fo.history_paths(['HEAD'], self.pub))


class RealTree(unittest.TestCase):
    """This repository, before its history rewrite and after it: the tree is clean, every internal
    path its history carries is on the move list, and the list is the rule at its base."""

    def test_the_list_is_the_rule_at_base(self):
        base, paths = fo.read_moves()
        if not fo.has_commit(base):
            self.skipTest('base %s rewritten away; the history tests hold instead' % base[:12])
        tree = fo.git('ls-tree', '-r', '--name-only', base).decode().splitlines()
        self.assertEqual(sorted(p for p in tree if fo.belongs_in_ops(p)), sorted(paths))

    def test_every_internal_path_in_the_history_is_listed(self):
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(fo.history(('HEAD',), out=out, err=err), 0, err.getvalue())

    def test_once_the_base_is_gone_the_history_carries_nothing_listed(self):
        base, paths = fo.read_moves()
        # gone from HEAD's history; a clone that fetched the backup tag still has the commit
        if subprocess.run(['git', 'merge-base', '--is-ancestor', base, 'HEAD'], cwd=fo.REPO,
                          capture_output=True).returncode == 0:
            self.skipTest('base %s still in the history: it is not rewritten yet' % base[:12])
        buf = io.StringIO()
        self.assertEqual(fo.history_check(('HEAD',), out=buf), 0, buf.getvalue())

    def test_the_public_tree_is_clean(self):
        env = {k: v for k, v in os.environ.items() if k != 'FREEREAC_REQUIRE_OPS'}
        with mock.patch.dict(os.environ, env, clear=True):
            buf = io.StringIO()
            self.assertEqual(fo.check(out=buf), 0, buf.getvalue())


if __name__ == '__main__':
    unittest.main()
