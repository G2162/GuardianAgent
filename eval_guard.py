import os, sys, json, hashlib, subprocess
from datetime import datetime

MANIFEST_PATH = "test_manifest.json"
LOG_PATH = "results/test_runs.log"
TOKEN_HASH_PATH = "expected_token_hash.txt"

# Canonical active dataset hashes
V14_HASHES = {
    "data/evaluation_splits/dev_dataset_v1.4.json":          "8397a99d7dd7a57fa7d413fc6291fe172a929cfc9f98c99e532277c546ed3159",
    "data/evaluation_splits/dev_paired_dataset_v1.4.json":   "a427dc9b97c25287b1517e93b273943d2118a4e7bc114c51924fd47494f567bc",
    "data/evaluation_splits/test_dataset_v1.4.json":         "50e14f70f18f2939377b6c68a2c834b338932aaf1a0128324e7156785fb0fe2d",
    "data/evaluation_splits/test_paired_dataset_v1.4.json":  "2f05ba10a6890faa6f26eeb54ad0d6fbcb09aa5890aa657a598e05d91c3bf924",
    "data/evaluation_splits/dev_extended_dataset_v1.4.json": "ae5825d408f29d23d0b46f2579932b81fc9d40444e86cdb2fb71531db5924979"
}

V13_HASHES = {
    "data/evaluation_splits/dev_dataset_v1.3.json":          "eb478515cbc1fa5bbab12c7cd4b2ae18cf16d9469b754476fcbd233be55e5e23",
    "data/evaluation_splits/test_dataset_v1.3.json":         "627308abd02ff2308a8ac4c5f14fd7351888b8e006ac18ac3c62689af65ddbd7",
    "data/evaluation_splits/dev_extended_dataset_v1.3.json": "0f1531a46c57b03cbc3ad2dd3b94e561887f4957fa18e317cfd9bdbad8d9bf77"
}

def _sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

def get_expected_token_hash():
    if os.path.exists(TOKEN_HASH_PATH):
        with open(TOKEN_HASH_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    return os.environ.get("GUARDIAN_EXPECTED_TOKEN_HASH", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

def verify_and_log_eval(split_name, config_desc="GUARDIAN_DISABLE_LLM=1", intent_track="Track A/B",
                        pipeline_version="v1.4", dataset_version="v1.4"):
    """
    Mandatory evaluation guard. Every evaluation script must invoke this function first.
    Refuses execution on the test split unless authorized by GUARDIAN_FINAL_EVAL_TOKEN.
    Blocks pipeline-design and iterative development scripts from reading TEST.
    Appends execution audit records to results/test_runs.log.
    """
    if not os.path.exists(MANIFEST_PATH):
        raise RuntimeError(f"FATAL: {MANIFEST_PATH} missing! Evaluation cannot proceed.")

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Verify prereg hashes (policy files — unchanged across all prereg versions)
    for fname, exp_hash in manifest.get("verified_prereg_hashes", {}).items():
        if not os.path.exists(fname):
            raise RuntimeError(f"FATAL: Frozen pre-registration file {fname} not found!")
        act_hash = _sha256(fname)
        if act_hash != exp_hash:
            raise RuntimeError(
                f"SECURITY VIOLATION: Prereg file {fname} has been modified!\n"
                f"Expected {exp_hash}, got {act_hash}"
            )

    # 2. Select dataset paths and expected hashes
    if dataset_version == "v1.4":
        test_path = "data/evaluation_splits/test_paired_dataset_v1.4.json"
        dev_path  = "data/evaluation_splits/dev_paired_dataset_v1.4.json"
        exp_test_hash = V14_HASHES.get(test_path)
        exp_dev_hash  = V14_HASHES.get(dev_path)
    elif dataset_version == "v1.3":
        test_path = "data/evaluation_splits/test_dataset_v1.3.json"
        dev_path  = "data/evaluation_splits/dev_dataset_v1.3.json"
        exp_test_hash = V13_HASHES.get(test_path)
        exp_dev_hash  = V13_HASHES.get(dev_path)
    else:
        test_path = "data/evaluation_splits/test_dataset_v1.2.json"
        dev_path  = "data/evaluation_splits/dev_dataset_v1.2.json"
        exp_test_hash = "44e35b7a13be6585b1540e1b5edf40044be324f62d74fe4cd9a3fe0b1cf401f3"
        exp_dev_hash  = "bb537ede40a93d0f2a1865c49947c51919142aa6dec86ca8a905577880204a6f"

    expected_hash = get_expected_token_hash()

    # 3. Verify split integrity and block unauthorized TEST access
    if split_name.lower() in ("test", "test_paired"):
        token = os.environ.get("GUARDIAN_FINAL_EVAL_TOKEN")
        if not token:
            raise PermissionError(
                "EVAL_GUARD ACCESS DENIED: Reading the TEST split is cryptographically locked.\n"
                "Pipeline iteration, tuning, and design must be performed on DEV only.\n"
                "Final benchmark evaluation requires the environment variable GUARDIAN_FINAL_EVAL_TOKEN.\n"
                "Please configure GUARDIAN_FINAL_EVAL_TOKEN with your pre-shared secret token."
            )
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        if token_hash != expected_hash:
            raise PermissionError(
                f"EVAL_GUARD ACCESS DENIED: Provided GUARDIAN_FINAL_EVAL_TOKEN does not match expected hash!\n"
                f"Provided token hash: {token_hash}\n"
                f"Expected token hash: {expected_hash}\n"
                "Final evaluation aborted."
            )
        if not os.path.exists(test_path):
            raise RuntimeError(f"FATAL: Test split file {test_path} missing (check data/test_v1.4.7z archive)!")
        act_hash = _sha256(test_path)
        if act_hash != exp_test_hash:
            raise RuntimeError(
                f"SECURITY VIOLATION: Test split {test_path} hash mismatch!\n"
                f"Expected: {exp_test_hash}\n"
                f"Actual:   {act_hash}\n"
                f"EVALUATION ABORTED."
            )
        print(f"[eval_guard] TEST SPLIT INTEGRITY VERIFIED ({dataset_version}, SHA-256: {act_hash[:16]}...)")
    elif split_name.lower() in ("dev", "dev_paired"):
        if not os.path.exists(dev_path):
            raise RuntimeError(f"FATAL: Dev split file {dev_path} missing!")
        act_hash = _sha256(dev_path)
        if exp_dev_hash and act_hash != exp_dev_hash:
            print(f"[eval_guard] WARNING: Dev split hash mismatch (expected {exp_dev_hash[:16]}..., got {act_hash[:16]}...)")
        print(f"[eval_guard] DEV SPLIT ACTIVE ({dataset_version}). Free development/tuning permitted.")
    else:
        print(f"[eval_guard] Custom split: {split_name}")

    # 4. Retrieve git commit
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        git_commit = "UNKNOWN_COMMIT"

    # 5. Append audit log entry
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "git_commit": git_commit,
        "pipeline_version": pipeline_version,
        "dataset_version": dataset_version,
        "config": config_desc,
        "intent_track": intent_track,
        "split": split_name
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    print(f"[eval_guard] Evaluation execution audited and recorded to {LOG_PATH}")
    return True

if __name__ == '__main__':
    split = sys.argv[1] if len(sys.argv) > 1 else "dev"
    dataset_ver = sys.argv[2] if len(sys.argv) > 2 else "v1.4"
    verify_and_log_eval(split, dataset_version=dataset_ver)
