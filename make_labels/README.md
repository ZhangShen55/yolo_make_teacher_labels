# make_labels

本子项目用于从视频平台批量采集教师端视频截图，并结合 8881 教师行为接口与 VLM 生成 YOLO 数据集。服务包名为 `app`，可从本目录独立运行。

## 接口迁移记录

新版教师行为接口的类别变化、中文叠框规则、VLM 复核职责和后续测试清单见 [新版教师行为接口迁移契约](docs/teacher-behavior-api-v6-migration.md)。该方案当前仅完成评审和记录，代码仍使用旧版接口映射，尚未切换目标实例。

## 环境

```bash
conda create -y -n make_label python=3.12
conda activate make_label
cd make_labels
python -m pip install -r requirements.txt
```

本机还需要可执行的 `ffmpeg` 和 `ffprobe`，用于远程视频抽帧与读取视频时长。

## 配置

`config.toml` 保存平台、抽帧、8881、输出目录和 VLM 配置。平台 token 不再需要手工填写到 `.env`，服务会在运行期通过 `[platform.auth]` 自动获取并刷新。

关键敏感配置：

```toml
[platform]
base_url = "https://example.edu.cn"

[platform.auth]
token_path = "/access_token"
grant_type = "password"
client_secret = "replace-with-platform-client-secret"
client_id = "replace-with-platform-client-id"
username = "replace-with-platform-username"
password = "replace-with-platform-password"
refresh_interval_seconds = 43200

[vlm]
api_key = "replace-with-vlm-api-key"
```

`grant_type`、`client_secret`、`client_id` 是平台 token 接口参数；`username` 和 `password` 根据不同平台账号填写。`refresh_interval_seconds` 默认 12 小时，平台 API 返回 `401` 或 `403` 时也会强制刷新 token 并重试一次。

注意：写入真实账号密码和 Ark API key 后，`config.toml` 属于敏感文件，不要提交到公开仓库。

## 启动

```bash
conda activate make_label
cd make_labels
python -m app.main --config config.toml --host 127.0.0.1 --port 8010

nohup python -u -m app.main --config config.toml --host 127.0.0.1 --port 8010 \
  </dev/null > make_label-service.log 2>&1 &

echo $! > make_label-service.pid
```

接口：

```text
GET  /api/health
GET  /api/config
GET  /api/jobs/status
POST /api/jobs/start
POST /api/jobs/stop
GET  /api/batches
```

从默认 `config.toml` 的 `start_page` 开始：

```bash
curl -X POST http://127.0.0.1:8010/api/jobs/start
```

从指定页开始，只处理 1 页：

```bash
curl -X POST http://127.0.0.1:8010/api/jobs/start \
  -H 'Content-Type: application/json' \
  -d '{"start_page": 150, "max_pages": 1}'
```

其中 `start_page` 表示课程列表页码，`max_pages` 表示本次最多处理多少页。

查看状态

```bash
curl http://127.0.0.1:8010/api/jobs/status
```

运行自检：

```bash
curl -X POST http://127.0.0.1:8010/api/preflight/run
```

如果需要验证平台是否接受“只携带 `jwt-token`、不携带 `Cookie`”的请求，可先运行自检中的 `platform_auth`，或使用同一配置账号请求组织树接口：

```bash
curl -X POST http://127.0.0.1:8010/api/preflight/run
curl http://127.0.0.1:8010/api/preflight
```

`platform_auth` 通过表示当前配置能够完成 token 获取并访问平台组织树。



## 输出

脱敏样例配置默认输出到 `../output`：

```text
output/
  batch_000001/
    images/
    labels/
    annotations.jsonl
    classes.txt
    raw/
    preview/
    failed/
```

`images/` 和 `labels/` 可直接用当前标注审核工具打开。

## 离线图片脚本

离线图片标注脚本位于 `scripts/teacher_vlm_labeler.py`。它使用 requirements 中声明的 `requests` 调用原有 8881 和 Ark HTTP 接口：

```bash
conda activate make_label
cd make_labels
export ARK_API_KEY="your-api-key"
python -m scripts.teacher_vlm_labeler --src-dir /path/to/images
```

查看完整参数：

```bash
python -m scripts.teacher_vlm_labeler --help
```

## 测试

从本子项目目录运行：

```bash
conda run -n make_label python -m pytest tests -q
python -m app.main --help
```

## 第一版限制

- 不做验证码自动识别。
- 不从 `1请求header.txt` 或 `2根据课程id拿到视频链接header.txt` 读取配置。
- 平台 token 会自动获取和刷新；如果账号密码失效或平台接口变更，任务会在状态接口的 `recent_errors` 中暴露错误。
