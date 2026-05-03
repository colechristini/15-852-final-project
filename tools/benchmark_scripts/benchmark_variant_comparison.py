#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


THREADS = (1, 2, 4, 8)
TRIALS = 3
N = 100_000
ARBORICITY = 20
BATCHES = 10
SEED = 0
EPSILON = 0.5
TIME_RE = re.compile(r"Time taken \(ns\):\s*(\d+)")

VARIANTS: Tuple[Dict[str, Any], ...] = (
    {
        "name": "baseline",
        "label": "Baseline",
        "deterministic_sort": False,
        "hash_table": False,
    },
    {
        "name": "deterministic_sort",
        "label": "Deterministic sort",
        "deterministic_sort": True,
        "hash_table": False,
    },
    {
        "name": "hashing",
        "label": "Hashing",
        "deterministic_sort": False,
        "hash_table": True,
    },
    {
        "name": "deterministic_sort_hashing",
        "label": "Both",
        "deterministic_sort": True,
        "hash_table": True,
    },
)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]


def require_dependencies() -> None:
    missing = []
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        missing.append("matplotlib")
    try:
        import tqdm  # noqa: F401
    except ImportError:
        missing.append("tqdm")
    if missing:
        raise SystemExit(f"Missing Python package(s): {', '.join(missing)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare baseline, deterministic sort, hashing, and combined parallel "
            "orientation variants on n=100000, arboricity=20, 10 batches, s0."
        )
    )
    parser.add_argument("--benchmarks-dir", type=Path, default=PROJECT_ROOT / "benchmarks")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "benchmark_results" / "variant_comparison")
    parser.add_argument("--runner", type=Path, default=PROJECT_ROOT / "run_graph_orientation")
    parser.add_argument("--threads", type=int, nargs="+", default=list(THREADS))
    parser.add_argument("--trials", type=int, default=TRIALS)
    parser.add_argument("--eps", type=float, default=EPSILON)
    parser.add_argument("--make-target", default="run_graph_orientation")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--timeout-seconds", type=float)
    return parser.parse_args()


def build_runner(project_dir: Path, make_target: str) -> None:
    subprocess.run(["make", make_target], cwd=project_dir, check=True)


def parse_time_ns(stdout: str) -> int:
    match = TIME_RE.search(stdout)
    if not match:
        raise RuntimeError(f"Could not parse timing from runner output:\n{stdout}")
    return int(match.group(1))


def graph_path(benchmarks_dir: Path) -> Path:
    return benchmarks_dir / f"n{N}_c{ARBORICITY}_b{BATCHES}_s{SEED}.txt"


def run_variant(
    runner: Path,
    graph_file: Path,
    output_dir: Path,
    variant: Dict[str, Any],
    threads: int,
    eps: float,
    timeout_seconds: float | None,
) -> int:
    fd, output_name = tempfile.mkstemp(
        prefix=f"{variant['name']}_", suffix=".oriented", dir=output_dir
    )
    os.close(fd)
    output_path = Path(output_name)
    try:
        cmd = [
            str(runner),
            str(graph_file),
            "parallel",
            str(output_path),
            "-c",
            str(ARBORICITY),
            "-eps",
            str(eps),
        ]
        if variant["deterministic_sort"]:
            cmd.append("--deterministic-sort")
        if variant["hash_table"]:
            cmd.append("--hash-table")

        env = os.environ.copy()
        env["PARLAY_NUM_THREADS"] = str(threads)
        completed = subprocess.run(
            cmd,
            cwd=runner.parent,
            env=env,
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        return parse_time_ns(completed.stdout)
    finally:
        output_path.unlink(missing_ok=True)


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.fmean(items) if items else float("nan")


def stdev(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.stdev(items) if len(items) > 1 else 0.0


def summarize(raw_trials: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[Tuple[str, int], List[int]] = {}
    for trial in raw_trials:
        grouped.setdefault((trial["variant"], trial["threads"]), []).append(trial["time_ns"])

    summaries: Dict[str, Any] = {}
    for variant, threads in grouped:
        times_ns = grouped[(variant, threads)]
        times_seconds = [time_ns / 1e9 for time_ns in times_ns]
        summaries.setdefault(variant, {"threads": {}})
        summaries[variant]["threads"][str(threads)] = {
            "trials": len(times_ns),
            "mean_time_ns": int(round(mean(times_ns))),
            "mean_time_seconds": mean(times_seconds),
            "stdev_time_seconds": stdev(times_seconds),
            "min_time_seconds": min(times_seconds),
            "max_time_seconds": max(times_seconds),
        }

    for variant_data in summaries.values():
        one_thread = variant_data["threads"].get("1", {}).get("mean_time_seconds")
        for thread_key, thread_data in variant_data["threads"].items():
            current = thread_data["mean_time_seconds"]
            thread_data["speedup_1_thread_over_n_threads"] = (
                one_thread / current if one_thread and current > 0 else float("nan")
            )
    return summaries


def plot_time(summaries: Dict[str, Any], threads: List[int], output_path: Path) -> None:
    import matplotlib.pyplot as plt

    labels = {variant["name"]: variant["label"] for variant in VARIANTS}
    plt.figure(figsize=(8, 5))
    for variant in VARIANTS:
        variant_name = variant["name"]
        if variant_name not in summaries:
            continue
        xs = []
        ys = []
        for thread_count in threads:
            thread_data = summaries[variant_name]["threads"].get(str(thread_count))
            if thread_data is None:
                continue
            xs.append(thread_count)
            ys.append(thread_data["mean_time_seconds"])
        if xs:
            plt.plot(xs, ys, marker="o", label=labels[variant_name])

    plt.title("Parallel Orientation Variant Comparison")
    plt.xlabel("Threads")
    plt.ylabel("Mean time (seconds)")
    plt.xticks(threads)
    plt.yscale("log")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def plot_speedup(summaries: Dict[str, Any], threads: List[int], output_path: Path) -> None:
    import matplotlib.pyplot as plt

    labels = {variant["name"]: variant["label"] for variant in VARIANTS}
    plt.figure(figsize=(8, 5))
    for variant in VARIANTS:
        variant_name = variant["name"]
        if variant_name not in summaries:
            continue
        xs = []
        ys = []
        for thread_count in threads:
            thread_data = summaries[variant_name]["threads"].get(str(thread_count))
            if thread_data is None:
                continue
            xs.append(thread_count)
            ys.append(thread_data["speedup_1_thread_over_n_threads"])
        if xs:
            plt.plot(xs, ys, marker="o", label=labels[variant_name])

    plt.title("Variant Parallel Speedup")
    plt.xlabel("Threads")
    plt.ylabel("1-thread time / N-thread time")
    plt.xticks(threads)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / ".matplotlib").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(args.output_dir / ".matplotlib"))
    require_dependencies()

    if args.trials <= 0:
        raise SystemExit("--trials must be positive")

    project_dir = PROJECT_ROOT
    if not args.no_build:
        build_runner(project_dir, args.make_target)

    runner = args.runner.resolve()
    if not runner.exists():
        raise SystemExit(f"Runner not found: {runner}")

    graph_file = graph_path(args.benchmarks_dir)
    if not graph_file.exists():
        raise SystemExit(f"Benchmark file not found: {graph_file}")

    from tqdm import tqdm

    scratch_dir = args.output_dir / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    raw_trials: List[Dict[str, Any]] = []
    total = len(VARIANTS) * len(args.threads) * args.trials

    progress = tqdm(total=total, desc="Benchmarking variants", unit="run")
    try:
        for variant in VARIANTS:
            for thread_count in args.threads:
                for trial in range(args.trials):
                    time_ns = run_variant(
                        runner,
                        graph_file,
                        scratch_dir,
                        variant,
                        thread_count,
                        args.eps,
                        args.timeout_seconds,
                    )
                    raw_trials.append(
                        {
                            "variant": variant["name"],
                            "variant_label": variant["label"],
                            "deterministic_sort": variant["deterministic_sort"],
                            "hash_table": variant["hash_table"],
                            "threads": thread_count,
                            "trial": trial,
                            "time_ns": time_ns,
                            "graph_file": str(graph_file),
                        }
                    )
                    progress.update(1)
    finally:
        progress.close()
        shutil.rmtree(scratch_dir, ignore_errors=True)

    summaries = summarize(raw_trials)
    results = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "n": N,
            "arboricity": ARBORICITY,
            "batches": BATCHES,
            "seed": SEED,
            "trials": args.trials,
            "threads": args.threads,
            "eps": args.eps,
            "runner": str(runner),
            "graph_file": str(graph_file),
        },
        "variants": list(VARIANTS),
        "raw_trials": raw_trials,
        "summaries": summaries,
    }

    json_path = args.output_dir / "variant_comparison.json"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    time_plot = args.output_dir / "variant_comparison_time.png"
    speedup_plot = args.output_dir / "variant_comparison_speedup.png"
    plot_time(summaries, args.threads, time_plot)
    plot_speedup(summaries, args.threads, speedup_plot)

    print(f"Wrote JSON results to {json_path}")
    print(f"Wrote plot to {time_plot}")
    print(f"Wrote plot to {speedup_plot}")


if __name__ == "__main__":
    main()
