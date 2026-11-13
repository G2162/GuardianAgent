import os, sys, json, hashlib, subprocess
from datetime import datetime

MANIFEST_PATH = "test_manifest.json"
LOG_PATH = "results/test_runs.log"

def verify_and_log_eval(split_name, config_desc="GUARDIAN_DISABLE_LLM=1", intent_track="Track A/B", pipeline_version="v1.1"):
    """
    Mandatory evaluation guard. Every evaluation script must invoke this function first.
    Refuses execution on the test split if any cryptographic digest differs.
    Appends execution audit records to results/test_runs.log.
    """
    if not os.path.exists(MANIFEST_PATH):
        raise RuntimeError(f"FATAL: {MANIFEST_PATH} missing! Evaluation cannot proceed.")

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Verify prereg hashes
    for fname, exp_hash in manifest.get("verified_prereg_hashes", {}).items():
        if not os.path.exists(fname):
            raise RuntimeError(f"FATAL: Frozen pre-registration file {fname} not found!")
        act_hash = hashlib.sha256(open(fname, "rb").read()).hexdigest()
        if act_hash != exp_hash:
            raise RuntimeError(f"SECURITY VIOLATION: Prereg file {fname} has been modified! Expected {exp_hash}, got {act_hash}")

    # 2. If split is test, verify test dataset integrity
    if split_name.lower() == "test":
        test_info = manifest["dataset_files"]["test_dataset.json"]
        test_path = test_info["path"]
        if not os.path.exists(test_path):
            raise RuntimeError(f"FATAL: Test split file {test_path} missing!")
        act_test_hash = hashlib.sha256(open(test_path, "rb").read()).hexdigest()
        if act_test_hash != test_info["sha256"]:
            raise RuntimeError(
                f"SECURITY VIOLATION: Test split {test_path} hash mismatch!\n"
                f"Expected: {test_info['sha256']}\n"
                f"Actual:   {act_test_hash}\n"
                f"EVALUATION ABORTED."
            )
        print(f"[eval_guard] TEST SPLIT INTEGRITY VERIFIED (SHA-256: {act_test_hash[:16]}...)")
    elif split_name.lower() == "dev":
        dev_info = manifest["dataset_files"]["dev_dataset.json"]
        dev_path = dev_info["path"]
        if not os.path.exists(dev_path):
            raise RuntimeError(f"FATAL: Dev split file {dev_path} missing!")
        print("[eval_guard] DEV SPLIT ACTIVE. Free development/tuning permitted.")
    else:
        print(f"[eval_guard] Custom split: {split_name}")

    # 3. Retrieve git commit
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        git_commit = "UNKNOWN_COMMIT"

    # 4. Append audit log entry
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "git_commit": git_commit,
        "pipeline_version": pipeline_version,
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
    verify_and_log_eval(split)

