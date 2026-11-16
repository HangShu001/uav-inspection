"""D 批 L4 质量图：每格观测帧数 / 最近视角距离 / 点密度。

为什么需要这一层（方案 §3.3）：v3.0 没法回答「这块地图可不可信」，于是要么全信
（撞）要么全不信（不敢飞）。L4 就是把「可信度」显式写出来。

三个指标各管一件事，不能互相替代：
  · 观测帧数：多帧重复看到才可信。单帧看到的多半是深度拖影或边缘噪点。
  · 最近视角距离：同是 5 帧，从 1 m 看和从 5 m 看，点精度差一个量级。
  · 点密度：决定能否分辨细节（车位线 0.15 m 宽，需要足够点）。

「观测帧数」按**帧-格去重**统计：同一帧里落在同一格的多个点只算一次。
若按点数统计，近处帧会独大，远处扫过的区域被低估——这正是 v3.0 全信/全不信的成因。

用法：
    python v4d_l4_quality_20261115.py <采集目录> <输出.npz>
"""
import glob
import json
import os
import sys

import numpy as np

# 复用 A2 的反投影，保证与目标发现同一套相机模型
# 默认值与实机一致；换机器/换副本时用 UAV_V4_ROOT 指向对应 vN 目录
_V4 = os.environ.get('UAV_V4_ROOT') or os.path.expanduser('~/uav_plate/code/v4')
sys.path.insert(0, os.path.join(_V4, 'ws/src/uav_viewpoint/scripts'))
sys.path.insert(0, os.path.join(_V4, 'ccpd_code'))
import free_space_targets as fst  # noqa: E402

CELL = 0.15          # 栅格边长 m（与方案 L1 的 0.10~0.20 一致，取中）
X0, X1 = -16.0, 16.0
Y0, Y1 = -11.0, 11.0
STRIDE = 8

NX = int(round((X1 - X0) / CELL))
NY = int(round((Y1 - Y0) / CELL))


def main():
    cap = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.expanduser('~/uav_plate/data/ccpd_data/captures/map_20261114_193904')
    out = sys.argv[2] if len(sys.argv) > 2 else '/tmp/v4d_l4.npz'

    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    frames = sorted(glob.glob(os.path.join(cap, '*_depth.png')))
    print('采集目录 %s' % cap)
    print('深度帧 %d 张，栅格 %dx%d（%.2f m）x[%.1f,%.1f] y[%.1f,%.1f]'
          % (len(frames), NX, NY, CELL, X0, X1, Y0, Y1))
    # 等帧数抽样：两次跑批帧数不同时，覆盖率不可直接比（≥3 帧这类指标随帧数单调）。
    # 均匀抽稀到同一帧数，是把「帧数差异」这个混淆变量消掉的唯一办法。
    if limit and len(frames) > limit:
        n_all = len(frames)
        idx = np.unique(np.linspace(0, n_all - 1, limit).round().astype(int))
        frames = [frames[k] for k in idx]
        print('等帧数抽样：%d -> %d 帧（沿时间均匀取）' % (n_all, len(frames)))

    cnt_frames = np.zeros((NX, NY), dtype=np.int32)   # 观测帧数（帧-格去重）
    cnt_pts = np.zeros((NX, NY), dtype=np.int32)      # 累计点数
    min_dist = np.full((NX, NY), np.inf)              # 最近观测距离
    max_z = np.full((NX, NY), -np.inf)                # 该格最高点（供 L2 参考）
    used = 0

    for i, dp in enumerate(frames):
        base = dp[:-len('_depth.png')]
        try:
            P = fst.frame_points(base, STRIDE)
        except Exception:
            continue
        if P is None or not len(P):
            continue
        used += 1
        ix = np.floor((P[:, 0] - X0) / CELL).astype(np.int64)
        iy = np.floor((P[:, 1] - Y0) / CELL).astype(np.int64)
        m = (ix >= 0) & (ix < NX) & (iy >= 0) & (iy < NY)
        if not np.any(m):
            continue
        ix, iy, zz = ix[m], iy[m], P[m, 2]

        flat = ix * NY + iy
        # 点数
        cnt_pts += np.bincount(flat, minlength=NX * NY).reshape(NX, NY)
        # 帧数：先取 unique 再 +1
        uf = np.unique(flat)
        cnt_frames += np.bincount(uf, minlength=NX * NY).reshape(NX, NY)
        # 最近距离：这帧相机到各格
        try:
            meta = json.load(open(base + '_meta.json'))
            od = meta['odom_at_capture']
            cam = (float(od['x']), float(od['y']))
        except Exception:
            cam = (0.0, 0.0)
        cx = X0 + (np.arange(NX) + 0.5) * CELL
        cy = Y0 + (np.arange(NY) + 0.5) * CELL
        dx = cx[:, None] - cam[0]
        dy = cy[None, :] - cam[1]
        d = np.hypot(dx, dy)
        todo = uf
        tix, tiy = todo // NY, todo % NY
        cur = min_dist[tix, tiy]
        np.minimum.at(min_dist, (tix, tiy), d[tix, tiy])
        # 最高点
        np.maximum.at(max_z, (ix, iy), zz)

        if (i + 1) % 60 == 0:
            print('  %d/%d 帧，已用 %d' % (i + 1, len(frames), used))

    np.savez_compressed(out, cnt_frames=cnt_frames, cnt_pts=cnt_pts,
                        min_dist=min_dist, max_z=max_z,
                        cell=CELL, x0=X0, y0=Y0, nx=NX, ny=NY)
    print('已写 %s（用到 %d 帧）' % (out, used))

    # ---- 当场给一份概览，不用等第二个脚本 ----
    seen = cnt_frames > 0
    print()
    print('=== 覆盖率（场地矩形内 %d 格）===' % seen.size)
    for k in (1, 2, 3, 5, 10):
        n = int((cnt_frames >= k).sum())
        print('  观测 >=%2d 帧：%6d 格  %5.1f%%' % (k, n, 100.0 * n / seen.size))
    print()
    print('=== 点位质量分布（有点的格）===')
    nz = cnt_pts[seen]
    if len(nz):
        for q in (5, 25, 50, 75, 95):
            print('  点数 %d%% 分位 %d' % (q, int(np.percentile(nz, q))))
    md = min_dist[seen]
    md = md[np.isfinite(md)]
    if len(md):
        for q in (5, 50, 95):
            print('  最近距离 %d%% 分位 %.2f m' % (q, np.percentile(md, q)))


if __name__ == '__main__':
    main()
