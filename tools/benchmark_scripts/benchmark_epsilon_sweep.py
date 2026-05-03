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


N = 1_000_000
ARBORICITY = 20
BATCHES = 10
SEED = 0
EPSILONS = (0.1, 0.5, 1.0)
THREADS = (1, 2, 4, 8)
TRIALS = 3

TIME_RE = re.compile(r"Time taken \(ns\):\s*(\d+)")
MAX_OUT_DEGREE_RE = re.compile(r"Max out-degree:\s*(\d+)")
AVG_OUT_DEGREE_RE = re.compile(r"Average out-degree:\s*([0-9.eE+-]+)")

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
            "Sweep epsilon for parallel orientation on n=1000000, c=20, b=10, "
            "and plot self-speedup plus orientation quality."
        )
    )
    parser.add_argument("--benchmarks-dir", type=Path, default=PROJECT_ROOT / "benchmarks")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "benchmark_results" / "epsilon_sweep")
    parser.add_argument("--runner", type=Path, default=PROJECT_ROOT / "run_graph_orientation")
    parser.add_argument("--epsilons", type=float, nargs="+", default=list(EPSILONS))
    parser.add_argument("--threads", type=int, nargs="+", default=list(THREADS))
    parser.add_argument("--trials", type=int, default=TRIALS)
    parser.add_argument("--make-target", default="run_graph_orientation")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--timeout-seconds", type=float)
    return parser.parse_args()


def build_runner(project_dir: Path, make_target: str) -> None:
    subprocess.run(["make", make_target], cwd=project_dir, check=True)


def graph_path(benchmarks_dir: Path) -> Path:
    return benchmarks_dir / f"n{N}_c{ARBORICITY}_b{BATCHES}_s{SEED}.txt"


def parse_runner_output(stdout: str) -> Dict[str, Any]:
    time_match = TIME_RE.search(stdout)
    max_match = MAX_OUT_DEGREE_RE.search(stdout)
    avg_match = AVG_OUT_DEGREE_RE.search(stdout)
    if not time_match or not max_match or not avg_match:
        raise RuntimeError(f"Could not parse runner output:\n{stdout}")
    return {
        "time_ns": int(time_match.group(1)),
        "max_out_degree": int(max_match.group(1)),
        "average_out_degree": float(avg_match.group(1)),
    }


def run_parallel(
    runner: Path,
    graph_file: Path,
    output_dir: Path,
    epsilon: float,
    threads: int,
    timeout_seconds: float | None,
) -> Dict[str, Any]:
    fd, output_name = tempfile.mkstemp(prefix="epsilon_sweep_", suffix=".oriented", dir=output_dir)
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
            str(epsilon),
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


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.fmean(items) if items else float("nan")


def stdev(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.stdev(items) if len(items) > 1 else 0.0


def epsilon_key(epsilon: float) -> str:
    return f"{epsilon:g}"


def summarize(raw_trials: List[Dict[str, Any]], epsilons: List[float], threads: List[int]) -> Dict[str, Any]:
    grouped: Dict[Tuple[float, int], List[Dict[str, Any]]] = {}
    for trial in raw_trials:
        grouped.setdefault((trial["epsilon"], trial["threads"]), []).append(trial)

    summaries: Dict[str, Any] = {}
    for epsilon in epsilons:
        eps_summary = {"epsilon": epsilon, "threads": {}}
        one_thread_time = None
        for thread_count in threads:
            trials = grouped.get((epsilon, thread_count), [])
            if not trials:
                continue
            times = [trial["time_ns"] / 1e9 for trial in trials]
            if thread_count == 1:
                one_thread_time = mean(times)
            eps_summary["threads"][str(thread_count)] = {
                "trials": len(trials),
                "mean_time_ns": int(round(mean(trial["time_ns"] for trial in trials))),
                "mean_time_seconds": mean(times),
                "stdev_time_seconds": stdev(times),
                "mean_max_out_degree": mean(trial["max_out_degree"] for trial in trials),
                "mean_average_out_degree": mean(trial["average_out_degree"] for trial in trials),
            }

        if one_thread_time is None:
            one_thread_entry = eps_summary["threads"].get("1")
            one_thread_time = one_thread_entry["mean_time_seconds"] if one_thread_entry else None
        for thread_count in threads:
            thread_data = eps_summary["threads"].get(str(thread_count))
            if thread_data is None:
                continue
            current = thread_data["mean_time_seconds"]
            thread_data["speedup_1_thread_over_n_threads"] = (
                one_thread_time / current if one_thread_time and current > 0 else float("nan")
            )
        summaries[epsilon_key(epsilon)] = eps_summary
    return summaries


def plot_speedup(summaries: Dict[str, Any], epsilons: List[float], threads: List[int], output_path: Path) -> None:
    import matplotlib.pyplot as plt

    plt.figure(figsize=(7.8, 5))
    for epsilon in epsilons:
        summary = summaries.get(epsilon_key(epsilon))
        if summary is None:
            continue
        xs = []
        ys = []
        for thread_count in threads:
            thread_data = summary["threads"].get(str(thread_count))
            if thread_data is None:
                continue
            xs.append(thread_count)
            ys.append(thread_data["speedup_1_thread_over_n_threads"])
        if xs:
            plt.plot(xs, ys, marker="o", label=f"eps={epsilon:g}")
    plt.title("Epsilon Sweep Self-Speedup")
    plt.xlabel("Threads")
    plt.ylabel("1-thread time / N-thread time")
    plt.xticks(threads)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def plot_quality_bars(summaries: Dict[str, Any], epsilons: List[float], output_path: Path) -> None:
    import matplotlib.pyplot as plt

    labels = [f"eps={epsilon:g}" for epsilon in epsilons]
    max_values = []
    avg_values = []
    for epsilon in epsilons:
        summary = summaries.get(epsilon_key(epsilon), {})
        thread_entries = summary.get("threads", {}).values()
        max_values.append(mean(entry["mean_max_out_degree"] for entry in thread_entries))
        avg_values.append(mean(entry["mean_average_out_degree"] for entry in thread_entries))

    x = list(range(len(epsilons)))
    width = 0.36
    fig, ax = plt.subplots(figsize=(7.8, 5))
    ax.bar([i - width / 2 for i in x], max_values, width=width, label="Max out-degree")
    ax.bar([i + width / 2 for i in x], avg_values, width=width, label="Average out-degree")
    ax.set_title("Orientation Quality by Epsilon")
    ax.set_xlabel("Epsilon")
    ax.set_ylabel("Out-degree")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend()
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
    if 1 not in args.threads:
        raise SystemExit("--threads must include 1 to compute self-speedup")

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
    total = len(args.epsilons) * len(args.threads) * args.trials
    progress = tqdm(total=total, desc="Benchmarking epsilon sweep", unit="run")
    try:
        for epsilon in args.epsilons:
            for thread_count in args.threads:
                for trial in range(args.trials):
                    parsed = run_parallel(
                        runner,
                        graph_file,
                        scratch_dir,
                        epsilon,
                        thread_count,
                        args.timeout_seconds,
                    )
                    raw_trials.append(
                        {
                            **parsed,
                            "epsilon": epsilon,
                            "threads": thread_count,
                            "trial": trial,
                            "n": N,
                            "arboricity": ARBORICITY,
                            "batches": BATCHES,
                            "seed": SEED,
                            "graph_file": str(graph_file),
                        }
                    )
                    progress.update(1)
    finally:
        progress.close()
        shutil.rmtree(scratch_dir, ignore_errors=True)

    summaries = summarize(raw_trials, args.epsilons, args.threads)
    results = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "n": N,
            "arboricity": ARBORICITY,
            "batches": BATCHES,
            "seed": SEED,
            "epsilons": args.epsilons,
            "threads": args.threads,
            "trials": args.trials,
            "runner": str(runner),
            "graph_file": str(graph_file),
        },
        "raw_trials": raw_trials,
        "summaries": summaries,
    }

    json_path = args.output_dir / "epsilon_sweep.json"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    speedup_plot = args.output_dir / "epsilon_sweep_speedup.png"
    quality_plot = args.output_dir / "epsilon_sweep_out_degree.png"
    plot_speedup(summaries, args.epsilons, args.threads, speedup_plot)
    plot_quality_bars(summaries, args.epsilons, quality_plot)

    print(f"Wrote JSON results to {json_path}")
    print(f"Wrote plot to {speedup_plot}")
    print(f"Wrote plot to {quality_plot}")


if __name__ == "__main__":
    main()
