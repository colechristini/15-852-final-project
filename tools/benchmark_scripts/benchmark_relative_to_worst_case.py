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


N = 100_000
ARBORICITY = 20
BATCHES = 10
SEED = 0
THREADS = (1, 2, 4, 8)
TRIALS = 5
EPSILON = 0.5

TIME_RE = re.compile(r"Time taken \(ns\):\s*(\d+)")

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
            "Benchmark parallel orientation runtime relative to sequential_worst_case "
            "on n=100000, c=20, b=10, averaged over 5 runs by default."
        )
    )
    parser.add_argument("--benchmarks-dir", type=Path, default=PROJECT_ROOT / "benchmarks")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "benchmark_results" / "relative_to_worst_case")
    parser.add_argument("--runner", type=Path, default=PROJECT_ROOT / "run_graph_orientation")
    parser.add_argument("--threads", type=int, nargs="+", default=list(THREADS))
    parser.add_argument("--trials", type=int, default=TRIALS)
    parser.add_argument("--eps", type=float, default=EPSILON)
    parser.add_argument(
        "--sequential-k",
        type=int,
        help="Optional k for sequential_worst_case; defaults to the runner's ceil(log2 n).",
    )
    parser.add_argument("--make-target", default="run_graph_orientation")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--timeout-seconds", type=float)
    return parser.parse_args()


def build_runner(project_dir: Path, make_target: str) -> None:
    subprocess.run(["make", make_target], cwd=project_dir, check=True)


def graph_path(benchmarks_dir: Path) -> Path:
    return benchmarks_dir / f"n{N}_c{ARBORICITY}_b{BATCHES}_s{SEED}.txt"


def parse_time_ns(stdout: str) -> int:
    match = TIME_RE.search(stdout)
    if not match:
        raise RuntimeError(f"Could not parse timing from runner output:\n{stdout}")
    return int(match.group(1))


def run_command(
    runner: Path,
    graph_file: Path,
    output_dir: Path,
    algorithm: str,
    extra_args: List[str],
    env: Dict[str, str],
    timeout_seconds: float | None,
) -> int:
    fd, output_name = tempfile.mkstemp(prefix="relative_runtime_", suffix=".oriented", dir=output_dir)
    os.close(fd)
    output_path = Path(output_name)
    try:
        cmd = [str(runner), str(graph_file), algorithm, str(output_path), *extra_args]
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


def run_sequential_worst_case(
    runner: Path,
    graph_file: Path,
    output_dir: Path,
    sequential_k: int | None,
    timeout_seconds: float | None,
) -> int:
    extra_args = []
    if sequential_k is not None:
        extra_args += ["-k", str(sequential_k)]
    return run_command(
        runner,
        graph_file,
        output_dir,
        "sequential_worst_case",
        extra_args,
        os.environ.copy(),
        timeout_seconds,
    )


def run_parallel(
    runner: Path,
    graph_file: Path,
    output_dir: Path,
    threads: int,
    eps: float,
    timeout_seconds: float | None,
) -> int:
    env = os.environ.copy()
    env["PARLAY_NUM_THREADS"] = str(threads)
    return run_command(
        runner,
        graph_file,
        output_dir,
        "parallel",
        ["-c", str(ARBORICITY), "-eps", str(eps)],
        env,
        timeout_seconds,
    )


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.fmean(items) if items else float("nan")


def stdev(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.stdev(items) if len(items) > 1 else 0.0


def summarize(raw_trials: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[Tuple[str, int | None], List[int]] = {}
    for trial in raw_trials:
        grouped.setdefault((trial["algorithm"], trial["threads"]), []).append(trial["time_ns"])

    summaries: Dict[str, Any] = {}
    for (algorithm, threads), times_ns in grouped.items():
        key = algorithm if threads is None else f"{algorithm}_t{threads}"
        times_seconds = [time_ns / 1e9 for time_ns in times_ns]
        summaries[key] = {
            "algorithm": algorithm,
            "threads": threads,
            "trials": len(times_ns),
            "mean_time_ns": int(round(mean(times_ns))),
            "mean_time_seconds": mean(times_seconds),
            "stdev_time_seconds": stdev(times_seconds),
            "min_time_seconds": min(times_seconds),
            "max_time_seconds": max(times_seconds),
        }

    sequential_time = summaries["sequential_worst_case"]["mean_time_seconds"]
    for key, summary in summaries.items():
        current = summary["mean_time_seconds"]
        summary["runtime_ratio_vs_sequential_worst_case"] = (
            current / sequential_time if sequential_time > 0 and current > 0 else float("nan")
        )
        summary["speedup_vs_sequential_worst_case"] = (
            sequential_time / current if sequential_time > 0 and current > 0 else float("nan")
        )
    return summaries


def plot_results(summaries: Dict[str, Any], threads: List[int], output_path: Path) -> None:
    import matplotlib.pyplot as plt

    xs = []
    ratios = []
    speedups = []
    for thread_count in threads:
        key = f"parallel_t{thread_count}"
        if key not in summaries:
            continue
        xs.append(thread_count)
        ratios.append(summaries[key]["runtime_ratio_vs_sequential_worst_case"])
        speedups.append(summaries[key]["speedup_vs_sequential_worst_case"])

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))
    axes[0].plot(xs, ratios, marker="o")
    axes[0].axhline(1.0, color="black", linewidth=1, alpha=0.4)
    axes[0].set_title("Runtime Ratio")
    axes[0].set_xlabel("Threads")
    axes[0].set_ylabel("Parallel time / sequential worst-case time")
    axes[0].set_xticks(threads)
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(xs, speedups, marker="o")
    axes[1].axhline(1.0, color="black", linewidth=1, alpha=0.4)
    axes[1].set_title("Speedup")
    axes[1].set_xlabel("Threads")
    axes[1].set_ylabel("Sequential worst-case time / parallel time")
    axes[1].set_xticks(threads)
    axes[1].grid(True, alpha=0.3)

    fig.suptitle(f"Parallel Runtime Relative to Sequential Worst-Case, n={N}, c={ARBORICITY}, b={BATCHES}")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / ".matplotlib").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(args.output_dir / ".matplotlib"))
    require_dependencies()

    if args.trials <= 0:
        raise SystemExit("--trials must be positive")

    if not args.no_build:
        build_runner(PROJECT_ROOT, args.make_target)

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
    total = args.trials * (1 + len(args.threads))

    progress = tqdm(total=total, desc="Benchmarking relative runtime", unit="run")
    try:
        for trial in range(args.trials):
            time_ns = run_sequential_worst_case(
                runner,
                graph_file,
                scratch_dir,
                args.sequential_k,
                args.timeout_seconds,
            )
            raw_trials.append(
                {
                    "algorithm": "sequential_worst_case",
                    "threads": None,
                    "trial": trial,
                    "time_ns": time_ns,
                    "graph_file": str(graph_file),
                }
            )
            progress.update(1)

            for thread_count in args.threads:
                time_ns = run_parallel(
                    runner,
                    graph_file,
                    scratch_dir,
                    thread_count,
                    args.eps,
                    args.timeout_seconds,
                )
                raw_trials.append(
                    {
                        "algorithm": "parallel",
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
            "threads": args.threads,
            "trials": args.trials,
            "eps": args.eps,
            "sequential_k": args.sequential_k,
            "runner": str(runner),
            "graph_file": str(graph_file),
        },
        "raw_trials": raw_trials,
        "summaries": summaries,
    }

    json_path = args.output_dir / "relative_to_worst_case.json"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    plot_path = args.output_dir / "relative_to_worst_case.png"
    plot_results(summaries, args.threads, plot_path)

    print(f"Wrote JSON results to {json_path}")
    print(f"Wrote plot to {plot_path}")
    print("Summary:")
    print(f"  sequential_worst_case mean: {summaries['sequential_worst_case']['mean_time_seconds']:.6f}s")
    for thread_count in args.threads:
        key = f"parallel_t{thread_count}"
        if key not in summaries:
            continue
        summary = summaries[key]
        print(
            f"  parallel {thread_count} threads: "
            f"{summary['mean_time_seconds']:.6f}s, "
            f"ratio={summary['runtime_ratio_vs_sequential_worst_case']:.4f}, "
            f"speedup={summary['speedup_vs_sequential_worst_case']:.4f}"
        )


if __name__ == "__main__":
    main()
