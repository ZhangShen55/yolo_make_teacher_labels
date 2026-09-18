# 标注审核工具

本项目是本地 Web 标注审核工具，用于查看、修改和拒收 YOLO 格式教师行为标注。

项目可从当前目录独立安装、启动和测试：

```text
review_labels/
  app/
    __init__.py
    main.py
    static/
  tests/
  requirements.txt
  README.md
```

## 环境

```bash
conda create -y -n label_review python=3.12
conda activate label_review
python -m pip install -r requirements.txt
```

## 启动

在 `review_labels/` 项目根目录启动：

```bash
conda activate label_review
cd review_labels
python -m app.main --dataset /path/to/dataset
```

打开：

```text
http://127.0.0.1:18000
```

## 数据集结构

```text
dataset_root/
  images/
  labels/
  annotations.jsonl
  classes.txt
  raw_vlm/
```

启动时传入的数据集目录会作为默认目录。页面顶部也可以输入新的数据集目录并点击“加载文件夹”切换；新目录必须包含 `images/` 和 `labels/`，且 `images/` 中每张图片都必须在 `labels/` 中有同名 `.txt` 文件，例如 `images/a.jpg` 对应 `labels/a.txt`。

应用会按需创建：

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

## 标签规则

类别顺序固定（YOLO class id -> label）：

```text
0 sit 坐
1 stand 站
2 bbwriting 写板书
3 teach 讲授演示
4 usephone 使用手机
5 mic 手持麦克风
```

新数据集的 `classes.txt` 内容应按相同顺序填写标签名（不包含数字和中文说明）：

```text
sit
stand
bbwriting
teach
usephone
mic
```

- `sit` 和 `stand` 必须且只能选择一个。
- `bbwriting`、`teach`、`usephone` 和 `mic` 可以独立选择，也可以与姿态及其他行为同时存在。
- 同一个 bbox 多标签时，YOLO txt 写多行相同坐标。
- 新数据集的 `classes.txt` 建议按上述六行顺序维护；审核工具以内部固定映射为准，即使历史数据只有四行或没有 `classes.txt` 也可以加载。
- `4` 和 `5` 是本审核工具的 YOLO class id，不代表 ImageDetect 的 `ObjectType` 编号。
- 本项目的六类审核契约不改变 `make_labels` 的自动检测、VLM 判定或标签生成逻辑。

## 功能

- 单图精修：Canvas 显示图片、拖动 bbox、缩放 bbox、修改标签、保存、拒收。
- 图片列表：左侧图片列表每页 50 张，在“图片列表”标题右侧提供上页 / 下页。
- 批量审核：默认一页 10 张，可切换 5 / 10 / 20 / 30 / 50 张，快速修改标签、保存、拒收、进入单图精修。
- 指定文件夹：页面顶部可输入任意本机数据集目录并加载，加载前会校验 `images/`、`labels/` 和图片对应 label 文件。
- 拒收样本不会永久删除，会移动到 `rejected/`。
- 第一次写操作前会自动备份 `annotations.jsonl` 和 `labels/`。

## 测试

在 `review_labels/` 项目根目录运行：

```bash
conda run -n label_review python -m pytest tests -q
```
