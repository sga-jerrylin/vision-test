# MiniCPM-o 4.5 Local Video Monitor

本仓库是本机部署版：不启动 ASR，不启动 TTS，把资源集中给视频帧理解和主模型。浏览器负责摄像头采集，页面里输入监控规则；命中事件时，服务端按事件日志逐条发送企业微信机器人 webhook。

## 包含什么

- `local_video_monitor/`：本地浏览器摄像头监控 UI 和 FastAPI 服务。
- `Start-LocalVideoMonitor.ps1`：启动 MiniCPM-o C++ 推理包装服务和监控 UI。
- `Stop-LocalVideoMonitor.ps1`：停止监控服务和推理服务。
- `patches/`：对上游 `llama.cpp-omni` 和 `MiniCPM-V-CookBook` 的补丁，让视频帧请求可以携带文本规则 prompt，并彻底走 video-only 路径。
- `scripts/Apply-Patches.ps1`：拉取上游源码并应用补丁。
- `scripts/Build-LlamaServer.ps1`：编译 CUDA 版 `llama-server.exe`。

## 不包含什么

- 不提交模型权重。请把 MiniCPM-o 4.5 GGUF 文件放到 `models\MiniCPM-o-4_5-gguf\`。
- 不提交企业微信 webhook。启动时通过 `-WechatWebhookUrl` 传入。
- 不提交 CUDA 安装包、构建产物、日志、缓存。

## 目标目录结构

```text
vision-test/
  local_video_monitor/
  models/
    MiniCPM-o-4_5-gguf/
      MiniCPM-o-4_5-Q4_K_M.gguf
  repos/
    llama.cpp-omni/
    MiniCPM-V-CookBook/
```

## 新机器部署

在 PowerShell 里执行：

```powershell
git clone https://github.com/sga-jerrylin/vision-test.git D:\vision-test
cd D:\vision-test
.\scripts\Apply-Patches.ps1
```

把模型文件放到：

```text
D:\vision-test\models\MiniCPM-o-4_5-gguf\MiniCPM-o-4_5-Q4_K_M.gguf
```

然后编译 C++ 推理服务：

```powershell
.\scripts\Build-LlamaServer.ps1
```

如果机器上有多个 Visual Studio/CUDA 版本，可以显式指定：

```powershell
.\scripts\Build-LlamaServer.ps1 -Generator "Visual Studio 18 2026" -CudaToolkitRoot "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2"
```

启动：

```powershell
.\Start-LocalVideoMonitor.ps1 -WechatWebhookUrl "<your enterprise wechat robot webhook>"
```

打开：

```text
http://localhost:8099
```

页面里输入规则，例如：

```text
有人出现就通知我，然后告诉我是男是女，还有穿什么衣服、明显特征和移动方向。
```

点击“发送要求/开始监控”后，浏览器会上传摄像头帧；模型输出非 `NO_EVENT` 的事件日志时，服务端会立刻发企业微信 webhook。当前策略是“日志有多少，webhook 就发多少”，没有冷却和去重。

## 检查环境

```powershell
.\scripts\Check-Ready.ps1
```

至少需要：

- Windows + NVIDIA GPU。
- Python 3.11/3.12/3.13，且 `python` 在 PATH 中。
- Git。
- CMake。
- Visual Studio Build Tools，包含 C++ 桌面开发和 CMake 工具。
- CUDA Toolkit，建议 12.8 或 13.2。

## 常用参数

```powershell
.\Start-LocalVideoMonitor.ps1 `
  -MonitorPort 8099 `
  -InferencePort 9060 `
  -VideoOnlyNPredict 96 `
  -VideoOnlyMaxTargetLength 256 `
  -LlamaBatchSize 2048 `
  -LlamaUBatchSize 512 `
  -WechatWebhookUrl "<your enterprise wechat robot webhook>"
```

如果 Python 不在 PATH：

```powershell
.\Start-LocalVideoMonitor.ps1 -PythonBin "C:\Path\To\python.exe" -WechatWebhookUrl "<your enterprise wechat robot webhook>"
```

## 设计取舍

- 旧 LiveKit/语音页面不是主路径。本仓库默认使用 `http://localhost:8099` 的轻量监控页。
- ASR/TTS 环境变量被设为关闭，避免浪费显存和调度时间。
- 只把补丁提交到仓库，不 vendoring 两个完整上游源码仓库，这样仓库小、可维护，也不会把构建产物误传。
- 企业微信 webhook 是敏感信息，不写入仓库。
