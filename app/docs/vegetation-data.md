# 乔木高度与绿化面积数据安装

源码中的 `/height`、`/area` 页面依赖独立数据目录。
上传中心不能一次装齐树实例、模型和点云之间的目录关系，因此仓库提供完整的离线运行数据及安装脚本。
不需要额外下载 Release、安装 Git LFS、PDAL、WebODM 或 GPU 推理依赖。

## 本地安装

在仓库根目录执行：

```bash
python app/scripts/install_vegetation_data.py --verify-only
python app/scripts/install_vegetation_data.py
```

第一条命令核对全部 60 个文件的大小与 SHA-256；第二条校验后复制到实际数据目录。
目标目录按 `--data-dir` > `UAV_DATA_DIR` > `app/deployment-layout.json` 的顺序选择，
当前仓库默认是根目录的 `02-data/`。
使用自定义位置时，安装和后端服务必须指向同一目录，例如：

```bash
python app/scripts/install_vegetation_data.py --data-dir D:/uav-data
```

然后将服务的 `UAV_DATA_DIR` 设置为 `D:/uav-data`，按原部署方式启动服务。
安装器会保留既有相同文件；遇到内容不同的同名文件，先报错退出。
需要替换时，备份相关数据后显式加 `--overwrite`。

## Docker 命名卷安装

先拉取包含本 PR 的代码，并按原方式启动 `deploy/compose.yml`。
在仓库的 `deploy/` 目录执行：

```bash
docker compose cp ../data/vegetation uav:/tmp/vegetation-data
docker compose cp ../app/scripts/install_vegetation_data.py uav:/tmp/install_vegetation_data.py
docker compose exec uav python /tmp/install_vegetation_data.py --bundle /tmp/vegetation-data --data-dir /data
```

数据写入 Compose 已配置的 `uav-data` 卷中的 `/data`，重建容器后仍保留。
安装源不进入应用镜像，无需为导入数据重建镜像。
重复导入同一数据包时可跳过前两条命令，直接运行安装命令。
完成后刷新浏览器；以 `/uav` 子路径部署时访问 `/uav/height`、`/uav/area`。

## 数据范围与验收

| 地块 | 候选乔木数 | 绿化投影面积（m²） | 网页点云点数 |
| --- | ---: | ---: | ---: |
| 信息学院1号地 | 28 | 935.45 | 412,102 |
| 信息学院2号地 | 82 | 2,768.38 | 448,799 |
| 玫瑰园2号地 | 78 | 2,904.72 | 448,601 |
| 玫瑰园1号地 | 578 | 53,785.64 | 449,541 |
| 玫瑰园3号地 | 151 | 4,552.64 | 438,481 |
| 合计 | 917 | 64,946.83 | 2,197,524 |

安装后的目录结构：

```text
02-data/                         # Docker 中为 /data/
├── measurement_data/
│   ├── task_*/                  # 绿化/灌木统计、预览、掩膜
│   └── pointcloud_web/task_*/   # scene.json、scene.ply
├── prelabel_output/instances_20260715/task_*/
│   └── summary.json、tree_instances.csv、tree_instances_overview.png
└── models/
    ├── tree_shrub_gnb_v1/
    └── green_area_gnb_v1/
```

`GET /api/v1/vegetation/overview` 应返回 5 个任务、917 棵树以及两个模型；
各任务的 `trees`、`scene`、预览图和点云资源均应返回 200。
网页展示的是已有测量结果与基于颜色模型的点云分类。
高度为候选树实例的 P99 离地高度，候选实例可能存在过分割；
绿化面积来自正射影像伪标签训练的分类结果，模型指标和数据局限保留在各模型的训练报告中。

本包只含现有页面所需文件，最大单文件约 12.86 MiB。
原始 WebODM 重建、训练集、大型候选点 CSV 和高分辨率树实例 PLY 未收录；
重新生成全部结果仍需另行提供原始输入和处理环境。
