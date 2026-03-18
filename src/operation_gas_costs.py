def get_fusaka_dict():
    out_dict = {}

    # Zero-cost or effectively zero-cost base opcodes.
    for op in ["STOP", "RETURN", "REVERT", "INVALID"]:
        out_dict[op] = 0

    # Base-tier opcodes.
    for op in [
        "ADDRESS",
        "BASEFEE",
        "BLOBBASEFEE",
        "CALLDATASIZE",
        "CALLER",
        "CALLVALUE",
        "CHAINID",
        "CODESIZE",
        "COINBASE",
        "GAS",
        "GASLIMIT",
        "GASPRICE",
        "MSIZE",
        "NUMBER",
        "ORIGIN",
        "PC",
        "POP",
        "PREVRANDAO",
        "RETURNDATASIZE",
        "TIMESTAMP",
    ]:
        out_dict[op] = 2

    out_dict["JUMPDEST"] = 1
    out_dict["PUSH0"] = 2
    out_dict["BLOCKHASH"] = 20
    out_dict["BLOBHASH"] = 3

    # Very-low-tier opcodes.
    for op in [
        "ADD",
        "AND",
        "BYTE",
        "CALLDATALOAD",
        "CODECOPY",
        "CALLDATACOPY",
        "EQ",
        "ISZERO",
        "LT",
        "GT",
        "MCOPY",
        "MLOAD",
        "MSTORE",
        "MSTORE8",
        "NOT",
        "OR",
        "RETURNDATACOPY",
        "SAR",
        "SHL",
        "SHR",
        "SGT",
        "SIGNEXTEND",
        "SLT",
        "SUB",
        "XOR",
    ]:
        out_dict[op] = 3

    for i in range(1, 33):
        out_dict[f"PUSH{i}"] = 3
    for i in range(1, 17):
        out_dict[f"DUP{i}"] = 3
        out_dict[f"SWAP{i}"] = 3

    # Low- and mid-tier arithmetic/control flow.
    for op in ["MUL", "DIV", "SDIV", "MOD", "SMOD", "SELFBALANCE"]:
        out_dict[op] = 5
    for op in ["ADDMOD", "MULMOD", "JUMP"]:
        out_dict[op] = 8
    out_dict["JUMPI"] = 10
    out_dict["EXP"] = 10

    # Memory and copy coefficients.
    out_dict["KECCAK256"] = 30
    out_dict["KECCAK256_WORD"] = 6
    out_dict["KECCAK256_MEM_WORD"] = 0
    out_dict["CALLDATACOPY_MEM_WORD"] = 3
    out_dict["CODECOPY_CODE_WORD"] = 3
    out_dict["CODECOPY_MEM_WORD"] = 0
    out_dict["RETURNDATACOPY_MEM_WORD"] = 3
    out_dict["MCOPY_MEM_WORD"] = 3
    out_dict["MLOAD_MEM_WORD"] = 0
    out_dict["MSIZE_MEM_WORD"] = 0
    out_dict["MSTORE_MEM_WORD"] = 0
    out_dict["MSTORE8_MEM_WORD"] = 0

    # Transient/state opcodes.
    out_dict["TLOAD"] = 100
    out_dict["TSTORE"] = 100
    out_dict["SSTORE"] = 100
    out_dict["SSTORE_NEW"] = 20_000 - 100
    out_dict["SSTORE_UPDATE"] = 5_000 - 2_100 - 100
    out_dict["SSTORE_COLD"] = 2_100
    out_dict["SLOAD"] = 100
    out_dict["SLOAD_COLD"] = 2_100 - 100

    # Standard precompiles.
    out_dict["ECRECOVER"] = 3_000
    out_dict["ECADD"] = 150
    out_dict["ECMUL"] = 6_000
    out_dict["ECPAIRING"] = 45_000
    out_dict["ECPAIRING_PAIRS"] = 34_000
    out_dict["SHA2-256"] = 60
    out_dict["SHA2-256_WORD"] = 12
    out_dict["RIPEMD-160"] = 600
    out_dict["RIPEMD-160_WORD"] = 120
    out_dict["IDENTITY"] = 15
    out_dict["IDENTITY_WORD"] = 3
    out_dict["MODEXP"] = 200
    # MODEXP uses a non-linear current-gas formula; the linear benchmark keeps only
    # a placeholder coefficient so the proposal layer can render a non-null value.
    out_dict["MODEXP_MOD"] = 0
    out_dict["BLAKE2F"] = 0
    out_dict["BLAKE2F_ROUNDS"] = 1

    # Newer protocol precompiles.
    out_dict["POINT_EVALUATION"] = 50_000
    out_dict["BLS12_G1ADD"] = 375
    out_dict["BLS12_G2ADD"] = 600
    out_dict["BLS12_MAP_FP_TO_G1"] = 5_500
    out_dict["BLS12_MAP_FP2_TO_G2"] = 23_800
    out_dict["BLS12_G1MSM"] = 0
    out_dict["BLS12_G1MSM_K"] = 12_000
    out_dict["BLS12_G2MSM"] = 0
    out_dict["BLS12_G2MSM_K"] = 22_500
    out_dict["BLS12_PAIRING_CHECK"] = 37_700
    out_dict["BLS12_PAIRING_CHECK_PAIRS"] = 32_600
    out_dict["P256VERIFY"] = 6_900

    # Stateful and call opcodes used by the shared proposal logic.
    for op in [
        "BALANCE",
        "DELEGATECALL",
        "STATICCALL",
        "CALL",
        "CALLCODE",
        "EXTCODESIZE",
        "EXTCODEHASH",
        "EXTCODECOPY",
    ]:
        out_dict[op] = 100
        out_dict[op + "_COLD"] = 2_500
    out_dict["EXTCODECOPY_SIZE"] = 3

    return out_dict
