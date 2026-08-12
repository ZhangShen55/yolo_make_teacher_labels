# 标注审核工具设计

## 目标

构建一个本地 Web 工具，用于审核、修正和拒收教师行为检测数据的图片标注。

第一版测试数据集为：

```text
测试数据/teacher-vlm-labels/
```

项目必须创建在当前仓库的：

```text
app/
```

项目必须运行在独立 conda 环境中：

```text
label_review
```

该工具需要读取已有图片目录和 YOLO 标签目录，在图片上显示 bbox 和标签，允许用户修改标签与 bbox，并把不合格样本移动到可恢复的 `rejected/` 区域，而不是永久删除。

## 合格指标

满足以下全部条件，项目才算合格。

1. 环境
   - 应用位于 `app/`。
   - 应用运行在 conda 环境 `label_review`。
   - README 中写清楚启动命令，并且命令可用：

     ```bash
     conda activate label_review
     cd app
     python main.py --dataset ../测试数据/teacher-vlm-labels
     ```

   - 本地页面可通过 `http://127.0.0.1:8000` 打开。

2. 数据集加载
   - 能加载 `images/`、`labels/`、`annotations.jsonl`、`classes.txt`。
   - 页面顶部支持输入新的本机数据集目录并加载。
   - 加载前必须校验目标目录存在 `images/` 和 `labels/`。
   - `images/` 中每张图片都必须在 `labels/` 中存在同名 `.txt`，否则拒绝加载并显示错误。
   - 页面显示图片总数、有效样本数、已拒收样本数和标签统计。
   - 使用 `teacher-vlm-labels` 测试时，在没有拒收任何样本前，页面应列出 95 张有效图片。

3. 图片与标注显示
   - 每张图片以稳定比例展示。
   - YOLO 标注能转换成像素 bbox，并在图上显示到正确位置。
   - 能显示 `sit`、`stand`、`bbwriting`、`teach` 四类标签。
   - 支持同一个 bbox 上有多个标签，例如 `stand + teach`。
   - 支持批量审核视图，一页默认显示 10 张图片，每张图片都显示 bbox 和当前标签。

4. 标签编辑
   - 支持编辑四个标签。
   - `sit` 和 `stand` 必须互斥。
   - `bbwriting` 和 `teach` 可以独立勾选，也可以同时存在。
   - 保存后同时更新 `labels/*.txt` 和 `annotations.jsonl`。
   - 刷新页面后，修改结果仍然存在。
   - 批量审核视图中可以直接修改单张卡片的标签并保存，不必进入单图模式。

5. bbox 编辑
   - 支持拖动整个 bbox。
   - 支持拖动边和角来调整 bbox 大小。
   - bbox 必须限制在图片边界内。
   - 保存时 bbox 写回归一化 YOLO 格式：`x_center y_center width height`。
   - 如果一个 bbox 有多个标签，YOLO 文件中写多行，但这些行使用相同归一化坐标。

6. 拒收行为
   - 拒收样本不做永久删除。
   - 拒收图片移动到 `rejected/images/`。
   - 拒收 YOLO txt 移动到 `rejected/labels/`。
   - 如果存在匹配的 `raw_vlm/{image_id}.json`，移动到 `rejected/raw_vlm/`。
   - 拒收 annotation 记录追加到 `rejected/annotations.jsonl`。
   - 主 `annotations.jsonl` 不再包含已拒收样本。
   - 每次拒收操作追加一条审计事件到 `rejected/reject-log.jsonl`。
   - 页面刷新后，已拒收样本不再出现在有效图片列表中。

7. 审核效率
   - 支持上一张 / 下一张。
   - 支持保存并跳到下一张。
   - 支持单图精修模式和批量审核模式切换。
   - 批量审核模式默认每页 10 张，可翻页，并可切换每页显示 5 / 10 / 20 / 30 / 50 张。
   - 支持按文件名搜索。
   - 支持按标签和 `needs_review` 过滤。
   - 支持快捷键：上一张、下一张、保存、拒收。

8. 数据安全
   - 每次服务启动后的第一次写操作前，自动在 `backups/` 下创建备份。
   - 更新 JSONL 和 txt 时使用临时文件加原子替换，避免写坏文件。
   - 所有路径访问限制在选定数据集根目录内。
   - 拒收操作可恢复：可以从 `rejected/` 中把文件移回主数据集。

9. 使用 `teacher-vlm-labels` 验收
   - 能加载 95 张图片。
   - 批量审核模式显示 10 张 / 页，共 10 页，最后一页 5 张。
   - 随机修改 3 张图片的标签后，txt 和 JSONL 均正确更新。
   - 随机修改 3 张图片的 bbox 后，txt 和 JSONL 均正确更新。
   - 拒收 2 张图片后，有效样本数变为 93。
   - `rejected/images/` 和 `rejected/labels/` 各新增 2 个文件。
   - 重启服务后，所有保存状态保持正确。

## 架构

第一版采用 FastAPI 本地后端，加原生 HTML/CSS/JavaScript 前端。前端使用 Canvas 实现 bbox 显示、拖动和缩放。

```text
app/
  main.py
  requirements.txt
  README.md
  label_review/
    __init__.py
    dataset.py
    yolo.py
    annotations.py
    review_ops.py
    schemas.py
  static/
    index.html
    app.js
    style.css
  tests/
    test_yolo.py
    test_annotations.py
    test_review_ops.py
```

模块职责：

- `main.py`：FastAPI 应用入口，提供静态页面，接收命令行数据集参数，并支持运行时切换当前数据集。
- `dataset.py`：校验数据集根目录，扫描图片，关联图片、标签和 annotation，计算统计信息。
- `yolo.py`：解析和写入 YOLO txt，负责 YOLO 归一化坐标与像素 bbox 互转。
- `annotations.py`：读取、写入、更新 `annotations.jsonl`，移除被拒收记录。
- `review_ops.py`：保存操作、备份创建、拒收移动、原子写入。
- `schemas.py`：API 请求和响应模型。
- `static/app.js`：图片列表、Canvas 渲染、bbox 拖动缩放、标签控件、API 调用。

浏览器不直接写文件。所有持久化修改都由 FastAPI 后端完成。

## 数据集格式

有效数据集根目录预期包含：

```text
dataset_root/
  images/
  labels/
  annotations.jsonl
  classes.txt
  raw_vlm/
```

`images/` 和 `labels/` 为必需目录。`annotations.jsonl`、`classes.txt`、`raw_vlm/` 可用于补充信息和拒收移动，但页面加载新目录时，硬性校验以图片和 YOLO txt 的一一对应为准：`images/{image_id}.jpg`、`images/{image_id}.png` 等图片必须存在 `labels/{image_id}.txt`。

应用会按需创建运行目录：

```text
dataset_root/
  backups/
  rejected/
    images/
    labels/
    raw_vlm/
    annotations.jsonl
    reject-log.jsonl
```

本项目的 `classes.txt` 顺序固定为：

```text
sit
stand
bbwriting
teach
```

YOLO txt 每行格式为：

```text
class_id x_center y_center width height
```

同一 bbox 多标签示例：

```text
1 0.520833 0.671296 0.127083 0.314815
3 0.520833 0.671296 0.127083 0.314815
```

上面两行坐标相同，`class_id` 分别为 `1` 和 `3`，表示同一个 bbox 同时标注 `stand` 和 `teach`。

## 页面设计

页面采用偏工作台的审核布局，避免做成展示型页面。

页面提供两种审核模式：

1. 单图精修模式：用于拖动 / 缩放 bbox、精确查看和修改单张图片。
2. 批量审核模式：用于一页查看 10 张图片，快速确认标签、修改标签或拒收样本。

顶部工具栏包含模式切换：

```text
[单图精修] [批量审核]   中间显示 10 张   搜索 frame_...   标签过滤   needs_review
```

### 单图精修模式

```text
┌──────────────────────────────────────────────────────────────┐
│ Dataset: teacher-vlm-labels     total 95 | active 95 | ...   │
├───────────────┬──────────────────────────────────┬───────────┤
│ 图片列表       │ 图片 Canvas                       │ 标注面板   │
│ 搜索/过滤      │ bbox overlay                      │ 标签       │
│ 缩略图         │ 拖动 / 缩放控制点                  │ bbox 数值  │
│ 状态标记       │ 缩放 / 适配                         │ 操作按钮   │
└───────────────┴──────────────────────────────────┴───────────┘
```

左侧面板：

- 数据集统计。
- 按文件名搜索。
- 按标签过滤：`sit`、`stand`、`bbwriting`、`teach`。
- 按 `needs_review` 过滤。
- 可滚动图片列表，当前图片高亮。

中间面板：

- 用 Canvas 渲染当前图片。
- 使用红色线条显示 bbox。
- bbox 的边和角显示可拖动控制点。
- bbox 附近显示当前标签。
- 图片适配容器尺寸时，坐标换算必须准确。

右侧面板：

- 文件名。
- 当前标签。
- 姿态单选：`sit` 或 `stand`。
- 行为复选：`bbwriting`、`teach`。
- 像素 bbox 输入框：`x1`、`y1`、`x2`、`y2`。
- 归一化 YOLO bbox 预览。
- 操作按钮：
  - 保存
  - 保存并下一张
  - 拒收样本
  - 重置当前未保存修改

快捷键：

- `ArrowRight`：下一张。
- `ArrowLeft`：上一张。
- `Ctrl+S` 或 `Cmd+S`：保存。
- `Shift+Enter`：保存并下一张。
- `Delete`：确认后拒收样本。
- `Esc`：重置当前未保存修改。

### 批量审核模式

批量审核模式默认每页展示 10 张图片，支持切换为 5 / 10 / 20 / 30 / 50 张，使用响应式网格展示：

```text
┌──────────────────────────────────────────────────────────────┐
│ Dataset: teacher-vlm-labels   批量审核   page 1 / 10          │
├──────────────────────────────────────────────────────────────┤
│ [card 1] [card 2] [card 3] [card 4] [card 5]                 │
│ [card 6] [card 7] [card 8] [card 9] [card 10]                │
├──────────────────────────────────────────────────────────────┤
│ 上一页                                      下一页            │
└──────────────────────────────────────────────────────────────┘
```

每张卡片包含：

- 图片预览。
- bbox 和标签 overlay。
- 文件名。
- 姿态单选：`sit` / `stand`。
- 行为复选：`bbwriting` / `teach`。
- 保存按钮。
- 拒收按钮。
- 进入精修按钮。

批量审核模式的边界：

- 可以修改标签。
- 可以拒收样本。
- 可以点击“进入精修”跳到单图精修模式修改 bbox。
- 第一版不在批量卡片内直接拖动 bbox，避免一页 10 张图同时存在复杂 Canvas 交互导致误操作。

## bbox 编辑

前端维护三套坐标：

1. 图片像素坐标：真实图片坐标。
2. Canvas 显示坐标：页面缩放后的显示坐标。
3. YOLO 归一化坐标：最终持久化坐标。

所有编辑操作先修改像素坐标，保存时再转换成 YOLO 归一化坐标。

编辑规则：

- 拖动 bbox 内部，移动整个 bbox。
- 拖动角控制点，同时调整两个方向。
- 拖动边控制点，只调整单侧。
- bbox 自动限制在图片边界内。
- 最小宽高默认 `4px`。
- 多行 YOLO 如果坐标相同，UI 将其视作一个多标签 bbox。

第一版主要支持“一张图一个老师 bbox”的预期流程，但后端解析不能因为某个文件存在多个 bbox 而崩溃。

## API 设计

`GET /`

- 返回审核工具页面。

`GET /api/dataset/summary`

返回：

```json
{
  "dataset_root": "...",
  "total": 95,
  "active": 95,
  "rejected": 0,
  "label_counts": {
    "sit": 0,
    "stand": 95,
    "bbwriting": 0,
    "teach": 95
  }
}
```

`POST /api/dataset/load`

请求：

```json
{
  "dataset_root": "/absolute/or/relative/dataset"
}
```

行为：

- 校验目录存在。
- 校验目录下存在 `images/` 和 `labels/`。
- 校验 `images/` 中每张支持格式图片都有 `labels/{image_id}.txt`。
- 校验失败时返回 `400`，并保持当前已加载数据集不变。
- 校验成功后切换当前数据集，并返回新的 summary 和 validation 信息。

`GET /api/images`

查询参数：

- `q`：可选，按文件名搜索。
- `label`：可选，按标签过滤。
- `needs_review`：可选，按是否需要复检过滤。
- `page`：可选，分页页码，默认 `1`。
- `page_size`：可选，每页数量，默认 `10`，第一版最大 `50`。

返回分页图片列表：

```json
{
  "page": 1,
  "page_size": 10,
  "total": 95,
  "items": [
    {
      "image_id": "frame_000001",
      "file_name": "frame_000001.jpg",
      "labels": ["stand", "teach"],
      "needs_review": false,
      "has_label": true
    }
  ]
}
```

`GET /api/images/batch`

查询参数：

- `page`：页码，默认 `1`。
- `page_size`：每页数量，默认 `10`，第一版最大 `50`。
- `q`、`label`、`needs_review`：与 `GET /api/images` 相同。

返回批量审核卡片所需数据，包括每张图片的 bbox、标签、宽高和图片 URL：

```json
{
  "page": 1,
  "page_size": 10,
  "total": 95,
  "items": [
    {
      "image_id": "frame_000001",
      "file_name": "frame_000001.jpg",
      "image_url": "/api/images/frame_000001/file",
      "width": 1920,
      "height": 1080,
      "boxes": [
        {
          "box_id": "0",
          "box_xyxy": [878, 555, 1122, 895],
          "labels": ["stand", "teach"]
        }
      ],
      "needs_review": false
    }
  ]
}
```

`GET /api/images/{image_id}`

返回单张图的 annotation 和像素 bbox：

```json
{
  "image_id": "frame_000001",
  "file_name": "frame_000001.jpg",
  "width": 1920,
  "height": 1080,
  "boxes": [
    {
      "box_id": "0",
      "box_xyxy": [878, 555, 1122, 895],
      "box_norm_xywh": [0.520833, 0.671296, 0.127083, 0.314815],
      "labels": ["stand", "teach"]
    }
  ],
  "reason": "老师站立在课堂中，正在进行讲授演示",
  "needs_review": false
}
```

`GET /api/images/{image_id}/file`

- 返回图片文件流。

`PATCH /api/images/{image_id}/annotation`

请求：

```json
{
  "boxes": [
    {
      "box_id": "0",
      "box_xyxy": [878, 555, 1122, 895],
      "labels": ["stand", "teach"]
    }
  ],
  "needs_review": false
}
```

行为：

- 校验标签。
- 强制 `sit` / `stand` 互斥。
- 将 bbox 转换为 YOLO 归一化格式。
- 更新 `labels/{image_id}.txt`。
- 更新主 `annotations.jsonl`。
- 返回保存后的 annotation。

`POST /api/images/{image_id}/reject`

请求：

```json
{
  "reason": "label_wrong_or_bad_frame"
}
```

行为：

- 移动图片到 `rejected/images/`。
- 移动 txt 到 `rejected/labels/`。
- 如果存在匹配的 raw VLM 响应，移动到 `rejected/raw_vlm/`。
- 追加 annotation 到 `rejected/annotations.jsonl`。
- 从主 `annotations.jsonl` 移除该 annotation。
- 追加操作事件到 `rejected/reject-log.jsonl`。
- 返回更新后的 summary。

## 文件写入策略

服务启动后第一次发生写操作时，创建一次备份：

```text
backups/
  20260609-HHMMSS/
    annotations.jsonl
    labels/
```

所有写入使用原子替换：

1. 写入内容到 `*.tmp`。
2. flush 并关闭文件。
3. 用原子 rename 替换目标文件。

拒收流程：

1. 确保备份已创建。
2. 移动图片到 `rejected/images/`。
3. 移动 label txt 到 `rejected/labels/`。
4. 如果存在匹配 raw VLM 响应，移动到 `rejected/raw_vlm/`。
5. 使用原子重写追加 annotation 到 rejected JSONL。
6. 使用原子重写从 active JSONL 移除 annotation。
7. 追加操作事件到 `reject-log.jsonl`。

如果目标 rejected 文件已存在，自动加后缀：

```text
frame_000001.jpg
frame_000001.1.jpg
frame_000001.2.jpg
```

## 校验规则

标签：

- 允许标签：`sit`、`stand`、`bbwriting`、`teach`。
- `sit` 和 `stand` 必须且只能存在一个。
- `bbwriting` 和 `teach` 可选，可以同时存在。
- 空标签非法。

bbox：

- `x1 < x2`，`y1 < y2`。
- 坐标限制在图片边界内。
- 最小宽高：`4px`。
- YOLO 归一化值保留六位小数。

路径：

- 数据集根目录解析为绝对路径。
- 所有图片、标签、JSONL 路径必须位于数据集根目录内。
- 服务启动后，浏览器 API 不再接受任意文件路径，只接受 `image_id`。

## 测试计划

后端单元测试：

- YOLO 行解析和写入。
- YOLO 归一化坐标转像素坐标。
- 像素坐标转 YOLO 归一化坐标。
- 相同 bbox 的多标签合并。
- `sit` / `stand` 互斥校验。
- 更新 `annotations.jsonl` 时保留无关记录。
- 拒收操作把图片和 txt 移动到 rejected 文件夹。
- 存在 raw VLM 响应时，拒收操作同步移动该文件。
- 拒收操作移除 active annotation，并写入 rejected annotation。
- 第一次写操作前创建备份。
- 分页查询能按 `page_size=10` 返回正确切片。

临时数据集集成测试：

- 加载数据集 summary。
- 加载批量审核页，验证 `page_size=10` 时返回 10 条。
- PATCH annotation 后，验证 txt 和 JSONL 同步更新。
- 拒收样本后，验证文件移动和统计变化。

使用 `teacher-vlm-labels` 手工验收：

- 启动应用：

  ```bash
  python main.py --dataset ../测试数据/teacher-vlm-labels
  ```

- 确认加载 95 张图片。
- 切换到批量审核模式，确认第一页显示 10 张图片。
- 翻到最后一页，确认显示 5 张图片。
- 在批量审核模式修改 3 张图片的标签并刷新确认。
- 修改 3 张图片的标签并刷新确认。
- 拖动 / 缩放 3 张图片的 bbox 并刷新确认。
- 拒收 2 张图片，确认 active 数量变为 93。
- 确认 rejected 文件存在于 `rejected/images/` 和 `rejected/labels/`。

## 第一版不做的内容

- 不在审核 UI 中运行 YOLO / ImageDetect / VLM。
- 不做多人协作。
- 不做云存储或远程数据集浏览。
- 不做完整撤销历史，只依赖 backup 和 rejected 可恢复性。
- 不做 CVAT 级别的多形状标注工具。

## 实现备注

- 依赖尽量少：`fastapi`、`uvicorn`、`pydantic`、`pillow`、`pytest`。
- 第一版前端不引入框架，直接使用原生 HTML/CSS/JavaScript。
- 页面应偏密集、偏操作台，不做营销页风格。
- 第一版只做本地工具，不需要登录认证。
- 因为工具会修改文件，页面必须显著展示当前数据集根目录。
