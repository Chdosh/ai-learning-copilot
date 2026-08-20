# Portable 自动更新发布约定

当前项目继续使用 Windows x64 Portable ZIP。更新器不会覆盖程序目录下的 `data/`，因此每个发布 ZIP 必须只包含程序文件，不要把本机运行后生成的 `data/` 打进去。

## 发布包内容

ZIP 根目录必须至少包含：

```text
AI-Learning-Copilot.exe
AI-Learning-Copilot-Updater.exe
LICENSE.txt
使用说明.txt
```

主程序会从 GitHub Releases 的最新稳定版本中寻找：

```text
AI-Learning-Copilot-{version}-win-x64.zip
SHA256SUMS.txt
```

预发布版本不会被自动更新选择。发布版本必须上传 `SHA256SUMS.txt`，否则客户端会停止更新并提示发布包不完整。

## 构建与检查

使用仓库现有的 PyInstaller spec：

```powershell
.\.venv-build\Scripts\pyinstaller.exe --noconfirm --clean ai_learning_copilot.spec
```

构建完成后，`dist/` 中应同时出现：

```text
AI-Learning-Copilot.exe
AI-Learning-Copilot-Updater.exe
```

把这两个 EXE、许可证和使用说明复制到一个干净的临时目录，再压缩该目录。不要从当前已经运行过的 `dist/` 目录直接打包，否则可能把本机的 `data/` 一起发布。

发布前至少检查：

- ZIP 可以在没有 Python 的干净 Windows 机器上启动；
- ZIP 中同时存在主程序和独立更新器；
- `SHA256SUMS.txt` 中的哈希对应 ZIP 文件；
- 新版本可以覆盖旧版本的 EXE，但旧版本的 `data/`、数据库和凭据仍然存在；
- 更新失败时，程序目录不会留下半个主程序。

## 首次升级说明

`0.6.0` 及更早的已发布 Portable 包本身没有更新检查器，因此不能自动发现第一个“支持自动更新”的版本。用户需要手动下载并安装一次该版本；从这个版本开始，后续版本即可通过内置更新完成升级。

## 运行时行为

- 程序启动后延迟检查一次最新稳定版；网络失败不会阻止启动。
- “设置 → 关于 → 检查更新”可以手动触发检查。
- 下载先保存到系统临时目录，完成后校验 SHA-256 和 ZIP 内容。
- 主程序退出后，独立更新器替换程序文件并保留 `data/`。
- 更新日志写入 `data/update.log`。
- 开发模式只允许测试检查和下载，不会替换源码目录。
