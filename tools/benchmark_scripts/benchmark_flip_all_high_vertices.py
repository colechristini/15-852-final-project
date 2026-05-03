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
BATCHES = (1, 10, 100)
THREADS = (1, 2, 4, 8)
TRIALS = 3
EPSILON = 0.5
SEED = 0

TIME_RE = re.compile(r"Time taken \(ns\):\s*(\d+)")
MAX_OUT_DEGREE_RE = re.compile(r"Max out-degree:\s*(\d+)")
AVG_OUT_DEGREE_RE = re.compile(r"Average out-degree:\s*([0-9.eE+-]+)")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]

VARIANTS = (
    {"name": "baseline", "label": "Baseline", "extra_args": []},
    {"name": "flip_all_high_vertices", "label": "Flip all high vertices", "extra_args": ["--flip-all-high-vertices"]},
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
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark baseline parallel vs flip-all-high-vertices on n100000_c20 "
            "across batch sizes and thread counts."
        )
    )
    parser.add_argument("--benchmarks-dir", type=Path, default=PROJECT_ROOT / "benchmarks")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "benchmark_results" / "flip_all_high_vertices")
    parser.add_argument("--runner", type=Path, default=PROJECT_ROOT / "run_graph_orientation")
    parser.add_argument("--threads", type=int, nargs="+", default=list(THREADS))
    parser.add_argument("--batches", type=int, nargs="+", default=list(BATCHES))
    parser.add_argument("--trials", type=int, default=TRIALS)
    parser.add_argument("--eps", type=float, default=EPSILON)
    parser.add_argument("--make-target", default="run_graph_orientation")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--timeout-seconds", type=float)
    return parser.parse_args()


def build_runner(project_dir: Path, make_target: str) -> None:
    subprocess.run(["make", make_target], cwd=project_dir, check=True)


def graph_path(benchmarks_dir: Path, batches: int) -> Path:
    return benchmarks_dir / f"n{N}_c{ARBORICITY}_b{batches}_s{SEED}.txt"


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
    variant: Dict[str, Any],
    threads: int,
    eps: float,
    timeout_seconds: float | None,
) -> Dict[str, Any]:
    fd, output_name = tempfile.mkstemp(prefix=f"{variant['name']}_", suffix=".oriented", dir=output_dir)
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
            *variant["extra_args"],
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


def summarize(raw_trials: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[Tuple[int, str, int], List[Dict[str, Any]]] = {}
    for trial in raw_trials:
        grouped.setdefault((trial["batches"], trial["variant"], trial["threads"]), []).append(trial)

    summaries: Dict[str, Any] = {}
    for (batches, variant, threads), trials in grouped.items():
        key = f"b{batches}_{variant}_t{threads}"
        times = [trial["time_ns"] / 1e9 for trial in trials]
        summaries[key] = {
            "batches": batches,
            "variant": variant,
            "threads": threads,
            "trials": len(trials),
            "mean_time_ns": int(round(mean(trial["time_ns"] for trial in trials))),
            "mean_time_seconds": mean(times),
            "stdev_time_seconds": stdev(times),
            "mean_max_out_degree": mean(trial["max_out_degree"] for trial in trials),
            "mean_average_out_degree": mean(trial["average_out_degree"] for trial in trials),
        }

    for batches in sorted({trial["batches"] for trial in raw_trials}):
        for variant in {trial["variant"] for trial in raw_trials}:
            one_thread = summaries.get(f"b{batches}_{variant}_t1", {}).get("mean_time_seconds")
            for threads in {trial["threads"] for trial in raw_trials}:
                key = f"b{batches}_{variant}_t{threads}"
                if key not in summaries:
                    continue
                current = summaries[key]["mean_time_seconds"]
                summaries[key]["speedup_1_thread_over_n_threads"] = (
                    one_thread / current if one_thread and current > 0 else float("nan")
                )
    return summaries


def plot_batch_scaling(
    summaries: Dict[str, Any],
    batches: int,
    threads: List[int],
    output_path: Path,
) -> None:
    import matplotlib.pyplot as plt

    plt.figure(figsize=(7.6, 5))
    for variant in VARIANTS:
        xs = []
        ys = []
        for thread_count in threads:
            key = f"b{batches}_{variant['name']}_t{thread_count}"
            if key not in summaries:
                continue
            xs.append(thread_count)
            ys.append(summaries[key]["speedup_1_thread_over_n_threads"])
        if xs:
            plt.plot(xs, ys, marker="o", label=variant["label"])
    plt.title(f"Scaling, b={batches}, n={N}, c={ARBORICITY}")
    plt.xlabel("Threads")
    plt.ylabel("1-thread time / N-thread time")
    plt.xticks(threads)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def plot_all_scaling(
    summaries: Dict[str, Any],
    batches: List[int],
    threads: List[int],
    output_path: Path,
) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(batches), figsize=(5.3 * len(batches), 4.8), sharey=True)
    if len(batches) == 1:
        axes = [axes]
    for ax, batch_count in zip(axes, batches):
        for variant in VARIANTS:
            xs = []
            ys = []
            for thread_count in threads:
                key = f"b{batch_count}_{variant['name']}_t{thread_count}"
                if key not in summaries:
                    continue
                xs.append(thread_count)
                ys.append(summaries[key]["speedup_1_thread_over_n_threads"])
            if xs:
                ax.plot(xs, ys, marker="o", label=variant["label"])
        ax.set_title(f"b={batch_count}")
        ax.set_xlabel("Threads")
        ax.set_xticks(threads)
        ax.grid(True, alpha=0.3)
    axes[0].set_ylabel("1-thread time / N-thread time")
    handles, labels = axes[-1].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=len(labels))
    fig.suptitle(f"Scaling by Batch Size, n={N}, c={ARBORICITY}")
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_max_degree_comparison(
    summaries: Dict[str, Any],
    batches: List[int],
    threads: List[int],
    output_path: Path,
) -> None:
    import matplotlib.pyplot as plt

    labels = [str(batch_count) for batch_count in batches]
    x = list(range(len(batches)))
    width = 0.36
    fig, ax = plt.subplots(figsize=(7.8, 5))
    for offset, variant in ((-width / 2, VARIANTS[0]), (width / 2, VARIANTS[1])):
        values = []
        for batch_count in batches:
            degree_values = [
                summaries[f"b{batch_count}_{variant['name']}_t{thread_count}"]["mean_max_out_degree"]
                for thread_count in threads
                if f"b{batch_count}_{variant['name']}_t{thread_count}" in summaries
            ]
            values.append(mean(degree_values))
        ax.bar([i + offset for i in x], values, width=width, label=variant["label"])
    ax.set_title(f"Max Out-Degree by Batch Size, n={N}, c={ARBORICITY}")
    ax.set_xlabel("Batches")
    ax.set_ylabel("Mean max out-degree across thread counts")
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
        raise SystemExit("--threads must include 1 to compute scaling")

    if not args.no_build:
        build_runner(PROJECT_ROOT, args.make_target)

    runner = args.runner.resolve()
    if not runner.exists():
        raise SystemExit(f"Runner not found: {runner}")

    jobs = []
    missing = []
    for batch_count in args.batches:
        path = graph_path(args.benchmarks_dir, batch_count)
        if path.exists():
            jobs.append((batch_count, path))
        else:
            missing.append(str(path))
    if not jobs:
        raise SystemExit("No matching benchmark files were found.")

    from tqdm import tqdm

    scratch_dir = args.output_dir / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    raw_trials: List[Dict[str, Any]] = []
    total = len(jobs) * len(VARIANTS) * len(args.threads) * args.trials
    progress = tqdm(total=total, desc="Benchmarking flip-all high vertices", unit="run")
    try:
        for batch_count, graph_file in jobs:
            for variant in VARIANTS:
                for thread_count in args.threads:
                    for trial in range(args.trials):
                        parsed = run_parallel(
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
                                **parsed,
                                "variant": variant["name"],
                                "variant_label": variant["label"],
                                "threads": thread_count,
                                "trial": trial,
                                "n": N,
                                "arboricity": ARBORICITY,
                                "batches": batch_count,
                                "seed": SEED,
                                "eps": args.eps,
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
            "batches": args.batches,
            "threads": args.threads,
            "trials": args.trials,
            "eps": args.eps,
            "seed": SEED,
            "runner": str(runner),
            "missing_files": missing,
        },
        "variants": list(VARIANTS),
        "raw_trials": raw_trials,
        "summaries": summaries,
    }
    json_path = args.output_dir / "flip_all_high_vertices.json"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    plots = []
    for batch_count in args.batches:
        path = args.output_dir / f"scaling_b{batch_count}.png"
        plot_batch_scaling(summaries, batch_count, args.threads, path)
        plots.append(path)
    all_scaling_plot = args.output_dir / "scaling_all_batches.png"
    max_degree_plot = args.output_dir / "max_degree_by_batch.png"
    plot_all_scaling(summaries, args.batches, args.threads, all_scaling_plot)
    plot_max_degree_comparison(summaries, args.batches, args.threads, max_degree_plot)
    plots.extend([all_scaling_plot, max_degree_plot])

    print(f"Wrote JSON results to {json_path}")
    for path in plots:
        print(f"Wrote plot to {path}")
    if missing:
        print("Missing benchmark files were skipped:")
        for path in missing:
            print(f"  {path}")


if __name__ == "__main__":
    main()
