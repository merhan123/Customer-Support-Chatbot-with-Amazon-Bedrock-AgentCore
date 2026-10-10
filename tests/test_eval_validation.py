import importlib.util
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class EvaluationValidationTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('eval_under_test', ROOT/'generate-eval-dataset-workaround.py')
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'boto3': types.ModuleType('boto3')}), patch.object(sys, 'path', [str(ROOT), *sys.path]):
            spec.loader.exec_module(self.module)
        self.client = Mock()
        self.client.invoke.return_value = {'Payload': io.BytesIO(b'{"ticketId":"offline","status":"OPEN"}')}

    def test_placeholder_report_never_invokes_lambda(self):
        result = self.module.invoke_lambda(self.client, 'offline', {'description':'description', 'stepsToReproduce':'steps', 'environment':'unknown'})
        self.client.invoke.assert_not_called()
        self.assertIn('error', result)

    def test_non_object_never_invokes_lambda(self):
        for value in [None, [], 'invalid']:
            with self.subTest(value=value):
                self.assertIn('error', self.module.invoke_lambda(self.client, 'offline', value))
        self.client.invoke.assert_not_called()

    def test_valid_report_preserves_payload(self):
        args = {'description':'Checkout is broken', 'stepsToReproduce':'Click checkout button', 'environment':'Firefox on Linux'}
        result = self.module.invoke_lambda(self.client, 'offline', args)
        self.assertEqual(result['ticketId'], 'offline')
        self.assertEqual(json.loads(self.client.invoke.call_args.kwargs['Payload']), args)


if __name__ == '__main__':
    unittest.main()
