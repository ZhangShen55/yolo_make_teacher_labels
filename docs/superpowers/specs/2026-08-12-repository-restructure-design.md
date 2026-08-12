# 双 FastAPI 项目目录整理设计

## 目标

将现有教师行为标签制作服务和标签审核服务纳入同一个公开 GitHub 仓库，同时保持两者可以进入各自目录后独立安装、测试和运行。目录整理不改变 ImageDetect、VLM、数据集写入或审核业务行为。

## 目标结构

```text
yolo_make_teacher_labels/
├── make_labels/
│   ├── app/
│   ├── scripts/
│   ├── tests/
│   ├── config.example.toml
│   ├── requirements.txt
│   └── README.md
├── review_labels/
│   ├── app/
│   │   └── static/
│   ├── tests/
│   ├── requirements.txt
│   └── README.md
├── docs/
├── .gitignore
└── README.md
```

两个项目内部均使用 `app` 作为 Python 包。由于两个服务始终在独立工作目录、独立环境和独立进程中运行，这种命名不会造成运行时冲突。测试也必须分别进入两个子项目执行。

## 应用边界

`make_labels/app` 保留现有模块职责：`main.py` 组装 FastAPI 应用和 CLI，`pipeline.py` 编排流程，`detector.py` 负责 ImageDetect 契约，`vlm_labeler.py` 负责 VLM 请求与结果解析，其余模块继续按现有边界组织。当前规模不引入空洞的 `api/core/services` 多层目录。

`review_labels/app` 保留审核领域模块，并将静态资源放入包内的 `static/`。`main.py` 继续提供应用工厂和 CLI，数据集读写逻辑保持在独立模块中。

根级离线脚本和对应测试归入 `make_labels`，因为它们属于标签制作能力。

## 运行约定

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

## 仓库安全边界

公开仓库只收录源码、测试、静态资源、依赖文件、文档和脱敏配置样例。以下内容不提交：

- 含平台凭据或 VLM 密钥的 `config.toml`。
- 课堂图片、YOLO 数据集和可追溯 annotation 元数据。
- 临时帧、失败图片、服务日志和原始接口响应。
- 个人 Codex 配置与本地缓存。

## 发布顺序

1. 建立安全的原始项目基线并推送。
2. 完成等价目录迁移，分别验证两个应用后提交并推送。
3. 在 `make_labels/docs` 记录新版教师行为接口契约、目标标注流程和后续实现清单，再提交并推送。

提交消息使用中文 Conventional Commits，Git 身份仅配置在当前仓库。

## 验收

- 三套现有测试在迁移前后均通过。
- 两个应用可以从各自目录导入 `app.main` 并显示 CLI 帮助。
- Git 索引不包含真实配置、课堂数据、运行产物或个人工作区文件。
- 远端 `main` 包含三次可审计提交。
