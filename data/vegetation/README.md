# 乔木高度与绿化面积运行数据

此目录保存从本地项目复制的 60 个运行文件，共 69,379,695 bytes（66.17 MiB）。
`manifest.json` 逐个记录原文件大小与 SHA-256；Git 保留这些文件的原始字节。

- `measurement_data/`：5 个地块的面积统计、掩膜、预览和浏览器点云。
- `prelabel_output/instances_20260715/`：候选树实例 CSV、统计和预览。
- `models/tree_shrub_gnb_v1/`：乔木/灌木分类基线及验证结果。
- `models/green_area_gnb_v1/`：绿化像素分类模型及验证结果。

在仓库根目录运行 `python app/scripts/install_vegetation_data.py` 安装；
仅检查数据完整性可使用 `--verify-only`。
此目录是版本化的安装来源，运行时上传与生成文件写入独立数据目录。
完整安装和 Docker 命令见 [部署说明](../../app/docs/vegetation-data.md)。

未包含原始 WebODM 影像、LAZ、训练集、候选点 CSV 或高分辨率实例 PLY。
实例目录原有 README 提及的 `tree_instances_colored.ply` 属于这些未收录的生成文件；
本包用于展示已有测量结果及网页点云，不提供完整重训输入。
