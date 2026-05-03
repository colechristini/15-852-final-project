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
from typing import Any, Dict, Iterable, List, Optional, Tuple


THREAD_COUNTS = (1, 2, 4, 8)
BATCH_COUNTS = (1, 10, 100)
TIME_RE = re.compile(r"Time taken \(ns\):\s*(\d+)")
MAX_OUT_DEGREE_RE = re.compile(r"Max out-degree:\s*(\d+)")
AVG_OUT_DEGREE_RE = re.compile(r"Average out-degree:\s*([0-9.eE+-]+)")
GRAPH_RE = re.compile(r"n(?P<n>\d+)_c(?P<c>\d+)_b(?P<b>\d+)_s(?P<s>\d+)\.txt$")


def require_plotting_dependencies() -> None:
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
        joined = ", ".join(missing)
        raise SystemExit(
            f"Missing Python package(s): {joined}. Install them, then rerun this script."
        )


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark parallel graph orientation on arboricity-20 batched graphs "
            "and plot parallel self-speedup relative to the 1-thread run."
        )
    )
    parser.add_argument("--benchmarks-dir", type=Path, default=root / "benchmarks")
    parser.add_argument("--output-dir", type=Path, default=root / "benchmark_results" / "arboricity20_parallel")
    parser.add_argument("--runner", type=Path, default=root / "run_graph_orientation")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--threads", type=int, nargs="+", default=list(THREAD_COUNTS))
    parser.add_argument("--batches", type=int, nargs="+", default=list(BATCH_COUNTS))
    parser.add_argument("--arboricity", "-c", type=int, default=20)
    parser.add_argument("--eps", type=float, default=0.5)
    parser.add_argument("--make-target", default="run_graph_orientation")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--deterministic-sort", action="store_true")
    parser.add_argument("--hash-table", action="store_true")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        help="Optional per-run timeout for each runner invocation.",
    )
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        help="Optionally restrict to these input sizes.",
    )
    return parser.parse_args()


def benchmark_files(
    benchmarks_dir: Path,
    arboricity: int,
    batches: Iterable[int],
    sizes: Optional[Iterable[int]],
) -> List[Tuple[int, int, int, Path]]:
    wanted_batches = set(batches)
    wanted_sizes = set(sizes) if sizes else None
    files: List[Tuple[int, int, int, Path]] = []
    for path in benchmarks_dir.glob("*.txt"):
        match = GRAPH_RE.match(path.name)
        if not match:
            continue
        n = int(match.group("n"))
        c = int(match.group("c"))
        b = int(match.group("b"))
        seed = int(match.group("s"))
        if c != arboricity or b not in wanted_batches:
            continue
        if wanted_sizes is not None and n not in wanted_sizes:
            continue
        files.append((n, b, seed, path))
    return sorted(files, key=lambda row: (row[0], row[1], row[2], row[3].name))


def build_runner(project_dir: Path, make_target: str) -> None:
    subprocess.run(["make", make_target], cwd=project_dir, check=True)


def parse_runner_output(stdout: str) -> Dict[str, Any]:
    time_match = TIME_RE.search(stdout)
    if not time_match:
        raise RuntimeError(f"Could not parse timing from runner output:\n{stdout}")
    max_match = MAX_OUT_DEGREE_RE.search(stdout)
    avg_match = AVG_OUT_DEGREE_RE.search(stdout)
    return {
        "time_ns": int(time_match.group(1)),
        "max_out_degree": int(max_match.group(1)) if max_match else None,
        "average_out_degree": float(avg_match.group(1)) if avg_match else None,
    }


def run_one(
    runner: Path,
    graph_file: Path,
    algorithm: str,
    output_dir: Path,
    threads: Optional[int],
    arboricity: int,
    eps: float,
    deterministic_sort: bool,
    hash_table: bool,
    timeout_seconds: Optional[float],
) -> Dict[str, Any]:
    fd, output_name = tempfile.mkstemp(
        prefix=f"{algorithm}_", suffix=".oriented", dir=output_dir
    )
    os.close(fd)
    output_path = Path(output_name)
    try:
        cmd = [str(runner), str(graph_file), algorithm, str(output_path)]
        if algorithm == "parallel":
            cmd += ["-c", str(arboricity), "-eps", str(eps)]
            if deterministic_sort:
                cmd.append("--deterministic-sort")
            if hash_table:
                cmd.append("--hash-table")
        env = os.environ.copy()
        if threads is not None:
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
        parsed = parse_runner_output(completed.stdout)
        parsed["stdout"] = completed.stdout
        return parsed
    finally:
        output_path.unlink(missing_ok=True)


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.fmean(items) if items else float("nan")


def stdev(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.stdev(items) if len(items) > 1 else 0.0


def summarize_trials(trials: List[Dict[str, Any]]) -> Dict[str, Any]:
    seconds = [trial["time_ns"] / 1e9 for trial in trials]
    return {
        "trials": len(trials),
        "mean_time_ns": int(round(mean(trial["time_ns"] for trial in trials))),
        "mean_time_seconds": mean(seconds),
        "stdev_time_seconds": stdev(seconds),
        "min_time_seconds": min(seconds),
        "max_time_seconds": max(seconds),
        "mean_max_out_degree": mean(
            trial["max_out_degree"] for trial in trials if trial["max_out_degree"] is not None
        ),
        "mean_average_out_degree": mean(
            trial["average_out_degree"]
            for trial in trials
            if trial["average_out_degree"] is not None
        ),
    }


def aggregate(results: Dict[str, Any]) -> Dict[str, Any]:
    par_by_file: Dict[str, Dict[str, Any]] = {}

    for trial in results["raw_trials"]:
        key = f"{trial['graph_file']}|t{trial['threads']}"
        par_by_file.setdefault(key, {"metadata": trial, "trials": []})["trials"].append(trial)

    parallel_files = {
        key: summarize_trials(value["trials"]) | {
            "graph_file": value["metadata"]["graph_file"],
            "n": value["metadata"]["n"],
            "batches": value["metadata"]["batches"],
            "seed": value["metadata"]["seed"],
            "threads": value["metadata"]["threads"],
        }
        for key, value in par_by_file.items()
    }

    by_size_batch: Dict[str, Dict[str, Any]] = {}
    for (n, b) in sorted({(entry["n"], entry["batches"]) for entry in results["raw_trials"]}):
        key = f"n{n}_b{b}"
        one_thread_entries = [
            entry
            for entry in parallel_files.values()
            if entry["n"] == n and entry["batches"] == b and entry["threads"] == 1
        ]
        one_thread_time = mean(entry["mean_time_seconds"] for entry in one_thread_entries)
        thread_entries: Dict[str, Any] = {}
        for threads in results["config"]["threads"]:
            par_entries = [
                entry
                for entry in parallel_files.values()
                if entry["n"] == n and entry["batches"] == b and entry["threads"] == threads
            ]
            par_time = mean(entry["mean_time_seconds"] for entry in par_entries)
            thread_entries[str(threads)] = {
                "mean_time_seconds": par_time,
                "self_speedup_vs_1_thread": (
                    par_time / one_thread_time if one_thread_time > 0 and par_time > 0 else float("nan")
                ),
            }
        by_size_batch[key] = {
            "n": n,
            "batches": b,
            "one_thread_mean_time_seconds": one_thread_time,
            "parallel": thread_entries,
        }

    return {
        "parallel_by_file": parallel_files,
        "by_size_batch": by_size_batch,
    }


def plot_results(results: Dict[str, Any], output_dir: Path) -> List[str]:
    import matplotlib.pyplot as plt

    aggregate_data = results["aggregates"]["by_size_batch"]
    threads = results["config"]["threads"]
    batches = results["config"]["batches"]
    sizes = sorted({entry["n"] for entry in aggregate_data.values()})
    written: List[str] = []

    for n in sizes:
        plt.figure(figsize=(7.5, 5))
        for b in batches:
            key = f"n{n}_b{b}"
            if key not in aggregate_data:
                continue
            y = [
                aggregate_data[key]["parallel"][str(t)]["self_speedup_vs_1_thread"]
                for t in threads
            ]
            plt.plot(threads, y, marker="o", label=f"{b} batch{'es' if b != 1 else ''}")
        plt.title(f"Parallel Orientation Self-Speedup, n={n}, arboricity=20")
        plt.xlabel("Threads")
        plt.ylabel("Time ratio vs 1-thread parallel")
        plt.xticks(threads)
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        path = output_dir / f"speedup_n{n}.png"
        plt.savefig(path, dpi=200)
        plt.close()
        written.append(str(path))

    fig, axes = plt.subplots(1, len(batches), figsize=(5.5 * len(batches), 4.6), sharey=True)
    if len(batches) == 1:
        axes = [axes]
    for ax, b in zip(axes, batches):
        for t in threads:
            xs = []
            ys = []
            for n in sizes:
                key = f"n{n}_b{b}"
                if key in aggregate_data:
                    xs.append(n)
                    ys.append(aggregate_data[key]["parallel"][str(t)]["mean_time_seconds"])
            if xs:
                ax.plot(xs, ys, marker="o", label=f"{t} thread{'s' if t != 1 else ''}")
        ax.set_title(f"{b} batch{'es' if b != 1 else ''}")
        ax.set_xlabel("Input size n")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.grid(True, alpha=0.3)
    axes[0].set_ylabel("Parallel time (seconds)")
    handles, labels = axes[-1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=len(threads))
    fig.suptitle("Parallel Orientation Time by Input Size, arboricity=20")
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    path = output_dir / "parallel_time_by_size.png"
    fig.savefig(path, dpi=200)
    plt.close(fig)
    written.append(str(path))
    return written


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / ".matplotlib").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(args.output_dir / ".matplotlib"))
    require_plotting_dependencies()

    if args.trials <= 0:
        raise SystemExit("--trials must be positive")

    project_dir = Path(__file__).resolve().parent
    scratch_dir = args.output_dir / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    if not args.no_build:
        build_runner(project_dir, args.make_target)

    runner = args.runner.resolve()
    if not runner.exists():
        raise SystemExit(f"Runner not found: {runner}")

    files = benchmark_files(args.benchmarks_dir, args.arboricity, args.batches, args.sizes)
    if not files:
        raise SystemExit("No matching benchmark files found.")

    from tqdm import tqdm

    if 1 not in args.threads:
        raise SystemExit("--threads must include 1 to compute self-speedup")

    total_runs = len(files) * args.trials * len(args.threads)
    raw_trials: List[Dict[str, Any]] = []
    progress = tqdm(total=total_runs, desc="Benchmarking", unit="run")
    try:
        for n, b, seed, graph_file in files:
            for trial in range(args.trials):
                for threads in args.threads:
                    parsed = run_one(
                        runner,
                        graph_file,
                        "parallel",
                        scratch_dir,
                        threads,
                        args.arboricity,
                        args.eps,
                        args.deterministic_sort,
                        args.hash_table,
                        args.timeout_seconds,
                    )
                    raw_trials.append(
                        {
                            **parsed,
                            "algorithm": "parallel",
                            "threads": threads,
                            "trial": trial,
                            "n": n,
                            "batches": b,
                            "seed": seed,
                            "graph_file": str(graph_file),
                        }
                    )
                    progress.update(1)
    finally:
        progress.close()
        shutil.rmtree(scratch_dir, ignore_errors=True)

    results: Dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "trials": args.trials,
            "threads": args.threads,
            "batches": args.batches,
            "arboricity": args.arboricity,
            "eps": args.eps,
            "deterministic_sort": args.deterministic_sort,
            "hash_table": args.hash_table,
            "timeout_seconds": args.timeout_seconds,
            "runner": str(runner),
            "benchmark_files": [str(path) for _, _, _, path in files],
        },
        "raw_trials": raw_trials,
    }
    results["aggregates"] = aggregate(results)

    json_path = args.output_dir / "parallel_orientation_benchmark.json"
    write_json(json_path, results)
    plot_paths = plot_results(results, args.output_dir)

    print(f"Wrote JSON results to {json_path}")
    for path in plot_paths:
        print(f"Wrote plot to {path}")


if __name__ == "__main__":
    main()
