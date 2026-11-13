import json, os

def verify_zero_overlap():
    existing_dbs = json.load(open('results/overlap_existing_dbs.json'))
    db_inventory = json.load(open('data/evaluation_dbs/db_inventory.json'))
    selected_dbs = list(db_inventory.keys())

    existing_set = set(existing_dbs)
    selected_set = set(selected_dbs)

    overlap = existing_set.intersection(selected_set)
    print("=== ZERO-OVERLAP VERIFICATION EVIDENCE ===")
    print(f"Total prior evaluation databases tracked: {len(existing_set)}")
    print(f"Total newly selected databases: {len(selected_set)}")
    print(f"Intersection count: {len(overlap)}")
    if overlap:
        print(f"CRITICAL ERROR: Overlap detected! {overlap}")
        raise ValueError(f"Overlap detected: {overlap}")
    else:
        print("PASS: Exact zero overlap between prior evaluation databases and new databases.")

    report = {
        "status": "PASS",
        "overlap_count": 0,
        "selected_database_count": len(selected_set),
        "selected_databases": sorted(list(selected_set)),
        "prior_evaluation_database_count": len(existing_set),
        "prior_evaluation_databases": sorted(list(existing_set))
    }
    os.makedirs('results', exist_ok=True)
    with open('results/overlap_check_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("Saved evidence report to results/overlap_check_report.json")

if __name__ == '__main__':
    verify_zero_overlap()

