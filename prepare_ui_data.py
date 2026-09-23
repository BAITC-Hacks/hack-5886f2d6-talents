#!/usr/bin/env python3
"""Calculate real C++ results and verify the complete static UI data bundle."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from verify_outputs import verify_bundle

ROOT = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT/'frontend/public/data')
    ap.add_argument('--data', type=Path, default=ROOT/'TechTask/data(1)/data')
    ap.add_argument('--core', type=Path)
    ap.add_argument('--core-config', type=Path)
    args = ap.parse_args()
    if args.core is None:
        args.core = next((ROOT/p for p in ('engine/build/engine.exe', 'engine/build/Release/engine.exe', 'engine/build/engine')
                          if (ROOT/p).is_file()), None)
    if args.core is None or not args.core.is_file():
        ap.error('Build the C++ engine or supply --core PATH; no demo fallback')
    cmd = [sys.executable, str(ROOT/'pipeline.py'), '--data', str(args.data.resolve()),
           '--out', str(args.out.resolve()), '--core', str(args.core.resolve())]
    if args.core_config:
        cmd += ['--core-config', str(args.core_config.resolve())]
    try:
        subprocess.run(cmd, check=True, timeout=310)
        report = verify_bundle(args.out, data=args.data, core=args.core)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0
    except Exception as exc:
        print(f'UI data preparation failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
