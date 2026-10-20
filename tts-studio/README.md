# 声场 · TTS Studio

本机运行的豆包、MiniMax、阿里 Qwen 语音合成试听工作台。使用 Python 3.12 标准库后端和原生 HTML/CSS/JavaScript，无需安装 npm 包或第三方 Python 依赖。

音色快照与请求参数依据官方文档整理，核对日期为 **2026-10-19**。公开目录不等同于账号当前授权清单；云端可用性仍由地域、账号权限和厂商响应决定。开发验证使用模拟云端返回，尚未使用真实凭据进行三家付费合成。

## 启动

在仓库根目录执行：

```powershell
python tts-studio/server.py
```

打开 <http://127.0.0.1:8765>。更换端口：

```powershell
python tts-studio/server.py --port 9000
```

也可执行 `./tts-studio/start.ps1 -Port 8765`。若 PowerShell 限制脚本执行，直接使用 Python 命令。

## 连接厂商

在页面右上角「连接设置」填写后点击「保存到本机」，API Key、业务空间 ID、App ID、资源 ID 和地域会写入 `tts-studio/settings.local.json`，服务重启后自动加载。输入框留空再保存会保留已有值；「清除凭据」会清除该厂商的内存及本地保存值，重启后仍保持清除状态。

也可复制 [.env.example](.env.example) 为同目录 `.env` 后填写。已通过页面保存的厂商配置优先于环境变量和 `.env`；尚未保存的厂商使用环境变量，其次使用 `.env`。如需重新使用环境变量配置，停止服务并删除 `settings.local.json` 后启动。

| 厂商 / API | 必填 | 其他配置 |
| --- | --- | --- |
| 豆包新版鉴权 | `DOUBAO_API_KEY` | App ID 留空；`DOUBAO_RESOURCE_ID=auto` 随所选资源，也可指定已开通资源 |
| 豆包旧版鉴权 | `DOUBAO_APP_ID` + `DOUBAO_API_KEY`（填 Access Key） | 兼容旧环境变量 `DOUBAO_ACCESS_TOKEN`，新变量优先 |
| MiniMax | `MINIMAX_API_KEY` | `MINIMAX_REGION=cn` / `intl` |
| Qwen-Audio 3.1 / 3.0 | `DASHSCOPE_API_KEY` + `QWEN_WORKSPACE_ID` | `QWEN_REGION=cn`（北京）/ `intl`（新加坡），业务空间和 Key 必须同地域 |
| Qwen3 Flash | `DASHSCOPE_API_KEY` | 北京 / 新加坡；无需业务空间 ID |

页面不回显已保存的凭据，不把密钥写入浏览器存储。本地配置文件包含明文凭据，请勿分享；`settings.local.json`、写入时的临时文件及 `.env` 均已被 Git 忽略，不能通过 Web 静态接口下载。保存采用临时文件加原子替换，写入失败会明确提示，保留之前的配置。「已配置」表示字段已填写，鉴权结果由实际请求确定。

服务只监听 `127.0.0.1`，面向单人本机使用。

## 工作台布局

桌面端采用左侧导航、中间文本编辑器、右侧调试台和底部常驻播放器。顶部切换厂商与模型，点击右侧音色卡片打开官方音色库，支持名称、ID、语言和风格搜索；选择音色后自动返回调试台。常用语速、音量、音调与表达指令直接展示，编码、混音和其他能力按组展开。

编辑器底部可生成或加入对比；也可在文本编辑器中按 Ctrl / Cmd + Enter 生成。MiniMax 提供光标处插入 0.5 秒停顿的快捷按钮。「参数重置」恢复当前模型的默认参数，不改动已加入对比的快照。

左侧「声音对比」统一使用编辑器中的当前文本，完成后打开「生成历史」展示结果和部分失败信息。历史记录的「试听」会切换底部播放器，可播放、暂停、拖动进度、前后切换记录及下载音频；切换导航不会中断播放。手机端自动改为上下排列，底部播放器保持可用。

## 音色与能力

音色列表可搜索名称、ID、语言、风格与类别，按模型和文档明确标出的地域筛选。较大列表每批显示 100 条。「指定模型或音色 ID」可用于自己的克隆音色和新开通模型。

| 厂商 | 目录与模型 | 表单能力 |
| --- | --- | --- |
| 豆包 | **553 个 TTS 音色 ID**：2.0 为 450，1.0 为 103；Seed TTS 2.0、1.0 字符计费、1.0 并发计费 | 语速、音量、音高、逐音色情绪与强度、2.0 表达指令、语言 / 方言、时间戳 / 字幕、读音字典、文本处理、全文末尾静音、1.0 混音 / 静音裁剪、缓存、编码、AIGC 水印 / 元数据 |
| MiniMax | **388 个公开文档 ID**，合并中国站与国际站；Speech 2.8 / 2.6 / 02 / 01 各 HD 和 Turbo | 语速、音量、音调、模型情绪、语言增强、读音字典、文本规范化、LaTeX、音色变换 / 音效、最多四音色混合、字幕、声道 / 编码、流式响应、AIGC 标识 |
| Qwen-Audio | 3.1 Flash 68；3.0 Plus 2 + 597 基础音色；3.0 Flash 12 + 597 基础音色 | 原生语速、音量、音调、表达指令与标签、语言提示、SSML、读音 / 文本替换、随机种子、字词时间戳、编码、AIGC 标识 |
| Qwen3 Flash | **48 个官方音色** | 音色、文本语言，24 kHz WAV，单次最多 600 字符 |

豆包快照保留全部 578 个官方 ID，其中 25 个只列于 S2S / SC 章节，TTS 兼容性未明确，因此不会出现在 TTS 模型的可选列表。15 个 1.0 音色有官方枚举情绪；混音只列出官方明确标注支持的 1.0 音色。声音复刻专属的 `tone_fidelity` / `use_tag_parser` 不作为系统音色能力展示。`disable_emoji_filter` 在当前和历史文档中语义冲突，界面保留原始参数名和差异提示。括号过滤采用官方建议的 0–100 字范围，不支持字符比例采用本地 0–1 范围；这些是工作台约束，不代表官方未公布的硬性上下限。

Qwen 共 **1,324 个唯一 ID**。两份基础音色表各含 597 条，保留原表来源与行号。基础表未逐条保证指令 / SSML / 时间戳能力，界面会说明；主音色表有明确不支持标记的项目会隐藏相应控制。MiniMax 公开表没有逐音色的模型 / 情绪矩阵，因此情绪按模型提供；可用自己的 Key 点击「刷新系统音色」，获取账号接口实际返回的系统音色。

情绪控制依厂商实现：MiniMax 使用原生枚举；豆包 1.0 按音色官方支持列表；豆包 2.0 与 Qwen-Audio 可用自然语言表达指令。开心、伤心、愤怒与快慢语速提供一键指令预设。Qwen3 Flash 没有这些数值或指令字段，切换到该模型时不会发送伪造控制参数。

常见组合限制会在本地先检查，例如 MiniMax 音量须大于 0、2.6 才列出 fluent / whisper、音色变换的格式限制、Qwen Opus 采样率限制、豆包 Ogg Opus 48 kHz 限制。表单默认值是工作台的试听配置，预览可查看实际发送值。

## 对比、音频与结果

- 保存最多 6 组配置，以当前文本统一生成；一次最多并发 3 个任务。一组失败仍保留其余成功结果。
- 播放、下载原始音频，查看本次参数、实际请求体、厂商用量与字幕 / 时间戳。MiniMax 非流式字幕保留官方 JSON 链接。
- 原始 16 位小端 PCM 和 MiniMax μ-law 转为标准 WAV 供播放；下载保留原始编码。支持 MiniMax 单 / 双声道 PCM。豆包流式 WAV 若返回多个完整 RIFF 段，会合并为单个 WAV；无法校验的流式 WAV 会提示切换 PCM / MP3。
- Qwen 返回的官方域名 HTTP 音频链接会升级为 HTTPS 下载，保留路径和签名参数；下载和重定向均检查域名白名单。
- 豆包与可选的 MiniMax / Qwen 流式响应在服务端收齐后播放，检查终止帧并避免重复拼接末尾聚合音频。当前显示总耗时，未测量首包延迟。
- 音频只缓存在服务进程内，最多 30 条、合计约 96 MiB，超限后释放较早记录。刷新页面会清空页面上的配置 / 结果，重启服务清空全部音频。
- 支持手机布局、深浅主题、示例文本；底部统一播放器在切换导航时保留播放状态，同一时刻试听一条音频。

生成会调用自己的厂商账号并可能产生费用。「预览实际请求」只构造请求体，不调用云服务。高级 JSON 会与请求体递归合并，模型、音色、文本由表单决定。高级参数中的格式、采样率和主要能力组合也会再次校验。

## 官方来源与数据维护

- 豆包：[当前 HTTP 接口](https://docs.volcengine.com/docs/6561/2528925)、[音色列表](https://docs.volcengine.com/docs/6561/1257544)。
- MiniMax：[HTTP 接口](https://platform.minimax.cn/docs/api-reference/speech-t2a-http)、[中国站音色](https://platform.minimax.cn/docs/faq/system-voice-id)、[国际站音色](https://platform.minimax.io/docs/faq/system-voice-id)、[获取音色接口](https://platform.minimax.cn/docs/api-reference/voice-management-get)。[本地完整 Schema 与出处](data/minimax-schema.json) 保留模型、约束和官方文档差异。
- Qwen：[Qwen-Audio 接口](https://help.aliyun.com/zh/model-studio/qwen-audio-tts-http-api)、[Qwen-Audio 音色](https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list)、[Qwen3 接口](https://help.aliyun.com/zh/model-studio/qwen-tts-api)、[Qwen3 音色](https://help.aliyun.com/zh/model-studio/qwen-tts-voice-list)、[SSML](https://help.aliyun.com/zh/model-studio/ssml-latex-user-guide)。[本地提取依据与计数](data/qwen-references.json)。

[catalog.py](catalog.py) 管理模型能力，[data/](data/) 保存官方音色快照。每条音色有来源；官方未声明的字段保留为空或 unknown，不补造性别、模型或情绪兼容性。目录不会联网自动更新；MiniMax 刷新仅更新当前服务进程。

## 本地验证

```powershell
python -m unittest discover -s tts-studio/tests -v
node --check tts-studio/web/app.js
```

测试涵盖参数映射、模型 / 音色 / 地域兼容性、请求限制、SSE / NDJSON 终止和字幕合并、PCM / μ-law 转换、原始下载、凭据不回显、并发、缓存与真实本地 HTTP 往返。厂商响应全部模拟，测试不会发起付费合成。

真实浏览器测试需要 Node.js 22 与 Microsoft Edge。先启动服务，再执行：

```powershell
node tts-studio/tests/browser-smoke.mjs http://127.0.0.1:8765
```

可用 `EDGE_PATH` 覆盖 Edge 安装路径。测试使用独立浏览器配置，拦截合成和设置写入，返回模拟静音 WAV；请求预览经过真实本地后端。验证目录筛选、参数、标签、对比、部分失败、播放、密钥输入清空、主题和 400px 布局。截图写入 Git 忽略的 `.playwright/desktop.png`、`.playwright/mobile.png`。

真实云端仍需使用本机配置的账号验证：鉴权 / 配额、具体音色与情绪实际效果、不同编码返回和下载。离线测试不代表声音质量或每个账号权限已验证。

后续可选：盲听打分、持久保存评测方案、导出音频与参数包、首包延迟与流式边到边播。
