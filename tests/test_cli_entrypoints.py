"""Public command entry points must work from a fresh repository checkout."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CLIEntrypointTests(unittest.TestCase):
    def test_help_without_pythonpath(self):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        commands = [
            (["-m", "privacy_trace.profile_generator"], "--count"),
            (["scripts/rebuild_official_ipf_targets.py"], "--income-only"),
            (["scripts/benchmark_profile_provider.py"], "--help"),
        ]
        for arguments, option in commands:
            with self.subTest(command=arguments):
                result = subprocess.run(
                    [sys.executable, *arguments, "--help"],
                    cwd=PROJECT_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(option, result.stdout)
