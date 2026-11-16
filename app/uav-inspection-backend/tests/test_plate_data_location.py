"""守卫车牌模块的数据落点约定（Run with: python -m unittest discover -s tests）。

约定：媒体、结果 JSON、结果卡放 `<数据根>/uav-inspection-backend/platedata/`，
模型权重与识别器放 `<数据根>/uav-inspection-backend/plateapp/`。

为什么值得单独测：2026-11-16 之前数据放在包目录 `plateapp/data/`，后果是
① 77 MB 素材跟着源码 `COPY` 进镜像层；② 容器 `--force-recreate` 后运行期写入的
timeline/coverage 全丢；③ `deployment_readiness` 查 `platedata`、接口读
`plateapp/data`，同一模块两套口径。这三条都不会在功能上立刻报错，
只会在部署时以"数据莫名消失"的形式出现，所以用测试钉住。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import deployment_readiness as readiness          # noqa: E402
import plateapp.api.detect as detect              # noqa: E402
from deployment_paths import backend_path         # noqa: E402


class PlateDataLocationTests(unittest.TestCase):
    def test_data_dir_is_the_domain_data_dir(self):
        self.assertEqual(detect.DATA_DIR, backend_path('platedata'))

    def test_data_dir_is_not_inside_the_package(self):
        pkg = BACKEND / 'plateapp'
        self.assertNotIn(pkg, detect.DATA_DIR.parents,
                         '数据又落回包目录了：会跟源码一起进镜像，且容器重建后写入丢失')
        self.assertFalse((pkg / 'data').exists(),
                         '包目录下出现了 data/：请把里面的文件搬到 <数据根>/uav-inspection-backend/platedata')

    def test_all_three_payloads_share_one_dir(self):
        for key in ('ACCEPTANCE_PATH', 'TIMELINE_PATH', 'COVERAGE_PATH'):
            self.assertEqual(getattr(detect, key).parent, detect.DATA_DIR, key)

    def test_static_dirs_are_under_data_dir(self):
        self.assertEqual(detect.CARDS_DIR, detect.DATA_DIR / 'cards')
        self.assertEqual(detect.MEDIA_DIR, detect.DATA_DIR / 'media')

    def test_readiness_and_api_read_the_same_acceptance_file(self):
        self.assertEqual(detect.ACCEPTANCE_PATH, backend_path('platedata', 'acceptance.json'))

    def test_plate_weight_stays_in_the_model_dir(self):
        self.assertEqual(readiness.MODEL_PATHS['plate'](),
                         backend_path('plateapp', 'plate-det-best.pt'))


class VersionStampTests(unittest.TestCase):
    """静态挂载无 Cache-Control，同 URL 换内容必须靠 ?v=<mtime> 破缓存。"""

    def test_existing_file_gets_one_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'x.jpg').write_bytes(b'x')
            url = detect._versioned('/api/v1/plate/cards/x.jpg', Path(tmp))
        self.assertRegex(url, r'^/api/v1/plate/cards/x\.jpg\?v=\d+$')

    def test_missing_file_is_returned_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(detect._versioned('/api/v1/plate/cards/none.jpg', Path(tmp)),
                             '/api/v1/plate/cards/none.jpg')

    def test_query_and_absolute_url_do_not_double_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'x.mp4').write_bytes(b'x')
            once = detect._versioned('/api/v1/plate/media/x.mp4', Path(tmp))
            twice = detect._versioned(once, Path(tmp))
        self.assertEqual(once.count('?'), 1)
        self.assertEqual(twice.count('?'), 1)


if __name__ == '__main__':
    unittest.main()
