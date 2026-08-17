# Windows 抽帧可靠性修复设计

## 问题边界

Windows 运行记录显示，`extract_frame()` 返回后 producer 将 `frame_1482.jpg` 放入队列，但 detector 读取时文件不存在。使用同一真实视频 URL 手工验证时，`ffprobe` 得到约 3000 秒时长，ffmpeg 在 1482 秒能够生成有效 JPEG。因此不能追溯断言历史故障一定是空输出还是并发覆盖，但可以确认现有代码有两个缺口：只检查 ffmpeg 退出码，不验证图片产物；不同任务使用相同的 `tmp_frames/<course_id>/` 路径。

## 修复设计

`extract_frame()` 的成功契约改为“ffmpeg 返回成功，并且输出文件存在、非空、可由 Pillow 完整解码像素”。不能只调用 `Image.verify()`，因为末尾截断的 JPEG 可能通过结构验证但在读取像素时失败。每次尝试前删除同名旧文件，避免把残留文件误判为本次成功。命令失败或产物无效都纳入同一重试预算，总尝试次数保持三次；全部失败后抛出 `VideoCommandError`，错误信息明确指出产物缺失或无效。

每个 `LabelPipeline` 实例生成唯一 `run_id`，所有 probe、正式帧和 VLM 预览均写入 `tmp_frames/<run_id>/<course_id>/`。这样同一台机器上的多个服务进程或重叠任务不会争用相同文件。

producer 只将经过验证的文件放入队列。`label_frame()` 在 detector 调用前再检查一次文件，若文件在队列传递后被外部删除，则记录单图错误并过滤该图，不再中断整门课程。

## 测试与兼容性

测试覆盖 ffmpeg 返回 0 但无文件、前两次无产物第三次成功、无效图片、可通过 `verify()` 但不能完整解码的截断 JPEG、任务路径隔离，以及 detector 前文件消失。公开函数和配置字段保持不变；Windows、macOS 和 Linux 均使用 `pathlib`、Pillow 与现有 subprocess 实现。

## 非目标

本次不修改视频 URL 获取、抽帧时间计算、ImageDetect、VLM 或数据集标签规则，也不尝试仅通过增加超时掩盖无产物问题。
