import ast
import sys
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from netpulse.features import HistoryStore, ProfileStore, rule_state


class EnglishInterfaceTests(unittest.TestCase):
    def test_rule_labels_are_english_without_changing_state_identifiers(self):
        self.assertEqual(rule_state('proxy', 'proxy')['label'], 'Applied')
        self.assertEqual(rule_state('proxy', 'direct')['label'], 'Pending')
        self.assertEqual(rule_state('proxy', 'direct', failed=True)['label'], 'Error')

    def test_export_uses_english_columns_and_preserves_numeric_measurements(self):
        with tempfile.TemporaryDirectory() as temporary:
            import csv
            import time
            root = Path(temporary)
            store = HistoryStore(root / 'history.db')
            store.record(time.time(), 100, 20, [('browser', 50, 10)])
            store.export_csv(root / 'usage.csv')
            with (root / 'usage.csv').open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(set(rows[0]), {'local_date', 'scope', 'application', 'bytes_received', 'bytes_sent'})
            self.assertEqual({row['scope'] for row in rows}, {'Global TCP+UDP', 'Sampled TCP'})
            self.assertEqual(sum(int(row['bytes_received']) for row in rows), 150)

    def test_profile_validation_returns_an_english_message(self):
        with self.assertRaisesRegex(ValueError, 'profile name and URL must be strings'):
            ProfileStore.validate({'name': None})

    def test_user_visible_python_text_has_no_untranslated_french_diacritics(self):
        # Ignore docstrings; inspect runtime literals, including f-string fragments.
        files = [ROOT / 'src/netpulse' / name for name in ('gui.py', 'features.py', 'monitor.py')]
        files.append(ROOT / 'live-upgrade.py')
        for file in files:
            tree = ast.parse(file.read_text())
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                        docstrings.add(id(node.body[0].value))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                    self.assertNotRegex(node.value, '[éèêàâçîïôùûÉÈÀÇ]', str(file) + ':' + str(node.lineno))
