# vision-test source bundle

This repository contains the local MiniCPM-o 4.5 video monitor source as a self-expanding source bundle.

The source is packaged this way because the current Windows machine does not have non-interactive GitHub HTTPS credentials available for `git push`. The bundle was written through the GitHub connector so another machine can clone it and expand it reliably.

## Use on another Windows machine

```powershell
git clone https://github.com/sga-jerrylin/vision-test.git D:\vision-test
cd D:\vision-test
.\Expand-Bundle.ps1
```

After expansion, the full source tree will be present in the same directory, including:

- `local_video_monitor/`
- `Start-LocalVideoMonitor.ps1`
- `Stop-LocalVideoMonitor.ps1`
- `scripts/`
- `patches/`
- `README.md`

Then follow the expanded project `README.md`. The normal setup is:

```powershell
.\scripts\Apply-Patches.ps1
.\scripts\Build-LlamaServer.ps1
.\Start-LocalVideoMonitor.ps1 -WechatWebhookUrl "<your enterprise wechat robot webhook>"
```

Model weights are intentionally not committed. Put the GGUF model at:

```text
models\MiniCPM-o-4_5-gguf\MiniCPM-o-4_5-Q4_K_M.gguf
```
