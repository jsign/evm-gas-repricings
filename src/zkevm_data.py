import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

sys.path.append(str(Path(__file__).parent))
from data import (
    OPCODES_IN_TEST_NAME_LIST,
    add_opcount_col,
    extract_param_values,
    get_current_gas_cost,
    process_compute_params,
)

_FIXTURE_PREFIX_RE = re.compile(
    r"^tests/benchmark/compute/(?:instruction|precompile|scenario)/"
)
_CLIENT_NAME_SEPARATOR = "__"
_TRACE_COLUMN_ALIASES = {
    "SHA3": "KECCAK256",
}
_NONCANONICAL_COMPUTE_PREFIXES = (
    "test_storage_access_",
    "test_block_",
)
_NONCANONICAL_COMPUTE_TESTS = {
    "test_auth_transaction",
    "test_empty_block",
}


def _extract_zkevm_test_params(bracket_content: str) -> str:
    """Extract normalized test params from a zkEVM benchmark title."""
    test_params = ""
    if "blockchain_test-" not in bracket_content:
        return test_params

    after_blockchain = bracket_content.split("blockchain_test-")[1]
    if after_blockchain.startswith("benchmark"):
        before_benchmark = ""
    else:
        before_benchmark = after_blockchain.split("-benchmark")[0]
    parts = before_benchmark.split("-")
    filtered = [
        item
        for item in parts
        if item[:6] not in ("opcode", "opcoun", "", "benchm")
    ]
    return "-".join(filtered)


def _infer_zkevm_test_opcode(
    test_name: str,
    test_title: str,
    test_params: str,
) -> str:
    """Infer a canonical opcode name from a zkEVM benchmark title."""
    if test_name == "test_jumpis":
        return "JUMPI"
    if test_name == "test_jumps":
        return "JUMP"
    if test_name.startswith("test_keccak"):
        return "KECCAK256"
    if test_name.startswith("test_sha256"):
        return "SHA2-256"
    if test_name.startswith("test_ripemd"):
        return "RIPEMD-160"
    if test_name == "test_alt_bn128":
        if "bn128_add" in test_params:
            return "ECADD"
        if "bn128_mul" in test_params:
            return "ECMUL"
        if "pair" in test_params:
            return "ECPAIRING"
    if test_name == "test_bn128_pairings_amortized":
        return "ECPAIRING"

    if test_name in OPCODES_IN_TEST_NAME_LIST:
        return test_name.split("_")[1].upper()
    if "opcode_" in test_title:
        return test_title.split("opcode_")[1].split("-")[0].split("]")[0]

    raw = test_name.replace("test_", "")
    return raw.split("_")[0].upper()


def parse_zkevm_test_title(test_title: str) -> dict:
    """Parse a zkEVM test title into canonical pipeline fields."""
    test_file = test_title.split(".py")[0]
    test_name = test_title.split(".py::")[1].split("[")[0]
    bracket_content = test_title.split("[")[1].rstrip("]")

    gas_match = re.search(r"gas-value_(\d+)M", bracket_content)
    block_limit_million = gas_match.group(1) if gas_match else None
    test_params = _extract_zkevm_test_params(bracket_content)
    test_opcode = _infer_zkevm_test_opcode(test_name, test_title, test_params)

    return {
        "test_file": test_file,
        "test_name": test_name,
        "test_opcode": test_opcode,
        "test_params": test_params,
        "block_limit_million": block_limit_million,
    }


def _normalize_trace_opcode_columns(prev_df: pd.DataFrame) -> pd.DataFrame:
    """Rename trace opcode columns to the canonical names used by the pipeline."""
    df = prev_df.copy()
    for source_col, target_col in _TRACE_COLUMN_ALIASES.items():
        if source_col not in df.columns:
            continue
        if target_col in df.columns:
            df[target_col] = df[target_col].where(df[target_col].notna(), df[source_col])
        else:
            df[target_col] = df[source_col]
        df = df.drop(columns=[source_col])
    return df


def _normalize_zkevm_param_names(prev_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize zkEVM parameter names to the shared pipeline conventions."""
    df = prev_df.copy()
    df["test_params"] = df["test_params"].fillna("").str.replace(
        r"\bsize_", "msg_size_", regex=True
    )
    return df


def _extract_fixture_opcode_count(test_data: dict) -> dict:
    """Read opcode counts from the supported zkEVM fixture schemas."""
    if not isinstance(test_data, dict):
        return {}

    info = test_data.get("_info", {})
    if not isinstance(info, dict):
        return {}

    metadata = info.get("metadata", {})
    if isinstance(metadata, dict):
        opcode_count = metadata.get("opcode_count", {})
        if isinstance(opcode_count, dict) and opcode_count:
            return opcode_count

    opcode_count = info.get("opcode_count", {})
    if isinstance(opcode_count, dict):
        return opcode_count
    return {}


def load_zkevm_fixtures(fixture_root: str) -> pd.DataFrame:
    """Load fixture traces into a canonicalized trace DataFrame."""
    rows = []
    for json_file in sorted(Path(fixture_root).rglob("*.json")):
        try:
            with open(json_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for test_key, test_data in data.items():
            if not isinstance(test_data, dict):
                continue
            opcode_count = _extract_fixture_opcode_count(test_data)
            if not opcode_count:
                continue
            short_name = _FIXTURE_PREFIX_RE.sub("", test_key)
            parsed = parse_zkevm_test_title(short_name)
            row = {"test_title": short_name, **parsed, **opcode_count}
            rows.append(row)
    return pd.DataFrame(rows)


def _infer_run_gas_limit(test_title: str) -> str:
    """Infer the gas limit used by a run for crash summaries."""
    try:
        inferred = parse_zkevm_test_title(test_title)["block_limit_million"]
    except (AttributeError, IndexError, KeyError):
        inferred = None
    return inferred or "unknown"


def load_zkevm_runs(runs_root: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load successful and crashed zkEVM run JSONs from the flat run layout."""
    rows = []
    crash_rows = []
    runs_path = Path(runs_root)

    for client_dir in sorted(runs_path.iterdir()):
        if not client_dir.is_dir():
            continue
        client = client_dir.name

        for prover_dir in sorted(client_dir.iterdir()):
            if not prover_dir.is_dir():
                continue
            prover = prover_dir.name
            client_name = f"{client}{_CLIENT_NAME_SEPARATOR}{prover}"

            for json_file in sorted(prover_dir.glob("*.json")):
                try:
                    with open(json_file) as f:
                        data = json.load(f)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                proving = data.get("proving", {})
                test_title = data.get("name", json_file.stem)
                if "crashed" in proving:
                    crash_rows.append(
                        {
                            "client_name": client_name,
                            "gas_limit": _infer_run_gas_limit(test_title),
                            "test_name": test_title,
                            "reason": proving["crashed"].get("reason", "unknown"),
                        }
                    )
                    continue
                if "success" not in proving:
                    continue

                rows.append(
                    {
                        "test_title": test_title,
                        "client_name": client_name,
                        "run_duration_ms": proving["success"]["proving_time_ms"],
                        "ingestion_timestamp": data.get("timestamp_completed"),
                    }
                )

    runs_df = pd.DataFrame(rows)
    crash_df = pd.DataFrame(crash_rows)

    if not crash_df.empty:
        print("\nCrash summary:")
        summary = (
            crash_df.groupby(["client_name", "gas_limit"])
            .size()
            .reset_index(name="count")
        )
        print(summary.to_string(index=False))
        print()

    return runs_df, crash_df


def process_zkevm_data(
    fixture_root: str, runs_root: str
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load canonicalized zkEVM fixtures and runs into pipeline-shaped frames."""
    print("Loading zkEVM fixtures...")
    trace_df = load_zkevm_fixtures(fixture_root)
    if trace_df.empty:
        raise ValueError(
            "No usable zkEVM fixture traces were loaded. "
            "Expected opcode counts under _info.metadata.opcode_count "
            f"or legacy _info.opcode_count in fixture JSONs under {fixture_root}."
        )
    trace_df = process_compute_params(trace_df)
    trace_df = _normalize_trace_opcode_columns(trace_df)
    trace_df = _normalize_zkevm_param_names(trace_df)
    trace_df = add_opcount_col(trace_df)
    print(f"  Loaded {len(trace_df)} fixture entries")

    print("Loading zkEVM runs...")
    runs_df, crash_df = load_zkevm_runs(runs_root)
    if runs_df.empty:
        raise ValueError(
            "No usable zkEVM run results were loaded. "
            "Expected JSON runs in "
            f"{runs_root}/<client>/<prover>/ with proving.success or proving.crashed data."
        )
    print(f"  Loaded {len(runs_df)} successful runs ({len(crash_df)} crashed)")

    parsed_df = pd.DataFrame(runs_df["test_title"].apply(parse_zkevm_test_title).tolist())
    for col in parsed_df.columns:
        runs_df[col] = parsed_df[col]
    runs_df = process_compute_params(runs_df)
    runs_df = _normalize_zkevm_param_names(runs_df)

    if "ingestion_timestamp" in runs_df.columns:
        runs_df["ingestion_timestamp"] = pd.to_datetime(runs_df["ingestion_timestamp"])

    gas_bench_df = runs_df.merge(
        trace_df[["test_title", "opcount"]],
        on="test_title",
        how="inner",
    )
    print(f"  Merged: {len(gas_bench_df)} rows in gas_bench_df")

    return gas_bench_df, trace_df


def _is_noncanonical_compute_benchmark(test_name: str) -> bool:
    return test_name.startswith(_NONCANONICAL_COMPUTE_PREFIXES) or (
        test_name in _NONCANONICAL_COMPUTE_TESTS
    )


def _classify_zkevm_exclusion(
    row: pd.Series,
    target_operations: set[str],
) -> str | None:
    test_name = row["test_name"]
    test_opcode = row["test_opcode"]

    if _is_noncanonical_compute_benchmark(test_name):
        return "noncanonical_compute_benchmark"
    if test_opcode not in target_operations:
        return "unsupported_operation"
    if pd.isna(row["opcount"]) or row["opcount"] == 0:
        return "missing_target_opcount"
    return None


def prepare_zkevm_estimation_data(
    gas_bench_df: pd.DataFrame,
    trace_df: pd.DataFrame,
    target_operations: List[str],
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Filter raw zkEVM data down to estimation-ready benchmark rows."""
    target_set = set(target_operations)
    title_reason_df = (
        trace_df[
            ["test_title", "test_name", "test_opcode", "test_params", "opcount"]
        ]
        .drop_duplicates(subset=["test_title"])
        .copy()
    )
    title_reason_df["exclude_reason"] = title_reason_df.apply(
        lambda row: _classify_zkevm_exclusion(row, target_set), axis=1
    )

    gas_bench_with_reasons = gas_bench_df.merge(
        title_reason_df[["test_title", "exclude_reason"]],
        on="test_title",
        how="left",
    )
    exclusions_df = (
        gas_bench_with_reasons[gas_bench_with_reasons["exclude_reason"].notna()]
        .copy()
        .sort_values(
            ["exclude_reason", "test_opcode", "test_name", "client_name", "test_title"]
        )
    )
    filtered_gas_bench_df = (
        gas_bench_with_reasons[gas_bench_with_reasons["exclude_reason"].isna()]
        .drop(columns=["exclude_reason"])
        .copy()
    )
    included_titles = set(filtered_gas_bench_df["test_title"].unique())
    filtered_trace_df = trace_df[trace_df["test_title"].isin(included_titles)].copy()
    return filtered_gas_bench_df, filtered_trace_df, exclusions_df


def _infer_active_gas_params(
    gas_bench_df: pd.DataFrame,
    params: List[str],
) -> Dict[str, List[str]]:
    active_params_by_opcode: Dict[str, List[str]] = {}
    for opcode, op_df in gas_bench_df.groupby("test_opcode"):
        active_params = ["constant"]
        for param in params:
            values = op_df["test_params"].apply(lambda x: extract_param_values(x, param))
            if values.dropna().nunique() > 1:
                active_params.append(param)
        active_params_by_opcode[opcode] = active_params
    return active_params_by_opcode


def validate_zkevm_estimation_data(
    gas_bench_df: pd.DataFrame,
    target_operations: List[str],
    params: List[str],
) -> dict:
    """Validate that zkEVM data can safely enter the shared repricing pipeline."""
    target_set = set(target_operations)
    included_df = gas_bench_df.copy()
    invalid_opcount_df = included_df[included_df["opcount"].isna()]
    unexpected_opcodes = sorted(set(included_df["test_opcode"].dropna()) - target_set)
    active_params_by_opcode = _infer_active_gas_params(included_df, params)

    missing_gas_costs = []
    for opcode, active_params in active_params_by_opcode.items():
        for param in active_params:
            if get_current_gas_cost(opcode, param) is None:
                missing_gas_costs.append({"opcode": opcode, "param": param})

    invalid_rows = (
        invalid_opcount_df[["test_title", "test_name", "test_opcode"]]
        .drop_duplicates()
        .sort_values(["test_opcode", "test_name", "test_title"])
        .to_dict("records")
    )
    invalid_by_opcode = (
        invalid_opcount_df.groupby("test_opcode").size().sort_values(ascending=False).to_dict()
        if not invalid_opcount_df.empty
        else {}
    )
    missing_gas_costs = sorted(
        missing_gas_costs,
        key=lambda item: (item["opcode"], item["param"]),
    )

    return {
        "is_valid": not invalid_rows and not unexpected_opcodes and not missing_gas_costs,
        "included_rows": len(included_df),
        "included_tests": included_df["test_title"].nunique(),
        "included_opcodes": sorted(included_df["test_opcode"].dropna().unique()),
        "invalid_opcount_rows": invalid_rows,
        "invalid_opcount_by_opcode": invalid_by_opcode,
        "unexpected_opcodes": unexpected_opcodes,
        "missing_gas_costs": missing_gas_costs,
        "active_params_by_opcode": active_params_by_opcode,
    }


def format_zkevm_validation_summary(
    validation: dict,
    exclusions_df: pd.DataFrame,
) -> str:
    """Render a compact markdown validation summary for zkEVM estimation data."""
    lines = [
        "# zkEVM Validation Summary",
        "",
        f"- Included rows: {validation['included_rows']}",
        f"- Included tests: {validation['included_tests']}",
        f"- Included opcodes: {len(validation['included_opcodes'])}",
        f"- Excluded rows: {len(exclusions_df)}",
        f"- Validation status: {'PASS' if validation['is_valid'] else 'FAIL'}",
        "",
        "## Exclusions",
    ]

    if exclusions_df.empty:
        lines.append("- No rows were excluded.")
    else:
        counts = exclusions_df["exclude_reason"].value_counts().sort_index()
        for reason, count in counts.items():
            lines.append(f"- {reason}: {count}")

    lines.extend(["", "## Active Params"])
    for opcode, params in sorted(validation["active_params_by_opcode"].items()):
        lines.append(f"- {opcode}: {', '.join(params)}")

    lines.extend(["", "## Validation Checks"])
    if validation["invalid_opcount_rows"]:
        lines.append("- Included rows with null opcount:")
        for opcode, count in validation["invalid_opcount_by_opcode"].items():
            lines.append(f"  - {opcode}: {count}")
    else:
        lines.append("- Included rows with null opcount: none")

    if validation["unexpected_opcodes"]:
        lines.append(
            "- Included opcodes outside target set: "
            + ", ".join(validation["unexpected_opcodes"])
        )
    else:
        lines.append("- Included opcodes outside target set: none")

    if validation["missing_gas_costs"]:
        lines.append("- Missing current gas mappings:")
        for item in validation["missing_gas_costs"]:
            lines.append(f"  - {item['opcode']} / {item['param']}")
    else:
        lines.append("- Missing current gas mappings: none")

    return "\n".join(lines) + "\n"
