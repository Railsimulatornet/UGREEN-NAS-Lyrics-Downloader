"""Regressionstests gegen eine Selbstblockade der Patch-Autofreigabe."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/dependabot-automerge.yml'
GATE = ROOT / '.github/scripts/dependabot_automerge.py'
PATTERN = "-p 'test_dependabot_automerge*.py'"


class WorkflowSicherheit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding='utf-8')
        cls.testjob = cls.workflow.split('\n  test:\n', 1)[1].split('\n  classify:\n', 1)[0]
        cls.mergejob = cls.workflow.split('\n  merge:\n', 1)[1]

    def test_hilfstest_laeuft_bei_beiden_pr_ereignissen(self):
        self.assertIn("if: github.event_name == 'pull_request' || github.event_name == 'pull_request_target'", self.testjob)

    def test_zielereignis_verwendet_nur_vertrauenswuerdigen_basisstand(self):
        self.assertIn("ref: ${{ github.event_name == 'pull_request_target' && github.event.pull_request.base.sha || github.ref }}", self.testjob)
        self.assertNotIn('pull_request.head', self.testjob)
        self.assertNotIn('secrets.', self.testjob)

    def test_hilfstest_bleibt_ausschliesslich_lesend(self):
        self.assertIn('permissions:\n      contents: read', self.testjob)
        self.assertIn('persist-credentials: false', self.testjob)
        self.assertNotIn(': write', self.testjob)
        self.assertNotIn('continue-on-error', self.testjob)

    def test_privilegierter_merge_prueft_weiterhin_main(self):
        self.assertIn('ref: main', self.mergejob)
        self.assertIn('persist-credentials: false', self.mergejob)
        self.assertNotIn('pull_request.head', self.mergejob)

    def test_beide_jobs_pruefen_alle_automerge_regressionstests(self):
        self.assertIn(PATTERN, self.testjob)
        self.assertIn(PATTERN, self.mergejob)
        self.assertIn("'.github/scripts/test_dependabot_automerge*.py'", self.workflow)

    def test_uebersprungene_oder_neutrale_pruefungen_werden_nicht_freigegeben(self):
        source = ast.parse(GATE.read_text(encoding='utf-8'))
        assignments = [n for n in source.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'SKIPPED_CHECKS' for t in n.targets)]
        self.assertEqual(len(assignments), 1)
        self.assertEqual(ast.literal_eval(assignments[0].value), {'publish', 'release', 'merge'})


if __name__ == '__main__':
    unittest.main()
