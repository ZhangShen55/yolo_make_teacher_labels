# 新版教师行为接口验证 Harness 记录

## 记录信息

- 验证日期：2026-08-12（Asia/Shanghai）
- 被验证提交：`abda118a682ee29307668d0498f2ca002c39d21f`
- 接口路由：`POST /ImageDetect/teacher/v1.0.0`
- 目标部署：本地忽略配置中的 `8871` 实例；本文不记录内网主机
- Python：`make_label` 与 `label_review` 均为 `3.12.13`
- 视频工具：`ffmpeg` / `ffprobe 7.1.1`

本记录用于保存新版教师行为契约的可复查验证证据。原始课堂图片、图片 Base64、真实配置、凭据和完整接口响应均不进入 Git。

## 自动化 Harness

在两个独立项目目录执行：

```bash
cd make_labels
conda run -n make_label python -m pytest tests -q
conda run -n make_label python -m compileall -q app scripts tests
conda run -n make_label python -m pip check
conda run -n make_label python -m app.main --help
conda run -n make_label python -m scripts.teacher_vlm_labeler --help

cd ../review_labels
conda run -n label_review python -m pytest tests -q
conda run -n label_review python -m compileall -q app tests
conda run -n label_review python -m pip check
conda run -n label_review python -m app.main --help
```

验证结果：

| 项目 | 结果 |
| --- | --- |
| `make_labels` 测试 | `106 passed` |
| `review_labels` 测试 | `21 passed` |
| 两项目 `compileall` | 通过 |
| 两项目 `pip check` | `No broken requirements found` |
| 主服务、审核服务、离线脚本 CLI | `--help` 正常退出 |

## 契约覆盖矩阵

| 场景 | 预期 | Harness 结果 |
| --- | --- | --- |
| `100` 主体框 | 最终 YOLO 框只来自主体框 | 通过 |
| `201/202/203/204` | 映射为 `sit/stand/bbwriting/teach` | 通过 |
| `205` | 契约错误，不生成该图片标签 | 通过 |
| 行为框为 `null` | 仍按 `ObjectCount>0` 汇总行为 | 通过 |
| 多主体框 | 置信度、面积、原始索引稳定选择并复核 | 通过 |
| 坐站冲突/姿态回退 | `needs_review=true` | 通过 |
| detector 与 VLM 标签不同 | `needs_review=true` | 通过 |
| 缺少有效 `100` 框 | 进入失败流程，不用行为框替代 | 通过 |
| 缺图、未知或重复 `ImageId` | 检测失败 | 通过 |
| `429/500/503`、连接错误、超时 | 总请求不超过 3 次 | 通过 |
| `422` 和其他 `4xx` | 不重试 | 通过 |
| HTTP 错误回显图片 data URL | Base64 脱敏 | 通过 |
| 同 stem 不同后缀图片 | 请求 ID 与输出文件均不冲突 | 通过 |
| 中文候选标签 | 固定顺序并始终位于主体框上方 | 通过 |
| 多标签 YOLO | VLM 最终标签共用同一 `100` 坐标 | 通过 |

## 真实接口 Smoke Harness

输入为本地被 Git 忽略的教师全景 JPEG，分辨率 `1920x1080`。只调用新版 ImageDetect 和本地解析/渲染链路，没有在该 smoke 中调用 Ark VLM。

脱敏响应摘要：

```json
{
  "http_status": "2xx",
  "root_status_code": 0,
  "image_status_code": 0,
  "object_types": [100, 201, 202, 203, 204],
  "object_counts": {"100": 1, "201": 0, "202": 1, "203": 0, "204": 1},
  "subject_box_count": 1,
  "confidence_location": "DataList[].ResultList[].ObjectPostList[].Confidence",
  "behavior_box_shapes": {
    "201": "null",
    "202": "list[1]",
    "203": "null",
    "204": "list[1]"
  },
  "legacy_205_present": false,
  "candidate_labels": ["stand", "teach"],
  "needs_review": false
}
```

结论：真实实例返回结构与 v6 契约一致；`100` 提供唯一主体框，`202` 和 `204` 分别解析为“站立”和“讲授”，置信度位于框对象，空行为框可为 `null`，未出现旧 `205`。

## 视觉 Harness

使用真实 smoke 结果生成 VLM 预览图并人工检查：

- 红框来自 `ObjectType=100`。
- 中文文本为 `站立 | 讲授`。
- 文本完整位于红框上方，没有遮挡主体。
- 原始图像坐标没有因预览画布扩展而改变。

测试 fixture 另覆盖 `202+203+204`，要求预览文本严格为 `站立 | 板书 | 讲授`，并用像素行检查验证蓝色文字位于红框上方。

## 安全与提交边界

- `make_labels/config.toml` 由 Git 忽略，只在本地保存真实目标地址和凭据。
- Harness 不保存原始图片、Base64、完整响应或带认证参数的视频 URL。
- 提交前对 staged diff 扫描内网主机、长 Base64 和真实凭据模式，未命中。
- VLM 的保留、删除、补充和最终 YOLO 写盘由自动化测试覆盖；本次真实 smoke 不声明 Ark 端到端联调。

## 最终判定

新版教师行为接口适配通过自动化、真实 ImageDetect smoke、中文预览视觉检查和安全扫描，可以用于后续标签制作。实际生成的数据仍应根据 `needs_review` 进入人工审核流程。
