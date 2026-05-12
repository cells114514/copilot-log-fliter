# Copilot Cli Log Fliter
用于分析Copilot Cli的日志文件，筛选出其中有用的json行，后续得到对应json进行的操作请自行定义，本程序提供了在终端输出的默认响应以及在桌面显示对应当前状态的gif图
目前仅适配linux系统，后续会跟进适配Windows系统的更改
# 快速开始
安装依赖：
```
pip install PyQt5
```

在终端运行Copilot Cli：
```
Copilot --log-level all
```

运行本脚本：
```
python copilot_json_watcher.py
```