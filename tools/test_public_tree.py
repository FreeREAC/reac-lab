# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/freereac_ops.py after the move: one plain rule, no move list.

The public tree keeps the README, the licence, the captures and the tools; any other
Markdown file is lab-notebook material and is refused. There is no list of moved paths,
no resolver, no export, and no rules file read from the private checkout.
Run: python3 -m unittest discover -s tools -p 'test_*.py'"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import freereac_ops as fo  # noqa: E402


def sh(cwd, *args):
    subprocess.run(['git', '-c', 'commit.gpgsign=false', *args], cwd=cwd, check=True,
                   capture_output=True)


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        f.write(text)


class Rule(unittest.TestCase):
    def test_classifier(self):
        for p in ('design-specs/2026-01-01-x.md', 'journal/j.md', 'runbooks/r.md', 'NOTES.md',
                  'captures/2026-plan.md'):
            self.assertTrue(fo.belongs_in_ops(p), p)
        for p in ('README.md', 'BUILDING.md', 'LICENSE', 'NOTICE', 'captures/README.md',
                  'captures/a.pcap', 'tools/freereac_ops.py', '.github/workflows/check.yml'):
            self.assertFalse(fo.belongs_in_ops(p), p)

    def test_the_move_machinery_is_gone(self):
        for name in ('MOVES', 'read_moves', 'resolve', 'ops_root', 'ops_path', 'read_rules',
                     'slug', 'citation_patterns', 'export'):
            self.assertFalse(hasattr(fo, name), name)
        self.assertFalse(os.path.exists(os.path.join(fo.REPO, 'tools', 'ops-moves.txt')))


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.pub = os.path.join(self.tmp, 'pub')
        os.makedirs(self.pub)
        sh(self.pub, 'init', '-q', '-b', 'main')
        write(self.pub, 'README.md', 'lab\n')
        write(self.pub, 'captures/README.md', 'captures\n')
        write(self.pub, 'captures/a.pcap', 'pointer\n')
        sh(self.pub, 'add', '-A')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_check(self):
        buf = io.StringIO()
        n = fo.check(self.pub, out=buf)
        return n, buf.getvalue()

    def add(self, rel, text):
        write(self.pub, rel, text)
        sh(self.pub, 'add', rel)

    def test_clean_tree_passes_with_no_move_list_and_no_ops_checkout(self):
        n, out = self.run_check()
        self.assertEqual(n, 0, out)
        self.assertIn('CHECK OK', out)

    def test_notebook_markdown_fails(self):
        for rel in ('design-specs/a.md', 'journal/j.md', 'runbooks/r.md'):
            self.add(rel, 'notes\n')
        n, out = self.run_check()
        self.assertEqual(n, 3, out)
        self.assertIn('INTERNAL journal/j.md', out)

    def test_the_real_tree_is_clean(self):
        buf = io.StringIO()
        self.assertEqual(fo.check(out=buf), 0, buf.getvalue())


if __name__ == '__main__':
    unittest.main()
