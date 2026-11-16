"""Run with: python -m unittest discover -s tests -p test_auth_policy.py.

钉住「账号体系开关」这一个行为：默认要登录，设 UAV_AUTH_ENABLED=0 则不需要。
这条开关是挂进不带 authapp 的上游平台（/uav/）的前提——同一份构建能有两种表现，
全靠它。测试只读环境变量与模块常量，不建库、不写盘。
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def fresh_api():
    """重新导入 authapp.api，让模块级 AUTH_ENABLED 重新读一次环境变量。"""
    import authapp.api as module
    return importlib.reload(module)


class AuthPolicyTests(unittest.TestCase):
    def tearDown(self):
        # 恢复默认，避免影响同进程里的其它测试
        os.environ.pop('UAV_AUTH_ENABLED', None)
        fresh_api()

    def test_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('UAV_AUTH_ENABLED', None)
            api = fresh_api()
            self.assertTrue(api.AUTH_ENABLED)
            self.assertEqual(api.policy()['data'], {'auth_enabled': True})

    def test_disabled_by_zero(self):
        for value in ('0', 'false', 'off', 'no', 'FALSE'):
            with self.subTest(value=value):
                with patch.dict(os.environ, {'UAV_AUTH_ENABLED': value}):
                    api = fresh_api()
                    self.assertFalse(api.AUTH_ENABLED)
                    self.assertEqual(api.policy()['data'], {'auth_enabled': False})

    def test_any_other_value_keeps_login(self):
        for value in ('1', 'true', 'yes', ''):
            with self.subTest(value=value):
                with patch.dict(os.environ, {'UAV_AUTH_ENABLED': value}):
                    api = fresh_api()
                    self.assertTrue(api.AUTH_ENABLED)

    def test_payload_shape_matches_platform_envelope(self):
        api = fresh_api()
        payload = api.policy()
        self.assertEqual(sorted(payload), ['code', 'data', 'message'])
        self.assertEqual(payload['code'], 200)
        self.assertIsInstance(payload['data']['auth_enabled'], bool)


if __name__ == '__main__':
    unittest.main()
