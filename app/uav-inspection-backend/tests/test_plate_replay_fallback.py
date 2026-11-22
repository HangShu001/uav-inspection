"""车辆违停巡检：默认演示批次缺失实机素材时的回退。

PR #75 合入的前端把四宫格的第 2、3 格绑在 RViz 分屏录屏上、第 4 格绑在
GOTO 日志重建的 path.json 上，但仓库自带批次里这两份素材都没有（只随实机
数据目录交付）。结果就是干净 clone 打开 /plate 时 3 格空着、还连打两个 404，
看起来像模块坏了。

这里验证后端能在不改动数据文件、不影响实机批次的前提下就地补齐：
coverage 给出 fallback rviz，path 现场重建一条随阶段时间轴推进的示意航线。
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class PlateReplayFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # deployment_paths.DATA_ROOT 在首次导入时就被缓存。本类若先于其它测试类
        # 导入 heatmapapp.main，且不先隔离 UAV_DATA_DIR，后续测试的账号/运行期数据
        # 就会写进真实数据目录，出现「用户名已被注册」之类的串扰。
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.environment = patch.dict(os.environ, {'UAV_DATA_DIR': cls.temp.name})
        cls.environment.start()
        cls.addClassCleanup(cls.environment.stop)
        from heatmapapp.main import app
        cls.client = cls.enterClassContext(TestClient(app))

    def test_coverage_exposes_fallback_rviz(self):
        from plateapp.api import detect

        result = self.client.get('/api/v1/plate/coverage')
        self.assertEqual(result.status_code, 200, result.text)
        rviz = result.json()['data']['rviz']
        self.assertTrue(rviz['fallback'])
        self.assertIn('replay.mp4', rviz['src'])
        self.assertTrue(rviz['same_batch'])
        # 与主回放共用一条时间轴，前端 followOverview 才不会把两格拽偏。
        timeline = detect._load_json_file(detect.TIMELINE_PATH)
        self.assertEqual(rviz['offset_s'], timeline['video']['offset_s'])
        self.assertGreater(rviz['seconds'], 0)

    def test_path_returns_reconstructed_route(self):
        result = self.client.get('/api/v1/plate/path')
        self.assertEqual(result.status_code, 200, result.text)
        data = result.json()['data']
        self.assertGreaterEqual(len(data['cars']), 1)
        self.assertGreater(len(data['steps']), 0)
        times = [step['t'] for step in data['steps']]
        self.assertEqual(times, sorted(times))
        self.assertEqual(
            {step['kind'] for step in data['steps']},
            {'overview', 'capture', 'transit'},
        )
        self.assertIn('fallback', data['source'])
        self.assertEqual(
            data['area'], {'x0': -13.7, 'x1': 13.7, 'y0': -9.2, 'y1': 9.2})

    def test_fallback_path_time_matches_phases(self):
        """路径时间必须落在阶段区间内，前端 pathNow 才能逐点点亮。"""
        from plateapp.api import detect

        data = detect._fallback_path()
        timeline = detect._load_json_file(detect.TIMELINE_PATH)
        self.assertIsNotNone(data)
        self.assertGreaterEqual(
            min(step['t'] for step in data['steps']), timeline['phases'][0]['t0'])
        self.assertLessEqual(
            max(step['t'] for step in data['steps']), timeline['phases'][-1]['t1'])


if __name__ == '__main__':
    unittest.main()
