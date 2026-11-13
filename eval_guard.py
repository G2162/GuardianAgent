import os, sys, json, hashlib, subprocess
from datetime import datetime

MANIFEST_PATH = "test_manifest.json"
LOG_PATH = "results/test_runs.log"

# v1.2 dataset hashes (canonical record)
V12_HASHES = {
    "data/evaluation_splits/dev_dataset_v1.2.json":  "bb537ede40a93d0f2a1865c49947c51919142aa6dec86ca8a905577880204a6f",
    "data/evaluation_splits/test_dataset_v1.2.json": "44e35b7a13be6585b1540e1b5edf40044be324f62d74fe4cd9a3fe0b1cf401f3",
}

def _sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

def verify_and_log_eval(split_name, config_desc="GUARDIAN_DISABLE_LLM=1", intent_track="Track A/B",
                        pipeline_version="v1.2", dataset_version="v1.2"):
    """
    Mandatory evaluation guard. Every evaluation script must invoke this function first.
    Refuses execution on the test split if any cryptographic digest differs.
    Appends execution audit records to results/test_runs.log.
    
    dataset_version: "v1.1" (legacy) or "v1.2" (default, regenerated dataset)
    """
    if not os.path.exists(MANIFEST_PATH):
        raise RuntimeError(f"FATAL: {MANIFEST_PATH} missing! Evaluation cannot proceed.")

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Verify prereg hashes (policy files — unchanged between v1.1 and v1.2)
    for fname, exp_hash in manifest.get("verified_prereg_hashes", {}).items():
        if not os.path.exists(fname):
            raise RuntimeError(f"FATAL: Frozen pre-registration file {fname} not found!")
        act_hash = _sha256(fname)
        if act_hash != exp_hash:
            raise RuntimeError(
                f"SECURITY VIOLATION: Prereg file {fname} has been modified!\n"
                f"Expected {exp_hash}, got {act_hash}"
            )

    # 2. Select dataset version
    if dataset_version == "v1.2":
        v12 = manifest.get("dataset_v1.2", {})
        test_path = "data/evaluation_splits/test_dataset_v1.2.json"
        dev_path  = "data/evaluation_splits/dev_dataset_v1.2.json"
        exp_test_hash = V12_HASHES.get(test_path)
        exp_dev_hash  = V12_HASHES.get(dev_path)
    else:
        # Legacy v1.1 paths
        test_path = manifest["dataset_files"]["test_dataset.json"]["path"]
        dev_path  = manifest["dataset_files"]["dev_dataset.json"]["path"]
        exp_test_hash = manifest["dataset_files"]["test_dataset.json"]["sha256"]
        exp_dev_hash  = manifest["dataset_files"]["dev_dataset.json"].get("sha256")

    # 3. Verify split integrity
    if split_name.lower() == "test":
        if not os.path.exists(test_path):
            raise RuntimeError(f"FATAL: Test split file {test_path} missing!")
        act_hash = _sha256(test_path)
        if act_hash != exp_test_hash:
            raise RuntimeError(
                f"SECURITY VIOLATION: Test split {test_path} hash mismatch!\n"
                f"Expected: {exp_test_hash}\n"
                f"Actual:   {act_hash}\n"
                f"EVALUATION ABORTED."
            )
        print(f"[eval_guard] TEST SPLIT INTEGRITY VERIFIED ({dataset_version}, SHA-256: {act_hash[:16]}...)")
    elif split_name.lower() == "dev":
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
    dataset_ver = sys.argv[2] if len(sys.argv) > 2 else "v1.2"
    verify_and_log_eval(split, dataset_version=dataset_ver)

