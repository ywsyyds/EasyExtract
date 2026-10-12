# 易解压 EasyExtract

一款简洁的 Windows 压缩 / 解压工具，基于 PySide6 (Qt) 与 7-Zip 引擎。

![图标](app/resources/icon.png)

## 功能

**解压**
- 支持 40+ 格式：zip、rar（含 RAR5）、7z、tar、tar.gz、tar.bz2、tar.xz、zst、gzip、bzip2、xz、cab、iso、wim、msi、dmg、vhd 等
- 拖拽或按钮批量添加，队列依次解压
- 默认解压到同名文件夹，可自定义目标目录
- 实时进度条 + 当前文件名，可随时取消
- 加密压缩包自动弹出密码框，同一会话内密码缓存免重复输入
- 双击任务预览压缩包内容清单（文件名 / 大小 / 修改时间）
- tar.gz / tar.xz 等复合包自动"智能解包"，一步解出最终文件

**压缩**
- 支持 7z、zip、tar、tar.gz、tar.bz2、tar.xz
- 保留目录结构；压缩等级可选（存储 / 最快 / 标准 / 最大）
- 密码加密：7z 使用 AES-256（可选加密文件名），zip 使用 AES-256
- 7z / zip 支持分卷（10 MB ~ 1 GB）
- 同样的进度显示与取消支持

## 开发运行

依赖：Windows 10+，Python 3.12+

```bat
py -m pip install -r requirements.txt
py run.py
```

## 测试

```bat
py scripts\make_samples.py   :: 生成测试压缩包样本
py scripts\test_engine.py    :: 引擎自动化测试（解压/压缩/密码/分卷/取消）
py scripts\gui_smoke.py      :: GUI 冒烟测试（截图 + 端到端操作）
```

## 构建

```bat
scripts\build.bat
```

产物：
- `build\dist\EasyExtract\` —— 绿色版（免安装目录，EasyExtract.exe）
- `dist\installer\EasyExtract_Setup_1.0.0.exe` —— 安装包（Inno Setup，支持选择目录、开始菜单/桌面快捷方式、卸载）

## 项目结构

```
app/
  main.py             应用入口模块
  version.py          版本常量
  core/engine.py      7z.exe 引擎封装（QProcess 异步：解压/压缩/列表/进度/密码）
  core/formats.py     格式识别与命名规则
  ui/                 PySide6 界面（主窗口 / 解压页 / 压缩页 / 密码框 / 内容浏览）
  bin/                捆绑的 7-Zip 引擎（7z.exe / 7z.dll）
  resources/          图标
installer/setup.iss   Inno Setup 安装包脚本
scripts/              构建 / 测试 / 图标 / 样本脚本
```

## 许可说明

- 本项目代码：MIT
- 捆绑的 7-Zip（7z.exe / 7z.dll）：LGPL-2.1 + unRAR 许可（见 `app/bin/License.txt`），RAR 解码部分遵循 unRAR 许可，仅限解压、不可用于重新创建 RAR 压缩格式
