"""把 L4 质量栅格转成前端直接可用的 coverage.json + 热力图 PNG。

## 三个口径决定（每一个都踩过坑）

1. **分母用贴墙矩形**（x±13.7 / y±9.2），不是栅格全域 x±16 / y±11。
   围墙在 x=±14.0 / y=±9.5，墙外 2 m 本来就看不到，算进分母会把覆盖率压到 89%。

2. **再扣掉 7 辆车自身的遮挡区**。车体底下的格子被车身挡住是物理必然，
   11-15 那轮实测 5 处「覆盖缺口」有 56% 落在车体矩形内——不该计入分母。
   车体尺寸取 B 批实测的碰撞盒 4.69 × 1.88（model 4.5×1.8 × box_scale 1.0432）。

3. **观测帧数按帧-格去重**（脚本 v4d_l4_quality 已如此），不是按点数。

## 用法

    python v4e_coverage_report_20261115.py <npz> <out.json> <out.png>
"""
from __future__ import annotations

import json
import math
import os
import sys

import cv2
import numpy as np

# 贴墙内表面减 0.3 m（围墙中心 x=±14.0 / y=±9.5，墙厚约 0.2）
RECT = (-13.7, 13.7, -9.2, 9.2)

# B 批实测碰撞盒：model.sdf 4.5×1.8 × box_scale 1.0432
CAR_L, CAR_W = 4.69, 1.88

_V4_CFG = os.environ.get('UAV_V4_CFG') or os.path.expanduser(
    '~/uav_plate/code/v4/ws/src/uav_viewpoint/config')
SLOTS_YAML = os.path.join(_V4_CFG, 'parking_slots_v2.yaml')
CARS_YAML = os.path.join(_V4_CFG, 'parking_cars_v2.yaml')

# 热力图配色（BGR）：0 帧深红、>=50 帧最亮绿。
# 注意 k=0 这一档是「无观测」，判定必须用 ==0，不能用 >=0——否则会把整张图刷成同一色。
LEVELS = [
    (0, (60, 60, 120), '无观测（0 帧）'),
    (1, (72, 72, 205), '1-2 帧'),
    (3, (58, 148, 240), '3-9 帧'),
    (10, (78, 190, 120), '10-49 帧'),
    (50, (52, 130, 42), '50+ 帧'),
]
FONT_PATH = (os.environ.get('UAV_CJK_FONT')
             or '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')


def load_yaml_slots():
    import yaml
    d = yaml.safe_load(open(SLOTS_YAML, encoding='utf-8')) or {}
    return [(s['name'], float(s['x']), float(s['y'])) for s in (d.get('slots') or [])]


def load_yaml_cars():
    import yaml
    d = yaml.safe_load(open(CARS_YAML, encoding='utf-8')) or {}
    return [(c['name'], float(c['x']), float(c['y'])) for c in (d.get('cars') or [])]


def car_mask_shape(nx, ny, x0, y0, cell, cars):
    """车体矩形覆盖的格（车轴对齐场地轴，7 辆 yaw 只有 0/180，等价于无旋转）。"""
    m = np.zeros((nx, ny), bool)
    hx, hy = CAR_L / 2.0, CAR_W / 2.0
    for _nm, cx, cy in cars:
        i0 = int(math.floor((cx - hx - x0) / cell))
        i1 = int(math.ceil((cx + hx - x0) / cell))
        j0 = int(math.floor((cy - hy - y0) / cell))
        j1 = int(math.ceil((cy + hy - y0) / cell))
        i0, i1 = max(0, i0), min(nx, i1)
        j0, j1 = max(0, j0), min(ny, j1)
        m[i0:i1, j0:j1] = True
    return m


def main() -> int:
    npz_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/l4_1114.npz'
    out_json = sys.argv[2] if len(sys.argv) > 2 else 'coverage.json'
    out_png = sys.argv[3] if len(sys.argv) > 3 else 'heatmap.png'
    frames_n = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    # 采集目录名：原先硬编码成 map_20261114_190944，换一批跑批就会把错的目录名写进 JSON。
    # frames_n 是**采集深度帧数**（如 291/309），不是视频帧数——两者差一个数量级，别传错。
    map_dir = sys.argv[5] if len(sys.argv) > 5 else ''

    d = np.load(npz_path)
    cf = d['cnt_frames']
    cp = d['cnt_pts']
    md = d['min_dist']
    cell, x0, y0 = float(d['cell']), float(d['x0']), float(d['y0'])
    nx, ny = int(d['nx']), int(d['ny'])

    cx = x0 + (np.arange(nx) + 0.5) * cell
    cy = y0 + (np.arange(ny) + 0.5) * cell
    in_x = (cx >= RECT[0]) & (cx <= RECT[1])
    in_y = (cy >= RECT[2]) & (cy <= RECT[3])
    site = in_x[:, None] & in_y[None, :]

    slots = load_yaml_slots()
    cars = load_yaml_cars()
    car_m = car_mask_shape(nx, ny, x0, y0, cell, cars)

    n_site = int(site.sum())
    n_car = int((site & car_m).sum())
    obs = site & ~car_m
    n_obs = int(obs.sum())

    coverage = []
    for k in (1, 3, 10):
        n = int(((cf >= k) & obs).sum())
        coverage.append({'min_frames': k, 'cells': n,
                         'ratio': round(100.0 * n / max(n_obs, 1), 2)})

    # ---- 分三排统计（x = -8.28 / 0 / +8.28，各 5 个车位）----
    rows = []
    for label, xc in (('左排', -8.28), ('中排', 0.0), ('右排', 8.28)):
        band = obs & (np.abs(cx[:, None] - xc) <= 6.25) & (np.abs(cy[None, :]) <= 6.25)
        n = int(band.sum())
        if not n:
            continue
        f = cf[band]
        rows.append({
            'label': label, 'x': xc, 'cells': n,
            'ge1': round(100.0 * float((f >= 1).mean()), 1),
            'ge3': round(100.0 * float((f >= 3).mean()), 1),
            'median_frames': int(np.median(f)),
        })

    # ---- 15 个车位处的质量（3×3 邻域取最大，避开格边界）----
    slot_rows = []
    for nm, sx, sy in slots:
        ix = int((sx - x0) / cell)
        iy = int((sy - y0) / cell)
        sl = (slice(max(0, ix - 1), ix + 2), slice(max(0, iy - 1), iy + 2))
        slot_rows.append({
            'name': nm, 'x': round(sx, 2), 'y': round(sy, 2),
            'frames': int(cf[sl].max()), 'points': int(cp[sl].max()),
            'min_dist': round(float(np.min(md[sl])), 2),
        })

    sub = cf[obs]
    payload = {
        'source': {
            'map_dir': map_dir or 'unknown',
            'frames_used': frames_n or None,
            'cell_m': cell, 'grid': [nx, ny],
            'rect': list(RECT),
            'note': '分母 = 贴墙矩形扣除 7 辆车体遮挡区；观测帧数按帧-格去重',
        },
        'area': {
            'site_cells': n_site,
            'car_cells': n_car,
            'observable_cells': n_obs,
        },
        'coverage': coverage,
        'depth': {
            'frames_p50': int(np.median(sub)),
            'frames_p95': int(np.percentile(sub, 95)),
            'dist_p50': round(float(np.median(md[obs])), 2),
            'dist_p95': round(float(np.percentile(md[obs], 95)), 2),
            'pts_p50': int(np.median(cp[obs])),
        },
        'rows': rows,
        'slots': slot_rows,
        'image': '/api/v1/plate/media/heatmap.png',
    }
    with open(out_json, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    # ---- 热力图 ----
    # cf 的索引是 [x, y]，图像是 [row=y, col=x]，所以所有画图操作走转置后的视图
    cf_t = cf.T
    site_t = site.T
    scale = 3
    img = np.zeros((ny, nx, 3), np.uint8)
    img[:] = (26, 26, 28)              # 墙外
    img[site_t] = (62, 62, 66)         # 场地内、无观测
    # 必须由低到高画：低阈值先铺底，高阈值再覆盖，否则最后画的 >=1 会把全图刷红
    for k, color, _lab in LEVELS[1:]:
        img[cf_t >= k] = color
    img = cv2.resize(img, (nx * scale, ny * scale), interpolation=cv2.INTER_NEAREST)

    def W2P(wx, wy):
        return (int((wx - x0) / cell * scale), int((wy - y0) / cell * scale))

    # 车位框（白）
    for _nm, sx, sy in slots:
        p0, p1 = W2P(sx - 1.25, sy - 2.65), W2P(sx + 1.25, sy + 2.65)
        cv2.rectangle(img, p0, p1, (235, 235, 235), 1, cv2.LINE_AA)
    # 车体（灰填充 + 轮廓）
    for _nm, ccx, ccy in cars:
        p0, p1 = W2P(ccx - CAR_L / 2, ccy - CAR_W / 2), W2P(ccx + CAR_L / 2, ccy + CAR_W / 2)
        cv2.rectangle(img, p0, p1, (150, 150, 155), -1)
        cv2.rectangle(img, p0, p1, (200, 200, 205), 1, cv2.LINE_AA)
    # 场地矩形
    cv2.rectangle(img, W2P(RECT[0], RECT[2]), W2P(RECT[1], RECT[3]), (120, 200, 255), 1)

    # 图例色块（文字交给 PIL——cv2 的 Hershey 字体画不了中文）
    lx, ly = 12, 12
    for _k, color, _lab in LEVELS:
        cv2.rectangle(img, (lx, ly), (lx + 16, ly + 16), color, -1)
        cv2.rectangle(img, (lx, ly), (lx + 16, ly + 16), (215, 215, 215), 1)
        ly += 24

    # 底部留一条底边放说明，否则文字会被场地边缘/车体块压住
    pad = 26
    canvas = np.zeros((img.shape[0] + pad, img.shape[1], 3), np.uint8)
    canvas[:] = (22, 22, 24)
    canvas[:img.shape[0]] = img
    img = canvas

    from PIL import Image, ImageDraw, ImageFont
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).convert('RGBA')
    w = img.shape[1]

    # 半透明底：图例与统计都压在色块上，不加底会看不清（尤其红底上的绿字）
    overlay = Image.new('RGBA', pil.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([8, 6, 146, 10 + 24 * len(LEVELS)], fill=(0, 0, 0, 145))
    od.rectangle([w - 190, 8, w - 10, 66], fill=(0, 0, 0, 145))
    pil = Image.alpha_composite(pil, overlay)

    dr = ImageDraw.Draw(pil)
    f_lg = ImageFont.truetype(FONT_PATH, 16, index=2)
    f_sm = ImageFont.truetype(FONT_PATH, 13, index=2)
    ly = 11
    for _k, _c, lab in LEVELS:
        dr.text((lx + 24, ly), lab, font=f_sm, fill=(238, 238, 238))
        ly += 24
    dr.text((w - 180, 14), '可观测区 %d 格' % n_obs, font=f_lg, fill=(255, 255, 255))
    # 不用 ≥ 号：该字形在部分 Noto CJK face 里缺字，会渲染成方框
    dr.text((w - 180, 38), '3 帧以上 %.1f%%' % coverage[1]['ratio'],
            font=f_lg, fill=(130, 245, 170))
    dr.text((12, img.shape[0] - 21),
            'L4 覆盖质量 · 栅格 %.2f m · 观测 %d 帧 · 已扣车体遮挡'
            % (cell, frames_n), font=f_sm, fill=(210, 210, 210))
    pil.convert('RGB').save(out_png)

    print('场地 %d 格 / 车体占用 %d 格 / 可观测 %d 格' % (n_site, n_car, n_obs))
    for c in coverage:
        print('  >=%2d 帧  %6d 格  %5.1f%%' % (c['min_frames'], c['cells'], c['ratio']))
    for r in rows:
        print('  %s x=%+.2f  中位 %d 帧  >=3 帧 %.1f%%' % (r['label'], r['x'], r['median_frames'], r['ge3']))
    print('→ %s / %s' % (out_json, out_png))
    return 0


if __name__ == '__main__':
    sys.exit(main())
