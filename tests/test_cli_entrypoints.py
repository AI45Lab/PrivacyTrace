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
            (["-m", "generate.generate_profiles"], "--count"),
            (["generate/build_targets.py"], "--income-only"),
            (["generate/benchmark_provider.py"], "--help"),
            (["-m", "generate.generate_scenarios"], "--input"),
            (["-m", "agent.run_scenarios"], "--profiles"),
            (["-m", "agent.package_trajectories"], "--source-dir"),
            (["-m", "attack.run_attacks"], "--attack-mode"),
            (["-m", "attack.run_channels"], "--input"),
            (["-m", "attack.run_view_scopes"], "--scope"),
            (["-m", "eval.run_judge"], "--records"),
            (["-m", "eval.reproduce_results"], "--output-root"),
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
