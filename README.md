# 教师行为标签制作工具

本仓库包含两个可以独立安装、测试和运行的 FastAPI 项目：

- `make_labels`：从课堂视频抽帧，结合 ImageDetect 和 VLM 制作教师行为 YOLO 标签。
- `review_labels`：在本地浏览、修改、拒收和复核已生成的 YOLO 标签。

## 项目结构

```text
make_labels/
  app/          # FastAPI 应用和标签制作流水线
  scripts/      # 本地图片批处理脚本
  tests/

review_labels/
  app/          # FastAPI 应用、审核逻辑和静态资源
  tests/
```

两个项目使用各自的 Python 环境和依赖文件。它们内部都使用 `app` 作为 Python 包，因此请先进入对应项目目录，再启动服务或运行测试。

```bash
cd make_labels
python -m app.main --config config.toml --host 127.0.0.1 --port 8010
python -m pytest tests -q
```

```bash
cd review_labels
python -m app.main --dataset /path/to/batch
python -m pytest tests -q
```

真实课堂图片、数据集、临时帧、服务日志、原始响应和包含凭据的 `config.toml` 不属于源码仓库，均由根级 `.gitignore` 排除。具体安装、配置和使用方式见各子项目 README。
