"""The `osaudit` command line: silent when the paper is clean, one line per finding otherwise.

Exit status: 0 no finding, 1 findings, 2 the audit could not run (configuration, input).
`osaudit run` writes a results file with its provenance; it prints nothing on success.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from . import __version__, _numbers, _provenance, _quotes, _results_check, _study
from ._config import Config, ConfigError, instruments, load
from ._findings import Finding
from ._git import GitError
from ._pdf import PdfError

CONVENTIONS = ("https://github.com/ASSERT-KTH/assert-research-agent/blob/main/"
               "CONVENTIONS.md")


def _results(cfg: Config, args: argparse.Namespace) -> list[Finding]:
    return _results_check.check(cfg, inputs=getattr(args, "inputs", False),
                                rerun=getattr(args, "rerun", False),
                                timeout=getattr(args, "timeout", None))


CHECKS: dict[str, tuple[Callable[[Config, argparse.Namespace], list[Finding]], str]] = {
    "numbers": (lambda cfg, _: _numbers.check(cfg),
                "every number of the paper traced to results, derivation or allow"),
    "quotes": (lambda cfg, _: _quotes.check(cfg),
               "every cited verbatim quote in a verified [[quotes]] entry, with its page"),
    "results": (_results,"every results file has a provenance that still holds "
                          "(static; --inputs, --rerun to go further)"),
    "study": (lambda cfg, _: _study.check(cfg),
              "every confirmatory result pre-registered, unamended after data, on unseen data"),
}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="osaudit",
        description="Audit a paper repository: report every claim not traced to its evidence. "
                    "Silent when clean; `file:line: rule: message` per finding. "
                    f"Conventions: {CONVENTIONS}. "
                    "Without a check name, runs every check (static parts only).",
        epilog="exit status: 0 clean, 1 findings, 2 the audit could not run",
    )
    p.add_argument("--version", action="version", version=f"osaudit {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=Path("."),
                        help="paper repository (default: current directory)")
    common.add_argument("--config", type=Path, help="audit.toml (default: <root>/audit.toml)")
    common.add_argument("--json", action="store_true",
                        help="print findings as a JSON array ([] when clean)")
    sub = p.add_subparsers(dest="check", metavar="CHECK")
    for name, (_, help_) in CHECKS.items():
        sp = sub.add_parser(name, parents=[common], help=help_, description=help_)
        if name == "results":
            sp.add_argument("--inputs", action="store_true",
                            help="rehash every recorded input (needs the inputs)")
            sp.add_argument("--rerun", action="store_true",
                            help="rerun every recorded command at its time anchor and compare")
            sp.add_argument("--timeout", type=float, help="seconds per rerun")
    sub.add_parser("all", parents=[common], help="run every check (the default)")
    run = sub.add_parser(
        "run", help="run an instrument, write its JSON results with their provenance",
        description="Run CMD (its stdout must be a JSON object) with the time anchor in "
                    f"${_provenance.ENV_NOW}, and write the object to OUTPUT with a provenance "
                    "block: command, inputs and their sha256, git commit, time anchor. "
                    "Refuses to run on a tree with uncommitted changes.",
        epilog="example: osaudit run --input data/answers.csv -o results/survey.json -- "
               "python study/survey.py data/answers.csv")
    run.add_argument("--root", type=Path, default=Path("."), help="repository of the instruments")
    run.add_argument("--input", type=Path, action="append", default=[], dest="input_paths",
                     help="an input file or directory (repeat for each)")
    run.add_argument("-o", "--output", type=Path, required=True, help="results file to write")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--prereg", metavar="FILE",
                      help="a CONFIRMATORY run under this committed pre-registration; refused "
                           "unless `osaudit study` would accept the result")
    mode.add_argument("--explore", metavar="FILE",
                      help="an EXPLORATORY run, logged in this exploration log")
    run.add_argument("cmd", nargs=argparse.REMAINDER, help="-- CMD [ARG ...]")
    return p


def _run(args: argparse.Namespace) -> int:
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        print("osaudit run: no command (put it after --)", file=sys.stderr)
        return 2
    root = args.root.resolve()
    try:
        output = args.output.resolve()
        out_rel = str(output.relative_to(root)) if output.is_relative_to(root) else str(output)
        study = args.prereg or args.explore
        if study:
            study = Path(study).resolve().relative_to(root).as_posix()
        mode = "confirmatory" if args.prereg else "exploratory" if args.explore else None
        _provenance.run(root, cmd, args.input_paths, args.output, instruments(root, out_rel),
                        mode, study, _study.precheck(root, out_rel) if mode else None)
    except (_provenance.RunError, ConfigError, GitError, OSError, ValueError) as e:
        print(f"osaudit run: {e}", file=sys.stderr)
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not (argv and argv[0] in (*CHECKS, "all", "run", "-h", "--help", "--version")):
        argv = ["all", *argv]
    args = parser().parse_args(argv)
    if args.check == "run":
        return _run(args)
    names = list(CHECKS) if args.check == "all" else [args.check]
    try:
        cfg = load(args.root.resolve(), args.config.resolve() if args.config else None)
        findings = [f for n in names for f in CHECKS[n][0](cfg, args)]
    except (ConfigError, PdfError, GitError, OSError, ValueError) as e:
        print(f"osaudit: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([f.as_json() for f in findings], indent=1))
    else:
        sys.stdout.write("".join(f"{f}\n" for f in findings))
    return 1 if findings else 0
