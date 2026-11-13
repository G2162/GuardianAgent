import json, os, glob

# Check if any TEST file was opened for write or modified
test_path = 'data/evaluation_splits/test_dataset.json'
manifest = json.load(open('test_manifest.json'))

import hashlib
current_test_hash = hashlib.sha256(open(test_path, 'rb').read()).hexdigest()
expected_test_hash = manifest['dataset_files']['test_dataset.json']['sha256']

print("Test dataset verification:")
print("Expected:", expected_test_hash)
print("Actual:  ", current_test_hash)
assert current_test_hash == expected_test_hash, "TEST SPLIT INTEGRITY COMPROMISED!"
print("TEST SPLIT INTEGRITY INTACT AND FROZEN.")

