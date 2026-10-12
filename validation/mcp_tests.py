import tempfile
import unittest
from pathlib import Path

from mcp import Client

from mcp_server import create_server


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        family = self.root / 'llm-as-code'
        (family / 'config').mkdir(parents=True)
        (family / 'shapes').mkdir()
        (family / 'config/models.yaml').write_text('models: []\n')
        (family / 'shapes/models.schema.yaml').write_text(
            'type: object\nrequired: [models]\nproperties:\n  models: {type: array}\n')
        self.server = create_server({'brb': self.root, 'cdt': self.root})

    async def test_discovery_and_annotations(self):
        async with Client(self.server) as client:
            tools = await client.list_tools()
            self.assertEqual(len(tools.tools), 2)
            for tool in tools.tools:
                self.assertTrue(tool.annotations.read_only_hint)
                self.assertFalse(tool.annotations.open_world_hint)
            result = await client.call_tool('validation_list_targets', {})
            self.assertEqual(len(result.structured_content['targets']), 2)

    async def test_validation_and_summary(self):
        async with Client(self.server) as client:
            result = await client.call_tool('validation_validate_pascode',
                                            {'target': 'cdt', 'family': 'llm-as-code'})
            self.assertTrue(result.structured_content['conforms'])
            self.assertEqual(result.structured_content['files'], 1)
            self.assertEqual(result.structured_content['results'], [])

    async def test_arbitrary_target_rejected(self):
        async with Client(self.server) as client:
            result = await client.call_tool('validation_validate_pascode', {'target': '/etc'})
            self.assertTrue(result.is_error)


if __name__ == '__main__':
    unittest.main()
