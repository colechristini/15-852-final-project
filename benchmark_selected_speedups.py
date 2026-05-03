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
BATCHES = (1, 10, 100)
TRIALS = 3
EPSILON = 0.5
TIME_RE = re.compile(r"Time taken \(ns\):\s*(\d+)")

HIGH_ARBORICITY_CASES = (
    (13, 10_000),
    (17, 100_000),
    (20, 1_000_000),
)
LOW_ARBORICITY_CASES = (
    (3, 10_000),
    (4, 100_000),
    (4, 1_000_000),
)


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
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description=(
            "Run selected s0 parallel-orientation benchmarks and plot time ratios "
            "for N-thread runs relative to the 1-thread run."
        )
    )
    parser.add_argument("--benchmarks-dir", type=Path, default=root / "benchmarks")
    parser.add_argument("--output-dir", type=Path, default=root / "benchmark_results" / "selected_speedups")
    parser.add_argument("--runner", type=Path, default=root / "run_graph_orientation")
    parser.add_argument("--threads", type=int, nargs="+", default=list(THREADS))
    parser.add_argument("--batches", type=int, nargs="+", default=list(BATCHES))
    parser.add_argument("--trials", type=int, default=TRIALS)
    parser.add_argument("--eps", type=float, default=EPSILON)
    parser.add_argument("--make-target", default="run_graph_orientation")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--deterministic-sort", action="store_true")
    parser.add_argument("--hash-table", action="store_true")
    parser.add_argument("--timeout-seconds", type=float)
    return parser.parse_args()


def build_runner(project_dir: Path, make_target: str) -> None:
    subprocess.run(["make", make_target], cwd=project_dir, check=True)


def graph_path(benchmarks_dir: Path, arboricity: int, n: int, batches: int) -> Path:
    return benchmarks_dir / f"n{n}_c{arboricity}_b{batches}_s0.txt"


def parse_time_ns(stdout: str) -> int:
    match = TIME_RE.search(stdout)
    if not match:
        raise RuntimeError(f"Could not parse timing from runner output:\n{stdout}")
    return int(match.group(1))


def run_parallel(
    runner: Path,
    graph_file: Path,
    output_dir: Path,
    threads: int,
    arboricity: int,
    eps: float,
    deterministic_sort: bool,
    hash_table: bool,
    timeout_seconds: float | None,
) -> int:
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
        if deterministic_sort:
            cmd.append("--deterministic-sort")
        if hash_table:
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


def summarize(raw_trials: List[Dict[str, Any]], threads: List[int]) -> Dict[str, Any]:
    grouped: Dict[Tuple[int, int, int], List[int]] = {}
    for trial in raw_trials:
        key = (trial["arboricity"], trial["n"], trial["batches"], trial["threads"])
        grouped.setdefault(key, []).append(trial["time_ns"])

    summaries: Dict[str, Any] = {}
    for (arboricity, n, batches, thread_count), times in grouped.items():
        case_key = f"c{arboricity}_n{n}_b{batches}"
        summaries.setdefault(
            case_key,
            {
                "arboricity": arboricity,
                "n": n,
                "batches": batches,
                "threads": {},
            },
        )
        mean_seconds = mean(t / 1e9 for t in times)
        summaries[case_key]["threads"][str(thread_count)] = {
            "trials": len(times),
            "mean_time_ns": int(round(mean(times))),
            "mean_time_seconds": mean_seconds,
        }

    for summary in summaries.values():
        one_thread = summary["threads"].get("1", {}).get("mean_time_seconds")
        for thread_count in threads:
            thread_data = summary["threads"].get(str(thread_count))
            if thread_data is None:
                continue
            current = thread_data["mean_time_seconds"]
            thread_data["time_ratio_vs_1_thread"] = (
                current / one_thread if one_thread and current > 0 else float("nan")
            )
    return summaries


def series_for_case(
    summaries: Dict[str, Any],
    arboricity: int,
    n: int,
    batches: List[int],
    threads: List[int],
) -> List[Tuple[int, List[int], List[float]]]:
    series = []
    for batch_count in batches:
        key = f"c{arboricity}_n{n}_b{batch_count}"
        if key not in summaries:
            continue
        xs = []
        ys = []
        for thread_count in threads:
            thread_data = summaries[key]["threads"].get(str(thread_count))
            if thread_data is None:
                continue
            xs.append(thread_count)
            ys.append(thread_data["time_ratio_vs_1_thread"])
        if xs:
            series.append((batch_count, xs, ys))
    return series


def plot_case(
    summaries: Dict[str, Any],
    arboricity: int,
    n: int,
    batches: List[int],
    threads: List[int],
    output_path: Path,
) -> None:
    import matplotlib.pyplot as plt

    plt.figure(figsize=(7.2, 4.8))
    for batch_count, xs, ys in series_for_case(summaries, arboricity, n, batches, threads):
        plt.plot(xs, ys, marker="o", label=f"{batch_count} batch{'es' if batch_count != 1 else ''}")
    plt.title(f"Parallel Time Ratio, c={arboricity}, n={n}")
    plt.xlabel("Threads")
    plt.ylabel("N-thread time / 1-thread time")
    plt.xticks(threads)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def plot_group(
    summaries: Dict[str, Any],
    cases: Tuple[Tuple[int, int], ...],
    batches: List[int],
    threads: List[int],
    title: str,
    output_path: Path,
) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(cases), figsize=(5.3 * len(cases), 4.6), sharey=True)
    if len(cases) == 1:
        axes = [axes]

    for ax, (arboricity, n) in zip(axes, cases):
        for batch_count, xs, ys in series_for_case(summaries, arboricity, n, batches, threads):
            ax.plot(xs, ys, marker="o", label=f"{batch_count} batch{'es' if batch_count != 1 else ''}")
        ax.set_title(f"c={arboricity}, n={n}")
        ax.set_xlabel("Threads")
        ax.set_xticks(threads)
        ax.grid(True, alpha=0.3)

    axes[0].set_ylabel("N-thread time / 1-thread time")
    handles, labels = axes[-1].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=max(1, len(labels)))
    fig.suptitle(title)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
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
    if 1 not in args.threads:
        raise SystemExit("--threads must include 1")

    project_dir = Path(__file__).resolve().parent
    if not args.no_build:
        build_runner(project_dir, args.make_target)

    runner = args.runner.resolve()
    if not runner.exists():
        raise SystemExit(f"Runner not found: {runner}")

    all_cases = HIGH_ARBORICITY_CASES + LOW_ARBORICITY_CASES
    jobs: List[Tuple[int, int, int, Path]] = []
    missing: List[str] = []
    for arboricity, n in all_cases:
        for batch_count in args.batches:
            path = graph_path(args.benchmarks_dir, arboricity, n, batch_count)
            if path.exists():
                jobs.append((arboricity, n, batch_count, path))
            else:
                missing.append(str(path))

    if not jobs:
        raise SystemExit("No selected s0 benchmark files were found.")

    from tqdm import tqdm

    scratch_dir = args.output_dir / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    raw_trials: List[Dict[str, Any]] = []
    total = len(jobs) * args.trials * len(args.threads)

    progress = tqdm(total=total, desc="Benchmarking selected graphs", unit="run")
    try:
        for arboricity, n, batch_count, graph_file in jobs:
            for trial in range(args.trials):
                for thread_count in args.threads:
                    time_ns = run_parallel(
                        runner,
                        graph_file,
                        scratch_dir,
                        thread_count,
                        arboricity,
                        args.eps,
                        args.deterministic_sort,
                        args.hash_table,
                        args.timeout_seconds,
                    )
                    raw_trials.append(
                        {
                            "arboricity": arboricity,
                            "n": n,
                            "batches": batch_count,
                            "seed": 0,
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

    summaries = summarize(raw_trials, args.threads)
    results = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "trials": args.trials,
            "threads": args.threads,
            "batches": args.batches,
            "eps": args.eps,
            "seed": 0,
            "runner": str(runner),
            "missing_files": missing,
        },
        "raw_trials": raw_trials,
        "summaries": summaries,
    }

    json_path = args.output_dir / "selected_speedups.json"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    case_plots = []
    for arboricity, n in all_cases:
        output_path = args.output_dir / f"c{arboricity}_n{n}_time_ratio.png"
        plot_case(summaries, arboricity, n, args.batches, args.threads, output_path)
        case_plots.append(output_path)

    high_plot = args.output_dir / "high_arboricity_time_ratio.png"
    low_plot = args.output_dir / "low_arboricity_time_ratio.png"
    plot_group(
        summaries,
        HIGH_ARBORICITY_CASES,
        args.batches,
        args.threads,
        "O(log n) Arboricity Parallel Speedup",
        high_plot,
    )
    plot_group(
        summaries,
        LOW_ARBORICITY_CASES,
        args.batches,
        args.threads,
        "O(log log n) Arboricity Speedup",
        low_plot,
    )

    print(f"Wrote JSON results to {json_path}")
    for path in case_plots:
        print(f"Wrote plot to {path}")
    print(f"Wrote plot to {high_plot}")
    print(f"Wrote plot to {low_plot}")
    if missing:
        print("Missing selected s0 files were skipped:")
        for path in missing:
            print(f"  {path}")


if __name__ == "__main__":
    main()
