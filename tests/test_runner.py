import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'paper.py'


class RunnerTests(unittest.TestCase):
    def test_cli_exists(self):
        self.assertTrue(SCRIPT.exists(), 'Missing duration-bounded paper CLI')

    @unittest.skipUnless(SCRIPT.exists(), 'CLI not implemented yet')
    def test_bounded_demo_completes_and_report_is_persisted(self):
        with TemporaryDirectory() as directory:
            cmd = [sys.executable, '-I', str(SCRIPT), 'run', '--source', 'demo',
                   '--duration-minutes', '.05', '--poll-seconds', '.05', '--output', directory]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([sys.executable, '-I', str(SCRIPT), 'report', '--output', directory],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['state']['status'], 'COMPLETED')
            self.assertGreaterEqual(report['state']['completed_trades'], 1)
            self.assertEqual(report['state']['classification'], 'DEMO_SYNTHETIC')
            self.assertFalse(report['worker_lock_held'])
            self.assertIn('events', report)

    @unittest.skipUnless(SCRIPT.exists(), 'CLI not implemented yet')
    def test_cli_has_no_live_mode(self):
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), 'start', '--source', 'live',
                                 '--duration-minutes', '30'], capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)

    @unittest.skipUnless(SCRIPT.exists(), 'CLI not implemented yet')
    def test_running_worker_blocks_duplicate_and_honors_stop(self):
        with TemporaryDirectory() as directory:
            worker = subprocess.Popen([sys.executable, '-I', str(SCRIPT), 'run', '--source', 'demo',
                                       '--duration-minutes', '1', '--poll-seconds', '.1', '--output', directory],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                started = json.loads(worker.stdout.readline())
                self.assertEqual(started['event'], 'STARTED')
                duplicate = subprocess.run([sys.executable, '-I', str(SCRIPT), 'start', '--source', 'demo',
                                            '--duration-minutes', '1', '--output', directory],
                                           capture_output=True, text=True, timeout=5)
                self.assertNotEqual(duplicate.returncode, 0)
                stopped = subprocess.run([sys.executable, '-I', str(SCRIPT), 'stop', '--source', 'demo',
                                          '--output', directory], capture_output=True, text=True, timeout=5)
                self.assertEqual(json.loads(stopped.stdout)['status'], 'STOP_REQUESTED')
                stdout, stderr = worker.communicate(timeout=10)
                self.assertEqual(worker.returncode, 0, stderr)
                report = subprocess.run([sys.executable, '-I', str(SCRIPT), 'report', '--output', directory],
                                        capture_output=True, text=True, timeout=5)
                state = json.loads(report.stdout)['state']
                self.assertIsNone(state['position'])
                self.assertEqual(state['status'], 'COMPLETED')
            finally:
                if worker.poll() is None:
                    worker.kill()
                    worker.communicate(timeout=5)
                if worker.stdout:
                    worker.stdout.close()
                if worker.stderr:
                    worker.stderr.close()


if __name__ == '__main__':
    unittest.main()