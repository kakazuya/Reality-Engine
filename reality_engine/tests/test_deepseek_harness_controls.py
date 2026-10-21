"""Local checks only: no credentials, subprocesses, inference or database access."""
import unittest
from pathlib import Path

from reality_engine.scripts.run_deepseek_harness import BASE_URL, build_patch


class HarnessControlsTests(unittest.TestCase):
    def test_production_patch_stays_stable(self):
        patch = build_patch('deepseek-v4.1-flash', 'xhigh', 'OPENCODE_GO_API_KEY_2')
        self.assertEqual(patch, build_patch('deepseek-v4.1-flash', 'xhigh', 'OPENCODE_GO_API_KEY_2'))
        self.assertIn('reasoningEffort: xhigh', patch)
        self.assertIn('thinkingFormat: deepseek', patch)
        self.assertIn(BASE_URL, patch)
        self.assertNotIn('maxRetries: 0', patch)
        self.assertNotIn('disabled: true', patch)

    def test_capped_probe_disables_auxiliary_title_request(self):
        patch = build_patch('deepseek-v4.1-flash', 'off', 'OPENCODE_GO_API_KEY_2', 128,
                            'http://127.0.0.1:12345/go2/v1')
        self.assertIn('maxTokens: 128', patch)
        self.assertIn('reasoningEffort: off', patch)
        self.assertIn('off: null', patch)
        self.assertIn('- id: session-title-llm\n  disabled: true', patch)
        self.assertIn('mode: normal\n          maxRetries: 0', patch)

    def test_accounts_have_distinct_session_headers(self):
        one = build_patch('deepseek-v4.1-flash', 'xhigh', 'OPENCODE_GO_API_KEY')
        two = build_patch('deepseek-v4.1-flash', 'xhigh', 'OPENCODE_GO_API_KEY_2')
        def header(patch):
            return next(line.strip() for line in patch.splitlines() if 'x-opencode-session:' in line)
        self.assertNotEqual(header(one), header(two))

    def test_caps_can_be_changed_without_changing_routing_session(self):
        low = build_patch('deepseek-v4.1-flash', 'low', 'OPENCODE_GO_API_KEY_2', 64)
        high = build_patch('deepseek-v4.1-flash', 'xhigh', 'OPENCODE_GO_API_KEY_2', 1024)
        self.assertIn('maxTokens: 64', low)
        self.assertIn('maxTokens: 1024', high)
        self.assertEqual(next(l for l in low.splitlines() if 'x-opencode-session:' in l),
                         next(l for l in high.splitlines() if 'x-opencode-session:' in l))

    def test_heartbeat_patch_loads_local_control_plugin_without_secrets(self):
        patch = build_patch(
            'deepseek-v4.1-flash', 'xhigh', 'OPENCODE_GO_API_KEY_2',
            control={
                'plugin': Path('reality_engine/scripts/dsh_heartbeat_control.mjs').resolve(),
                'endpoint': Path('C:/tmp/run.control.json'),
            },
        )
        self.assertIn('- id: dsh-heartbeat-control', patch)
        self.assertIn('name: "file:///', patch)
        self.assertIn('endpointFile: "C:/tmp/run.control.json"', patch)
        self.assertNotIn('DSH_HEARTBEAT_TOKEN', patch)
        self.assertNotIn('X-DSH-Heartbeat-Token', patch)


if __name__ == '__main__':
    unittest.main()
