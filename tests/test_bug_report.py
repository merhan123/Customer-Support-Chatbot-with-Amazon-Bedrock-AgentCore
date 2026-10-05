import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class BugReportTests(unittest.TestCase):
    def setUp(self):
        self.table = Mock()
        fake_boto = types.SimpleNamespace(resource=lambda _: types.SimpleNamespace(Table=lambda _: self.table))
        path = Path(__file__).resolve().parents[1] / 'create_bug_report.py'
        spec = importlib.util.spec_from_file_location('bug_report_under_test', path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'boto3': fake_boto}), patch.dict(os.environ, {'TABLE_NAME': 'offline'}):
            spec.loader.exec_module(self.module)
        self.valid = dict(description='Checkout is broken', stepsToReproduce='Click checkout', environment='Firefox on Linux')

    def test_valid_report_is_written(self):
        result = self.module.lambda_handler(self.valid, None)
        self.assertEqual(result['status'], 'OPEN')
        self.assertEqual(self.table.put_item.call_args.kwargs['Item']['description'], self.valid['description'])

    def test_non_string_values_are_rejected(self):
        for value in (False, 123, ['text'], {'text': 'value'}, None):
            with self.subTest(value=value):
                result = self.module.lambda_handler(dict(self.valid, environment=value), None)
                self.assertIn('error', result)
        self.table.put_item.assert_not_called()

    def test_empty_field_rejected(self):
        self.assertIn('error', self.module.lambda_handler(dict(self.valid, description='  '), None))
        self.table.put_item.assert_not_called()

    def test_malformed_parameter_container(self):
        for value in (1, 'text', {}, None):
            self.assertIn('error', self.module.lambda_handler({'messageVersion': '1', 'parameters': value}, None))
        self.table.put_item.assert_not_called()

    def test_parameter_envelope(self):
        event = {'messageVersion': '1', 'parameters': [{'name': k, 'value': v} for k, v in self.valid.items()]}
        self.assertEqual(self.module.lambda_handler(event, None)['status'], 'OPEN')

    def test_invalid_parameter_name_is_ignored(self):
        self.assertEqual(self.module._normalize_payload({'messageVersion': '1', 'parameters': [{'name': [], 'value': 'x'}]}), {})

    def test_storage_failure_returns_error(self):
        self.table.put_item.side_effect = RuntimeError('offline')
        self.assertIn('error', self.module.lambda_handler(self.valid, None))

    def test_unsupported_tool_does_not_write(self):
        context = types.SimpleNamespace(client_context=types.SimpleNamespace(custom={'bedrockAgentCoreToolName': 'bad'}))
        self.assertIn('error', self.module.lambda_handler(self.valid, context))
        self.table.put_item.assert_not_called()


if __name__ == '__main__':
    unittest.main()
