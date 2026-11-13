import json, os, random
from collections import Counter

random.seed(42)

benign_cases = json.load(open('data/benign_cases_initial.json'))
unsafe_cases = json.load(open('data/unsafe_cases_initial.json'))
all_cases = benign_cases + unsafe_cases

# Unique databases
all_dbs = sorted(list(set(c['database'] for c in all_cases)))
print(f"Total databases: {len(all_dbs)}")

# 18 databases: 30% dev = 5 or 6 databases; 70% test = 12 or 13 databases
# Let's assign 5 databases to DEV (27.8%) and 13 databases to TEST (72.2%)
# or 6 databases to DEV (33.3%) and 12 databases to TEST (66.7%)
# 30% of 18 is 5.4. 5 dbs to DEV and 13 to TEST is 27.8% vs 72.2%.
# Let's check distribution
dev_dbs = all_dbs[:5] # 5 dbs
test_dbs = all_dbs[5:] # 13 dbs

print("DEV databases:", dev_dbs)
print("TEST databases:", test_dbs)

dev_cases = [c for c in all_cases if c['database'] in dev_dbs]
test_cases = [c for c in all_cases if c['database'] in test_dbs]

print(f"\nDEV cases: {len(dev_cases)} ({len(dev_cases)/len(all_cases)*100:.1f}%)")
print(f"TEST cases: {len(test_cases)} ({len(test_cases)/len(all_cases)*100:.1f}%)")

os.makedirs('data/evaluation_splits', exist_ok=True)
with open('data/evaluation_splits/dev_dataset.json', 'w') as f:
    json.dump(dev_cases, f, indent=2)

with open('data/evaluation_splits/test_dataset.json', 'w') as f:
    json.dump(test_cases, f, indent=2)

def print_breakdown(name, cases):
    print(f"\n=== {name} BREAKDOWN ===")
    print(f"Total: {len(cases)}")
    by_op = Counter(c['ground_truth_intent']['operation'] for c in cases)
    print("Operations:", dict(by_op))
    by_fam = Counter(c['family_id'] for c in cases)
    print("Families:", len(by_fam), "unique families")
    by_db = Counter(c['database'] for c in cases)
    print("Databases:", dict(by_db))

print_breakdown("DEV", dev_cases)
print_breakdown("TEST", test_cases)

