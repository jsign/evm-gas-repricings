import argparse
import os
import sys
import datetime
import warnings
import pandas as pd
from pathlib import Path

# Suppress warnings
warnings.filterwarnings("ignore", module="statsmodels")
warnings.filterwarnings("ignore", message="Tight layout not applied")
pd.options.mode.chained_assignment = None

sys.path.append(str(Path(__file__).parent))
import operation_types
from zkevm_data import (
    format_zkevm_validation_summary,
    prepare_zkevm_estimation_data,
    process_zkevm_data,
    validate_zkevm_estimation_data,
)
from reports import generate_repricings_report, generate_runtime_report
from glue import generate_glue_opcode_report


# Target opcodes: same as EIP-7904
SIMPLE_OPERATIONS = operation_types.SIMPLE_EIP_7904
VARIABLE_OPERATIONS = operation_types.VARIABLE_EIP_7904

PARAMS = [
    "num_rounds",
    "num_pairs",
    "msg_size",
]

PARAM_MULTIPLIERS = {
    "msg_size": 1 / 32.0,  # per word (32 bytes)
}


def write_text_file(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    # Usage: .venv/bin/python src/estimate_zkevm_repricings.py [--anchor-rate 12.5e6]
    #
    # Prerequisites:
    #   - Fixture JSON files in zkevm/fixtures/blockchain_tests/for_osaka_at_*/compute/
    #     (contain opcode traces for each test — used to count target opcode executions)
    #   - Run result JSON files in zkevm/runs/<EL-client>/<prover>/
    #     (contain proving times per test per client/prover combination)
    #
    # Output goes to reports/zkevm/<date>/ and includes:
    #   - gas_bench_data_raw.csv: all runs merged with trace opcode counts
    #   - gas_bench_data.csv: filtered to estimation-ready rows only
    #   - trace_data.csv: fixture trace data (opcode counts per test)
    #   - zkevm_excluded_rows.csv: rows removed during filtering (with reasons)
    #   - zkevm_validation_summary.md: data quality checks
    #   - runtime estimation report, glue opcode report, and repricing proposal

    parser = argparse.ArgumentParser(description="Estimate zkEVM gas repricings")
    parser.add_argument(
        "--anchor-rate",
        type=float,
        default=12.5e6,
        help="Anchor rate in gas/second (default: 12.5M)",
    )
    args = parser.parse_args()

    run_time = datetime.datetime.now()
    anchor_rate = args.anchor_rate

    # Output directory: reports/zkevm/<YYYY-MM-DD>/
    file_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.abspath(os.path.join(file_dir, ".."))
    out_dir = os.path.join(
        repo_dir,
        "reports",
        "zkevm",
        f"{run_time.strftime('%Y-%m-%d')}",
    )
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "figs"), exist_ok=True)

    # Step 1: Load and parse raw data
    # - Fixtures provide opcode execution traces (how many times each opcode runs per test)
    # - Runs provide proving times (how long each test took per EL-client/prover pair)
    # - These are merged on test_title to get: timing + opcount per run
    fixture_root = os.path.join(
        repo_dir, "zkevm", "fixtures", "blockchain_tests"
    )
    runs_root = os.path.join(repo_dir, "zkevm", "runs")

    raw_gas_bench_df, raw_trace_df = process_zkevm_data(fixture_root, runs_root)
    raw_gas_bench_df.to_csv(os.path.join(out_dir, "gas_bench_data_raw.csv"), index=False)

    # Step 2: Filter to estimation-ready data
    # Removes noncanonical benchmarks, unsupported opcodes, and rows with missing opcount
    candidate_target_ops = list(dict.fromkeys(SIMPLE_OPERATIONS + VARIABLE_OPERATIONS))
    gas_bench_df, trace_df, exclusions_df = prepare_zkevm_estimation_data(
        raw_gas_bench_df,
        raw_trace_df,
        candidate_target_ops,
    )

    gas_bench_df.to_csv(os.path.join(out_dir, "gas_bench_data.csv"), index=False)
    trace_df.to_csv(os.path.join(out_dir, "trace_data.csv"), index=False)
    exclusions_df.to_csv(os.path.join(out_dir, "zkevm_excluded_rows.csv"), index=False)

    # Step 3: Validate data quality before running regressions
    validation = validate_zkevm_estimation_data(
        gas_bench_df,
        candidate_target_ops,
        PARAMS,
    )
    summary_text = format_zkevm_validation_summary(validation, exclusions_df)
    summary_path = os.path.join(out_dir, "zkevm_validation_summary.md")
    write_text_file(summary_path, summary_text)

    if gas_bench_df.empty:
        raise SystemExit(
            "zkEVM estimation dataset is empty after filtering. "
            f"See {summary_path}."
        )
    if not validation["is_valid"]:
        raise SystemExit(
            "zkEVM estimation data failed validation. "
            f"See {summary_path}."
        )

    # Step 4: Determine clients, date range, and operation lists from filtered data
    all_clients = set(gas_bench_df["client_name"].unique())
    print(f"Detected clients: {all_clients}")

    start_date = gas_bench_df["ingestion_timestamp"].min().strftime("%Y-%m-%d")
    end_date = gas_bench_df["ingestion_timestamp"].max().strftime("%Y-%m-%d")

    available_opcodes = set(gas_bench_df["test_opcode"].dropna().unique())
    simple_ops = [op for op in SIMPLE_OPERATIONS if op in available_opcodes]
    variable_ops = [op for op in VARIABLE_OPERATIONS if op in available_opcodes]
    all_target_ops = simple_ops + variable_ops

    print(f"Simple operations ({len(simple_ops)}): {simple_ops}")
    print(f"Variable operations ({len(variable_ops)}): {variable_ops}")
    if not exclusions_df.empty:
        print("Excluded rows by reason:")
        print(exclusions_df["exclude_reason"].value_counts().sort_index().to_string())

    # Step 5: Generate reports
    # - Runtime report: NNLS regression to estimate per-opcode proving times
    # - Glue report: estimates overhead from helper opcodes (PUSH, POP, etc.)
    # - Repricing report: converts runtimes to gas costs using the anchor rate
    generate_runtime_report(
        start_date=start_date,
        end_date=end_date,
        eip_number="zkevm",
        gas_bench_df=gas_bench_df,
        out_dir=out_dir,
        params=PARAMS,
        operations=all_target_ops,
    )

    generate_glue_opcode_report(
        start_date=start_date,
        end_date=end_date,
        eip_number="zkevm",
        gas_bench_df=raw_gas_bench_df,
        trace_df=raw_trace_df,
        out_dir=out_dir,
        target_opcodes=all_target_ops,
    )

    generate_repricings_report(
        start_date=start_date,
        end_date=end_date,
        out_dir=out_dir,
        anchor_rate=anchor_rate,
        eip_number="zkevm",
        params=PARAMS,
        params_multipliers=PARAM_MULTIPLIERS,
        target_operations=all_target_ops,
        all_clients=all_clients,
    )
