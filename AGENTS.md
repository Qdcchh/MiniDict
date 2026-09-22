# MiniDict

macOS 离线弹窗词典：Python 3.14 + tkinter + PyObjC（`.venv`，依赖见 requirements.txt，仅 darwin）。
全局热键 ⌥D（被占用时回退 ⌃⌥D）呼出窗口并自动查剪贴板；支持英→中精确查询与中→英反查（候选列表）。
数据源是 ECDICT SQLite：`data/stardict.db`（812MB、340 万词条，已 gitignore；缺失时从
skywind3000/ECDICT 的 release 下载后放入 `data/`）。

## 常用命令

- 运行 GUI：`.venv/bin/python gui.py`
- 运行 CLI：`.venv/bin/python main.py`（刻意只做英→中，无反查，不是缺陷）
- 构建 macOS 应用：`./scripts/build_app.sh` → `dist/MiniDict.app`
- 无正式测试/lint 配置；验证方式见下方「测试模式」

## 结构与分层

- `dictionary.py` — 全部 SQL 在这一层。`lookup()` 英→中（走 word 索引）；
  `lookup_by_chinese()` 中→英（translation 列无索引，LIKE 全表扫，热态 ~0.3s、冷启动 ~2.3s）。
  连接一律只读（`?mode=ro`），每次查询重建连接。
- `gui.py` — 界面与生命周期：CJK 路由、候选列表点击/返回导航、常驻降级矩阵、热键与菜单栏装配。
- `macos_hotkey.py` — macOS 平台层：Carbon 热键（ctypes 声明，因 PyObjC 不暴露 InstallEventHandler）、
  AppKit 激活/激活策略、菜单栏图标 NSStatusItem（「译」）、剪贴板读取。
  **AppKit/PyObjC 导入必须保持在函数内延迟导入**——非 macOS 上 gui.py 也会无条件 import 本模块。
- `associator.py` — 小模型插槽：`Associator` 协议 + `NullAssociator`。
  做"中文查英文联想词"先读它的模块 docstring；接入点是 `MiniDictApp(associator=...)`，
  调用侧（查词条/去重/容错）已在 gui 里就位。
- `scripts/` — `build_app.sh`（打包）与 `make_icon.py`（AppKit 画图标 + sips/iconutil 制 icns）。

## 硬性规则

1. **原生回调绝不直接调用 Tk**（Carbon 事件处理器、NSMenu 动作都在内）：只写管道字节
   （`b"s"`=呼出、`b"x"`=退出），由 `createfilehandler` 唤醒 Tcl 循环。原因见 macos_hotkey.py 模块 docstring。
2. **应用永不可达不变式**：accessory 策略去掉 Dock 图标后必须有呼出渠道。降级矩阵在
   `gui.start_hotkey()`：热键挂 → 菜单栏图标顶着；两者全挂 → 恢复 Dock 策略。改 hide()/start_hotkey() 时别破坏它。
3. 热键操作只能在跑 Tk 事件循环的主线程；注册是独占的（`kEventHotKeyExclusive`）。

## 已知坑

- **FTS5 trigram 对两字中文查询失效**（3 字符下限），中→英加速别走这条路；正统方案是预建"释义分段表"。
- ECDICT 的 `frq`/`bnc` 是排名：越小越常用，0/NULL 是未收录，排序时未收录要垫底。
- 本机 PyObjC 的坑：NSRect/NSPoint 必须经 `NSMakeRect`/`NSMakePoint`（裸元组 depythonify 报错）；
  `NSBitmapImageRep.imageRepFromData_` 不存在——位图导出走 TIFF + `sips`。
- **已在运行的 MiniDict 实例会持有 ⌥D**：再起进程（含测试）会回退 ⌃⌥D。测试不要硬断言热键注册成功，断言菜单栏图标即可。
- `dist/MiniDict.app` 是包装型 bundle：构建时烧录本机 venv 与项目绝对路径，项目挪位置后重跑
  build_app.sh；运行日志在 /tmp/minidict.log。
- 用户可见文案用中文；docstring/注释用英文且只写约束本身，不写"做了什么"。

## 测试模式（无框架，历史验证方式）

- 数据层：直接在 `.venv/bin/python` 里 import + 断言（lookup、反查排序、边界输入）。
- GUI：不可见窗口集成测试——`root.withdraw()` 后 monkeypatch `root.deiconify/lift`、
  `search_entry.focus_force`、`gui.activate_application`、`gui.read_pasteboard_word`，
  直接调 `search()/show()/open_candidate()`，断言 `results` 文本与 tag_ranges。
  `start_hotkey()` 可真实注册（热键/菜单栏图标是真的，进程退出自动释放）。
- 反查排序质量验证基准："苹果"→apple 第一、"打"→hit/beat/strike/dozen、"查找"→find/seek/lookup。
