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
ARBORICITIES = (4, 20)
BATCHES = (1, 10, 100)
TRIALS = 3
PARALLEL_THREADS = 8
EPSILON = 0.5
SEED = 0

TIME_RE = re.compile(r"Time taken \(ns\):\s*(\d+)")
MEAN_FLIPS_RE = re.compile(r"Mean flips:\s*([0-9.eE+-]+)")
MAX_FLIPS_RE = re.compile(r"Max flips:\s*(\d+)")
TOTAL_FLIPS_RE = re.compile(r"Total flips:\s*(\d+)")
FLIPPED_EDGES_RE = re.compile(r"Flipped edges:\s*(\d+)")

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
            "Benchmark instrumented parallel vs sequential worst-case flip counts "
            "on n=100000, c in {4,20}, across batch sizes."
        )
    )
    parser.add_argument("--benchmarks-dir", type=Path, default=PROJECT_ROOT / "benchmarks")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "benchmark_results" / "instrumented_flips")
    parser.add_argument("--runner", type=Path, default=PROJECT_ROOT / "run_graph_orientation_instrumented")
    parser.add_argument("--trials", type=int, default=TRIALS)
    parser.add_argument("--threads", type=int, default=PARALLEL_THREADS)
    parser.add_argument(
        "--sequential-k",
        type=int,
        help="Optional k for sequential_worst_case; defaults to the runner's ceil(log2 n).",
    )
    parser.add_argument("--eps", type=float, default=EPSILON)
    parser.add_argument("--make-target", default="run_graph_orientation_instrumented")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--timeout-seconds", type=float)
    return parser.parse_args()


def build_runner(project_dir: Path, make_target: str) -> None:
    subprocess.run(["make", make_target], cwd=project_dir, check=True)


def graph_path(benchmarks_dir: Path, arboricity: int, batches: int) -> Path:
    return benchmarks_dir / f"n{N}_c{arboricity}_b{batches}_s{SEED}.txt"


def parse_runner_output(stdout: str) -> Dict[str, Any]:
    time_match = TIME_RE.search(stdout)
    mean_match = MEAN_FLIPS_RE.search(stdout)
    max_match = MAX_FLIPS_RE.search(stdout)
    total_match = TOTAL_FLIPS_RE.search(stdout)
    flipped_edges_match = FLIPPED_EDGES_RE.search(stdout)
    if not time_match or not mean_match or not max_match:
        raise RuntimeError(f"Could not parse instrumented runner output:\n{stdout}")
    return {
        "time_ns": int(time_match.group(1)),
        "mean_flips": float(mean_match.group(1)),
        "max_flips": int(max_match.group(1)),
        "total_flips": int(total_match.group(1)) if total_match else None,
        "flipped_edges": int(flipped_edges_match.group(1)) if flipped_edges_match else None,
    }


def run_parallel(
    runner: Path,
    graph_file: Path,
    output_dir: Path,
    arboricity: int,
    threads: int,
    eps: float,
    timeout_seconds: float | None,
) -> Dict[str, Any]:
    fd, output_name = tempfile.mkstemp(prefix="parallel_", suffix=".oriented", dir=output_dir)
    os.close(fd)
    output_path = Path(output_name)
    try:
        cmd = [
            str(runner),
            str(graph_file),
            "parallel",
            str(output_path),
            "-c",
            str(arboricity),
            "-eps",
            str(eps),
        ]
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
        return parse_runner_output(completed.stdout)
    finally:
        output_path.unlink(missing_ok=True)


def run_sequential_worst_case(
    runner: Path,
    graph_file: Path,
    output_dir: Path,
    sequential_k: int | None,
    timeout_seconds: float | None,
) -> Dict[str, Any]:
    fd, output_name = tempfile.mkstemp(
        prefix="sequential_worst_case_", suffix=".oriented", dir=output_dir)
    os.close(fd)
    output_path = Path(output_name)
    try:
        cmd = [str(runner), str(graph_file), "sequential_worst_case", str(output_path)]
        if sequential_k is not None:
            cmd += ["-k", str(sequential_k)]
        completed = subprocess.run(
            cmd,
            cwd=runner.parent,
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        return parse_runner_output(completed.stdout)
    finally:
        output_path.unlink(missing_ok=True)


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.fmean(items) if items else float("nan")


def stdev(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.stdev(items) if len(items) > 1 else 0.0


def summarize(raw_trials: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[Tuple[int, int, str], List[Dict[str, Any]]] = {}
    for trial in raw_trials:
        key = (trial["arboricity"], trial["batches"], trial["algorithm"])
        grouped.setdefault(key, []).append(trial)

    summaries: Dict[str, Any] = {}
    for (arboricity, batches, algorithm), trials in grouped.items():
        key = f"c{arboricity}_b{batches}_{algorithm}"
        mean_flip_values = [trial["mean_flips"] for trial in trials]
        max_flip_values = [trial["max_flips"] for trial in trials]
        total_flip_values = [
            trial["total_flips"] for trial in trials if trial["total_flips"] is not None
        ]
        flipped_edge_values = [
            trial["flipped_edges"] for trial in trials if trial["flipped_edges"] is not None
        ]
        time_values = [trial["time_ns"] / 1e9 for trial in trials]
        summaries[key] = {
            "arboricity": arboricity,
            "n": N,
            "batches": batches,
            "algorithm": algorithm,
            "trials": len(trials),
            "mean_flips_mean": mean(mean_flip_values),
            "mean_flips_stdev": stdev(mean_flip_values),
            "max_flips_mean": mean(max_flip_values),
            "max_flips_max": max(max_flip_values),
            "total_flips_mean": mean(total_flip_values),
            "total_flips_stdev": stdev(total_flip_values),
            "flipped_edges_mean": mean(flipped_edge_values),
            "flipped_edges_stdev": stdev(flipped_edge_values),
            "time_seconds_mean": mean(time_values),
            "time_seconds_stdev": stdev(time_values),
        }
    return summaries


def plot_metric(
    summaries: Dict[str, Any],
    arboricities: List[int],
    batches: List[int],
    metric: str,
    ylabel: str,
    output_path: Path,
) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(arboricities), figsize=(5.8 * len(arboricities), 4.6), sharey=True)
    if len(arboricities) == 1:
        axes = [axes]

    for ax, arboricity in zip(axes, arboricities):
        for algorithm, label in (
            ("sequential_worst_case", "Sequential worst-case"),
            ("parallel", "Parallel"),
        ):
            xs = []
            ys = []
            for batch_count in batches:
                key = f"c{arboricity}_b{batch_count}_{algorithm}"
                if key not in summaries:
                    continue
                xs.append(batch_count)
                ys.append(summaries[key][metric])
            if xs:
                ax.plot(xs, ys, marker="o", label=label)
        ax.set_title(f"c={arboricity}, n={N}")
        ax.set_xlabel("Batches")
        ax.set_xticks(batches)
        ax.set_xscale("log")
        ax.grid(True, alpha=0.3)

    axes[0].set_ylabel(ylabel)
    handles, labels = axes[-1].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=len(labels))
    fig.tight_layout(rect=(0, 0, 1, 0.88))
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
        raise SystemExit(f"Instrumented runner not found: {runner}")

    jobs = []
    missing = []
    for arboricity in ARBORICITIES:
        for batch_count in BATCHES:
            path = graph_path(args.benchmarks_dir, arboricity, batch_count)
            if path.exists():
                jobs.append((arboricity, batch_count, path))
            else:
                missing.append(str(path))

    if not jobs:
        raise SystemExit("No matching benchmark files were found.")

    from tqdm import tqdm

    scratch_dir = args.output_dir / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    raw_trials: List[Dict[str, Any]] = []
    algorithms = ("sequential_worst_case", "parallel")
    total = len(jobs) * len(algorithms) * args.trials

    progress = tqdm(total=total, desc="Benchmarking instrumented flips", unit="run")
    try:
        for arboricity, batch_count, graph_file in jobs:
            for algorithm in algorithms:
                for trial in range(args.trials):
                    if algorithm == "parallel":
                        parsed = run_parallel(
                            runner,
                            graph_file,
                            scratch_dir,
                            arboricity,
                            args.threads,
                            args.eps,
                            args.timeout_seconds,
                        )
                    else:
                        parsed = run_sequential_worst_case(
                            runner,
                            graph_file,
                            scratch_dir,
                            args.sequential_k,
                            args.timeout_seconds,
                        )
                    raw_trials.append(
                        {
                            **parsed,
                            "algorithm": algorithm,
                            "arboricity": arboricity,
                            "n": N,
                            "batches": batch_count,
                            "seed": SEED,
                            "trial": trial,
                            "parallel_threads": args.threads if algorithm == "parallel" else None,
                            "sequential_k": args.sequential_k if algorithm == "sequential_worst_case" else None,
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
            "arboricities": list(ARBORICITIES),
            "batches": list(BATCHES),
            "seed": SEED,
            "trials": args.trials,
            "parallel_threads": args.threads,
            "sequential_k": args.sequential_k,
            "eps": args.eps,
            "runner": str(runner),
            "missing_files": missing,
        },
        "raw_trials": raw_trials,
        "summaries": summaries,
    }

    json_path = args.output_dir / "instrumented_flips.json"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    total_plot = args.output_dir / "total_flips_by_batches.png"
    mean_plot = args.output_dir / "mean_flips_per_flipped_edge_by_batches.png"
    max_plot = args.output_dir / "max_flips_per_edge_by_batches.png"
    plot_metric(
        summaries,
        list(ARBORICITIES),
        list(BATCHES),
        "total_flips_mean",
        "Total flips",
        total_plot,
    )
    plot_metric(
        summaries,
        list(ARBORICITIES),
        list(BATCHES),
        "mean_flips_mean",
        "Mean flips per flipped edge",
        mean_plot,
    )
    plot_metric(
        summaries,
        list(ARBORICITIES),
        list(BATCHES),
        "max_flips_mean",
        "Mean max flips per edge",
        max_plot,
    )

    print(f"Wrote JSON results to {json_path}")
    print(f"Wrote plot to {total_plot}")
    print(f"Wrote plot to {mean_plot}")
    print(f"Wrote plot to {max_plot}")
    if missing:
        print("Missing benchmark files were skipped:")
        for path in missing:
            print(f"  {path}")


if __name__ == "__main__":
    main()
