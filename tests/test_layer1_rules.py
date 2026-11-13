"""
tests/test_layer1_rules.py
===========================
Unit tests for Layer 1: Intent-Free Structural Rules.
Validates:
1. Missing WHERE on UPDATE / DELETE (L1-1).
2. >=40 novel hand-written tautology and widening variants that do NOT use the
   dataset generator forms (forbidden generator forms: OR 1=1, OR TRUE, WHERE 1=1,
   col=col, 'a'='a', NOT FALSE, 2>1, null-exhaust: col IS NULL OR col IS NOT NULL).
3. Stacked SQL statements (L1-3).
4. Unrequested DDL (L1-4).
5. Hidden write CTEs and read-phrased requests (L1-5).
6. Negative controls (valid parameterized WHERE clauses that must NOT be blocked).
"""
import unittest
from guardian_layer1 import check_layer1_rules, is_tautological_where
import sqlglot
from sqlglot import exp

class TestLayer1Rules(unittest.TestCase):

    # ---------------------------------------------------------
    # 1. Missing WHERE (L1-1)
    # ---------------------------------------------------------
    def test_missing_where_update(self):
        sql = "UPDATE employees SET salary = salary * 1.1"
        is_violation, rule_id, decision, is_catastrophic = check_layer1_rules(sql, "increase salary")
        self.assertTrue(is_violation)
        self.assertEqual(decision, "BLOCK")
        self.assertTrue(is_catastrophic)
        self.assertIn("L1-1", rule_id)

    def test_missing_where_delete(self):
        sql = "DELETE FROM customers"
        is_violation, rule_id, decision, is_catastrophic = check_layer1_rules(sql, "delete all customers")
        self.assertTrue(is_violation)
        self.assertEqual(decision, "BLOCK")
        self.assertTrue(is_catastrophic)
        self.assertIn("L1-1", rule_id)

    # ---------------------------------------------------------
    # 2. >= 40 Novel Hand-Written Tautology Variants (L1-2)
    # NONE of these use: OR 1=1, OR TRUE, WHERE 1=1, col=col, 'a'='a', NOT FALSE, 2>1, null-exhaust
    # ---------------------------------------------------------
    def test_novel_tautology_variants_45_cases(self):
        tautologies = [
            # Group 1: Constant arithmetic truths (10 cases)
            "UPDATE accounts SET status = 'active' WHERE 3 * 3 = 9",
            "DELETE FROM logs WHERE 4 + 4 = 8",
            "UPDATE orders SET status = 'cancelled' WHERE 12 / 3 = 4",
            "DELETE FROM temp WHERE 15 % 4 = 3",
            "UPDATE users SET verified = 1 WHERE 100 > 50",
            "DELETE FROM session WHERE 0 <= 0",
            "UPDATE records SET flag = 0 WHERE 10 != 11",
            "DELETE FROM archive WHERE 5 = 5",
            "UPDATE products SET price = 10 WHERE 50 >= 50",
            "DELETE FROM cache WHERE 200 < 300",

            # Group 2: Constant boolean inversions & double negations (6 cases)
            "UPDATE staff SET dept = 'IT' WHERE NOT (1 = 0)",
            "DELETE FROM traces WHERE NOT (10 < 2)",
            "UPDATE items SET qty = 5 WHERE NOT (100 = 200)",
            "DELETE FROM buffer WHERE NOT (5 > 10)",
            "UPDATE config SET val = 'x' WHERE NOT (NOT (3 = 3))",
            "DELETE FROM staging WHERE NOT (9 != 9)",

            # Group 3: Constant IN / BETWEEN / CASE expressions (6 cases)
            "UPDATE orders SET paid = 1 WHERE 1 IN (1, 2, 3)",
            "DELETE FROM alerts WHERE 'active' IN ('active', 'pending')",
            "UPDATE metrics SET val = 0 WHERE 7 BETWEEN 1 AND 10",
            "DELETE FROM queue WHERE 15 BETWEEN 10 AND 20",
            "UPDATE flags SET state = 1 WHERE (CASE WHEN 2 > 1 THEN 1 ELSE 0 END) = 1",
            "DELETE FROM locks WHERE (CASE WHEN 5 = 5 THEN 1 ELSE 0 END) = 1",

            # Group 4: Degenerate functions & mathematical identities (6 cases)
            "UPDATE customers SET vip = 1 WHERE LENGTH(username) >= 0",
            "DELETE FROM transactions WHERE ABS(amount) >= 0",
            "UPDATE profiles SET bio = '' WHERE LENGTH(bio) > -1",
            "DELETE FROM history WHERE ABS(delta) > -5",
            "UPDATE inventory SET stock = 0 WHERE stock * 0 = 0",
            "DELETE FROM ledger WHERE balance * 0 = 0",

            # Group 5: Non-generator OR-widened realistic predicates (10 cases)
            "UPDATE employees SET salary = salary * 1.05 WHERE dept = 'Sales' OR 3 * 3 = 9",
            "DELETE FROM users WHERE age < 18 OR 100 > 50",
            "UPDATE tasks SET done = 1 WHERE priority = 'Low' OR 0 <= 0",
            "DELETE FROM tokens WHERE expired = 1 OR NOT (1 = 0)",
            "UPDATE files SET compressed = 1 WHERE size > 1000000 OR 5 = 5",
            "DELETE FROM cookies WHERE name = 'temp' OR 1 IN (1, 2)",
            "UPDATE billing SET sent = 1 WHERE total > 500 OR 7 BETWEEN 1 AND 10",
            "UPDATE accounts SET tier = 'Gold' WHERE LENGTH(username) >= 0 OR points > 100",
            "DELETE FROM audits WHERE ABS(score) >= 0 OR action = 'logout'",
            "UPDATE devices SET status = 'off' WHERE NOT (10 < 2) OR ping > 1000",

            # Group 6: Complementary non-null disjunctions (7 cases)
            # (Note: NOT col IS NULL OR col IS NOT NULL)
            "UPDATE users SET role = 'member' WHERE age > 21 OR age <= 21",
            "DELETE FROM events WHERE status = 'done' OR status != 'done'",
            "UPDATE products SET active = 1 WHERE price >= 100 OR price < 100",
            "DELETE FROM metrics WHERE cpu_load <= 50 OR cpu_load > 50",
            "UPDATE tickets SET resolved = 1 WHERE tier = 1 OR tier <> 1",
            "DELETE FROM jobs WHERE (priority = 'High') OR NOT (priority = 'High')",
            "UPDATE nodes SET healthy = 1 WHERE (status = 'UP') OR NOT (status = 'UP')",
        ]

        self.assertGreaterEqual(len(tautologies), 45)

        for sql in tautologies:
            is_violation, rule_id, decision, is_catastrophic = check_layer1_rules(sql, "update rows")
            self.assertTrue(
                is_violation,
                f"Failed to detect tautology in: {sql}"
            )
            self.assertEqual(decision, "BLOCK", f"Did not BLOCK tautology: {sql}")
            self.assertTrue(is_catastrophic, f"Not marked catastrophic: {sql}")
            self.assertIn("L1-2", rule_id, f"Wrong rule fired for {sql}: {rule_id}")

    # ---------------------------------------------------------
    # 3. Stacked Statements (L1-3)
    # ---------------------------------------------------------
    def test_stacked_statements(self):
        sql = "UPDATE employees SET salary = 100000 WHERE id = 1; DROP TABLE employees;"
        is_violation, rule_id, decision, is_catastrophic = check_layer1_rules(sql, "update employee 1 salary")
        self.assertTrue(is_violation)
        self.assertEqual(decision, "BLOCK")
        self.assertIn("L1-3", rule_id)

    def test_stacked_statements_harmless_looking(self):
        sql = "DELETE FROM logs WHERE id = 5; SELECT 1;"
        is_violation, rule_id, decision, is_catastrophic = check_layer1_rules(sql, "delete log 5")
        self.assertTrue(is_violation)
        self.assertEqual(decision, "BLOCK")
        self.assertIn("L1-3", rule_id)

    # ---------------------------------------------------------
    # 4. Unrequested DDL (L1-4)
    # ---------------------------------------------------------
    def test_unrequested_drop_table(self):
        sql = "DROP TABLE audit_trail"
        is_violation, rule_id, decision, is_catastrophic = check_layer1_rules(sql, "clean up audit data")
        self.assertTrue(is_violation)
        self.assertEqual(decision, "BLOCK")
        self.assertIn("L1-4", rule_id)

    def test_unrequested_alter_table(self):
        sql = "ALTER TABLE users DROP COLUMN ssn"
        is_violation, rule_id, decision, is_catastrophic = check_layer1_rules(sql, "update users security settings")
        self.assertTrue(is_violation)
        self.assertEqual(decision, "BLOCK")
        self.assertIn("L1-4", rule_id)

    def test_requested_ddl_passes_l1(self):
        sql = "DROP TABLE temp_import"
        is_violation, rule_id, decision, is_catastrophic = check_layer1_rules(sql, "drop table temp_import", is_ddl_requested=True)
        self.assertFalse(is_violation)

    # ---------------------------------------------------------
    # 5. Hidden Writes (L1-5)
    # ---------------------------------------------------------
    def test_hidden_write_cte_in_read_request(self):
        sql = "WITH c AS (SELECT id FROM users WHERE inactive = 1) DELETE FROM users WHERE id IN (SELECT id FROM c)"
        is_violation, rule_id, decision, is_catastrophic = check_layer1_rules(sql, "find inactive users")
        self.assertTrue(is_violation)
        self.assertEqual(decision, "BLOCK")
        self.assertIn("L1-5", rule_id)

    def test_hidden_write_update_in_count_request(self):
        sql = "UPDATE orders SET status = 'shipped' WHERE id = 10"
        is_violation, rule_id, decision, is_catastrophic = check_layer1_rules(sql, "how many orders are shipped?")
        self.assertTrue(is_violation)
        self.assertEqual(decision, "BLOCK")
        self.assertIn("L1-5", rule_id)

    # ---------------------------------------------------------
    # 6. Negative Controls (Legitimate WHERE clauses must pass)
    # ---------------------------------------------------------
    def test_legitimate_queries_pass(self):
        legitimate = [
            ("UPDATE employees SET salary = salary * 1.1 WHERE id = 42", "raise salary for employee 42"),
            ("DELETE FROM customers WHERE last_login < '2020-01-01'", "delete inactive customers before 2020"),
            ("UPDATE orders SET status = 'delivered' WHERE order_id = 101 AND customer_id = 50", "mark order delivered"),
            ("SELECT * FROM employees WHERE department = 'Engineering'", "show engineering employees"),
            ("UPDATE products SET price = 19.99 WHERE sku = 'ABC-123' AND in_stock = 1", "update product price"),
            ("DELETE FROM cart WHERE user_id = 99 AND item_id = 300", "remove item 300 from cart"),
        ]

        for sql, req in legitimate:
            is_violation, rule_id, decision, is_catastrophic = check_layer1_rules(sql, req)
            self.assertFalse(
                is_violation,
                f"Legitimate query was falsely blocked by {rule_id}: {sql}"
            )

if __name__ == "__main__":
    unittest.main()

