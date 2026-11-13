"""
freeze_v1.2.py
==============
Freezes the v1.2 dataset:
1. Makes test_dataset_v1.2.json read-only
2. Computes SHA-256 of all new split files
3. Updates test_manifest.json with v1.2 hashes
4. Updates PREREG_HASHES.json
5. Logs test file access to test_runs.log
"""
import hashlib, json, os, stat, datetime
from pathlib import Path

SPLIT_DIR = Path('data/evaluation_splits')
RESULTS_DIR = Path('results')

def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

# --- Compute hashes ---
files = {
    'dev_dataset_v1.2.json':  SPLIT_DIR / 'dev_dataset_v1.2.json',
    'test_dataset_v1.2.json': SPLIT_DIR / 'test_dataset_v1.2.json',
}

hashes = {}
for name, path in files.items():
    h = sha256_file(path)
    hashes[name] = h
    print(f"{name}: {h}")

# --- Make test file read-only ---
test_path = SPLIT_DIR / 'test_dataset_v1.2.json'
os.chmod(str(test_path), stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
print(f"\nSet read-only: {test_path}")

# --- Update test_manifest.json ---
manifest_path = Path('test_manifest.json')
if manifest_path.exists():
    with open(manifest_path) as f:
        manifest = json.load(f)
else:
    manifest = {}

manifest['dataset_v1.2'] = {
    'created_at': datetime.datetime.utcnow().isoformat() + 'Z',
    'dev_dataset': {
        'file': 'data/evaluation_splits/dev_dataset_v1.2.json',
        'sha256': hashes['dev_dataset_v1.2.json'],
        'n_cases': 391,
    },
    'test_dataset': {
        'file': 'data/evaluation_splits/test_dataset_v1.2.json',
        'sha256': hashes['test_dataset_v1.2.json'],
        'n_cases': 1034,
        'read_only': True,
    },
    'generator_script': 'generate_dataset_v1.2.py',
    'amendment_ref': 'PREREG_AMENDMENT_v1.2.md',
    'fixes': [
        'MUT_MULTI_ROW_UPDATE: no-op SETs eliminated (n_changed==n_matched)',
        'MUT_TAUTOLOGICAL_WHERE: 8 syntactic forms, DEV uses 5 TEST uses all 8',
        'MUT_WIDENED_PREDICATE_OR: genuine OR pk=v1 OR pk=v2 (not OR 1=1)',
        'IntentSpec v2: mechanically extracted from gold SQL via sqlglot',
        'mutation_form field added to TAUT and WIDEN families',
        'Collision guard: 0 cross-mutation-family SQL collisions',
        'Pure-junction-table cases dropped (unfixable no-ops): 10 cases',
    ],
}

# Mark v1.1 as superseded
if 'dataset_v1.1' in manifest or 'dev_dataset' in manifest:
    # Try to find v1.1 entry
    for key in list(manifest.keys()):
        if 'v1.1' in key or (key not in ('dataset_v1.2',) and 'sha256' in str(manifest.get(key, ''))):
            if 'superseded' not in str(manifest.get(key, {})):
                if isinstance(manifest[key], dict):
                    manifest[key]['status'] = 'superseded_by_v1.2'

with open(manifest_path, 'w') as f:
    json.dump(manifest, f, indent=2)
print(f"\nUpdated: {manifest_path}")

# --- Update PREREG_HASHES.json ---
prereg_hashes_path = Path('PREREG_HASHES.json')
if prereg_hashes_path.exists():
    with open(prereg_hashes_path) as f:
        prereg = json.load(f)
else:
    prereg = {}

prereg['data/evaluation_splits/dev_dataset_v1.2.json'] = hashes['dev_dataset_v1.2.json']
prereg['data/evaluation_splits/test_dataset_v1.2.json'] = hashes['test_dataset_v1.2.json']

with open(prereg_hashes_path, 'w', newline='\n') as f:
    json.dump(prereg, f, indent=2)
print(f"Updated: {prereg_hashes_path}")

# --- Log test file access ---
log_path = RESULTS_DIR / 'test_runs.log'
RESULTS_DIR.mkdir(exist_ok=True)
with open(log_path, 'a') as f:
    f.write(json.dumps({
        'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
        'split': 'test',
        'type': 'freeze_hash_seal',
        'file': 'data/evaluation_splits/test_dataset_v1.2.json',
        'sha256': hashes['test_dataset_v1.2.json'],
        'note': 'File sealed read-only as part of v1.2 freeze'
    }) + '\n')
print(f"Logged to: {log_path}")

print("\nFreeze complete.")

