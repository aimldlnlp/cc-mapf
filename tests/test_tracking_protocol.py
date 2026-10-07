"""Reject invalid execution timing and case paths before writing a protocol."""
from pathlib import Path
import subprocess
import sys


def test_stress_protocol_rejects_invalid_timing_and_case_paths(tmp_path):
    root=Path(__file__).resolve().parents[1]
    for options in [['--step-seconds','nan'],['--cases','../other']]:
        result=subprocess.run([sys.executable,str(root/'scripts/dev/evaluate_robustness.py'),
                               '--reference',str(tmp_path/'reference'),
                               '--output',str(tmp_path/'output'),*options],capture_output=True,text=True)
        assert result.returncode != 0
        assert 'error:' in result.stderr
        assert not (tmp_path/'output').exists()
