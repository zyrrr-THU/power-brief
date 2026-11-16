# PowerBrief 电力日报 · 使用手册

每天早上自动收集电力行业新闻（政策、市场电价、大小企业、新能源储能、电网技术、国际），挑出约 20 条，配上通俗摘要、行业解读、术语解释，并附上：

- **政策雷达**：直接跟踪国家能源局、国家发改委的通知/公告/解读，以及广东、山东等省的政策和征求意见稿（含截止日）；
- **行业数据**：全国碳价、国际油气价格、全社会用电量等指标的趋势图，以及新闻里的关键数字；
- **能源股与公司公告**：15 只能源股行情，关注公司和全市场能源类上市公司的重要公告（含中小企业）；
- **专题追踪**：同一议题（如容量电价、机制电价竞价）跨天串成时间线，每周日附专题深度解读。

**v2.0 起在云端运行**：GitHub 每天北京时间 07:30（瑞士冬令时 00:30、夏令时 01:30）自动生成简报并发布成网页。你在任何设备（Windows、Mac、手机）打开一个网址就能看，看完关掉即可；电脑上不需要安装或运行任何东西。

> 示例：小李在瑞士读书，关注国内电力行业。早上喝咖啡时在手机上打开收藏的网址，先看“今日三件事”，再挑几条读摘要；碰到“机制电价”不懂，点一下术语就有大白话解释；有用的点“收藏”，周末在电脑上导出成笔记。

---

## 0. 第一次设置（约 20 分钟，只做一次）

需要准备：一个 GitHub 账号（免费）；可选一个 DeepSeek 账号（AI 摘要用，约 ¥0.6/月，不配则为“规则模式”：自动分类 + 术语词典，没有 AI 摘要）。

### 第 1 步：建仓库（GitHub 网页上操作）
1. 登录 github.com，右上角“＋”→ **New repository**。
2. Repository name 填 `power-brief`；选 **Public**（免费的网页发布要求公开仓库，见第 9 节“隐私”）；其他选项都不要勾（不要加 README、.gitignore、License），点 **Create repository**。

### 第 2 步：上传程序（本机终端）
在 `power-brief` 文件夹空白处按住 Shift 右键 →“在终端中打开”，逐行运行（把 `你的用户名` 换成 GitHub 用户名）：

```bash
git init -b main
```
```bash
git add .
```
```bash
git commit -m "PowerBrief 2.0"
```
```bash
git remote add origin https://github.com/你的用户名/power-brief.git
```
```bash
git push -u origin main
```

- 第一次 push 会弹出浏览器让你登录 GitHub，按提示授权即可。
- 如果 `git commit` 提示 “Please tell me who you are”，先运行 `git config --global user.name "你的名字"` 和 `git config --global user.email "你的邮箱"`。
- `.env`（本机密钥）、`logs/`、`_历史版本/`、`_更新包/` 已在 `.gitignore` 里排除，不会上传。上传前可以用 `git status` 看一眼文件列表。

### 第 3 步：打开网页发布
仓库页面 **Settings → Pages**：Source 选 **Deploy from a branch**，Branch 选 `main`，文件夹选 `/docs`，点 Save。约 1–2 分钟后页面顶部出现网址：

`https://你的用户名.github.io/power-brief/`

这就是以后每天看简报的网址。在手机浏览器打开后可“添加到主屏幕”，像 App 一样打开；电脑上收藏成书签。

### 第 4 步：填密钥（GitHub 网页上操作）
仓库 **Settings → Secrets and variables → Actions → New repository secret**，按需添加（名称必须一字不差）：

| 名称 | 作用 | 在哪里拿 |
|---|---|---|
| `DEEPSEEK_API_KEY` | AI 摘要（推荐） | platform.deepseek.com 注册 → 充值 10 元 → API keys → 创建 |
| `PUSHPLUS_TOKEN` | 推送到微信（可选，不想推送可不填） | pushplus.plus 微信扫码登录 → 一对一推送 → 复制 token |
| `ANTHROPIC_API_KEY` | 用 Claude API 代替 DeepSeek（可选） | console.anthropic.com → API Keys（按量付费，与 Claude Pro 订阅是两套账户） |

其他推送渠道见第 6 节。密钥只存在 GitHub，网页和仓库文件里都看不到。

### 第 5 步：试跑一次
仓库 **Actions** 页面 → 左侧 **daily-brief** → 右侧 **Run workflow** → 绿色 **Run workflow**。约 3–5 分钟后变成绿色 ✓，再等 1–2 分钟网页就会更新。打开网址，“运行”页能看到这次运行记录，“用量”页能看到真实 token 数（配了 DeepSeek 时）。

如果是红色 ✗：点进去看 “Generate brief” 步骤的报错；常见原因见第 10 节。

### 第 6 步：让网页能改设置、能“立即更新”（每台设备一次）
1. 打开 github.com/settings/personal-access-tokens/new （GitHub 头像 → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token）。
2. Token name 随便填（如 `power-brief 网页`）；Expiration 选 1 年；**Repository access** 选 **Only select repositories** → 选 `power-brief`。
3. **Permissions → Repository permissions**：**Contents** 选 *Read and write*，**Actions** 选 *Read and write*（Metadata 会自动变为只读）。点 Generate token，复制以 `github_pat_` 开头的令牌。
4. 打开简报网址 →“设置”页 →“连接 GitHub”：仓库一般已自动填好（`你的用户名/power-brief`），粘贴令牌，点“连接”。

令牌只保存在这台设备的浏览器里，只能操作这一个仓库。电脑、Mac、手机各连接一次（可以用同一个令牌）。不连接也能正常阅读，只是不能改设置。令牌过期或换设备后重新粘贴即可；不用了在 GitHub 令牌页面删除它。

完成以上 6 步后，本机就不再需要做任何事了。

---

## 1. 日常使用

打开网址，顶部各页：

- **今日**：当天简报。今日三件事 → 各分类新闻（摘要、👉 行业解读、📖 术语）；侧栏有关键数据小图、能源股（异动股下挂当天公告）、政策雷达、公司公告、今日概念、来源健康。新闻卡上的 🧵 表示所属专题和此前报道次数。
- **政策**：近 60 天的政策文件，可筛选“征求意见中”（还没过截止日的）、正式文件、政策解读。
- **数据**：每个指标一张趋势图（纵轴标单位），显示最新值和较上期变化。
- **专题**：各议题的时间线；AI 发现的新议题 14 天内出现 3 次以上会自动加入并标“自动”。
- **归档 / 收藏 / 术语**：历史简报、收藏的新闻（可导出 Markdown）、术语词典。顶部搜索框可搜所有历史简报。
- **用量**：每天 AI 用了多少 token、花了多少钱（见第 7 节）。
- **运行**：“立即更新”按钮、最近的运行记录（成功/失败原因、AI 是否可用、推送结果）、上次运行的日志。
- **设置**：所有开关（见第 2 节）。

每周日额外附“本周回顾”：一周最重要的 10 条、股价周涨跌、本周最热专题的约 600 字深度解读（AI 模式）。

**复制文字**
- 每条新闻右下角“复制”：复制“【分类】标题 / 摘要 / 👉 解读 / 📖 术语 / 来源 · 时间 / 原文链接”，可直接贴到微信或笔记。
- 日期旁“复制简报”：选“纯文字（适合微信）”或“Markdown（适合笔记）”，按“今日三件事 → 政策雷达 → 关键数据 → 能源股 → 公司公告 → 各类新闻 → 今日概念”排好。先点上方分类按钮筛选，就只复制这一类。
- 政策雷达、公司公告、关键数据、新闻中的关键数字、政策页、数据页、专题时间线、收藏页，标题旁都有“复制”，复制成带序号的清单。
- 新闻标题和摘要都可以用鼠标直接拖选复制；要看原文点“原文 ↗”。

**立即更新**：“运行”页点“更新网页”（只重新生成，不推送）或“更新并推送到手机”。页面会显示“排队中 → 运行中 → 等待网页发布 → 更新完成”，全程约 4–7 分钟，可以先去看别的页面。

## 2. 改设置

“设置”页（需先连接 GitHub）：

| 区块 | 能改什么 |
|---|---|
| 🔑 密钥 | 显示上次运行时各密钥是否已配置，按钮直达 GitHub 添加密钥的页面 |
| 🧠 AI 解读 | 开关；供应商的使用顺序（前一个不可用自动换下一个）和模型名；每天送给 AI 的候选条数 |
| 📲 推送到手机 | 渠道（可多选；都不选 = 只更新网页）；推送标题前缀 |
| ⏰ 数量与统计 | 抓取最近几小时、每天精选条数、每类最多几条；用量统计口径 |
| 🎯 内容偏好 | 关注清单（命中置顶标★）、降权词、政策雷达跟踪的省份 |
| 📈 股票与公告 | 关注的股票（沪 sh / 深 sz / 港 hk + 代码）、异动阈值、全市场公告关键词 |
| 📰 新闻来源 | 每个来源的开关；新增 Google 新闻搜索词 |
| 🧵 专题关键词 | 每行“专题名: 词1, 词2” |

- 点“保存”后修改写入仓库根目录的 `settings.json`，**下次生成时生效**（明早自动，或去“运行”页立即更新）。页面顶部会提示“有尚未生效的修改”。
- `settings.json` 只记录与默认值不同的项；每个区块都有“恢复默认”，页面底部有“全部恢复默认”。
- 每次保存都是一次 Git 提交，“设置修改历史”链接里能看到每次改了什么，必要时可在 GitHub 上恢复旧版本。
- 没连接 GitHub 的设备上，设置页是只读的；也可以改好后点“下载 settings.json”，在 GitHub 仓库页面 Add file → Upload files 上传到根目录。
- 默认值在 `config.yaml`、`stocks.yaml`、`sources.yaml`、`topics.yaml` 里（带注释），想改默认值可直接在 GitHub 网页上编辑这些文件。

**改每天的生成时间**：在 GitHub 打开 `.github/workflows/daily.yml`，点铅笔图标编辑 `cron: "30 23 * * *"`（UTC 时间，分 时；北京时间减 8 小时）。例如想北京时间 06:00 生成，改为 `"0 22 * * *"`。GitHub 的定时任务常有 5–30 分钟延迟。

## 3. AI 解读与费用

AI 模式会从约 40 条候选里挑选最有价值的新闻，为每条写 2 句摘要和 1 句“对行业意味着什么”，解释生僻术语，并写“今日三件事”和“今日学一个概念”。供应商按顺序尝试：前一个不可用（没密钥、报错）就换下一个；全部失败自动退回规则模式，保证每天都有简报。

| 供应商 | 需要的密钥 | 每天一次的费用 |
|---|---|---|
| DeepSeek（默认第一） | `DEEPSEEK_API_KEY` | 约 ¥0.02（约 ¥0.6/月） |
| Claude API（默认第二） | `ANTHROPIC_API_KEY` | 默认模型约 ¥0.7；设置里把模型改为 `claude-sonnet-5-5` 更便宜 |
| OpenAI / 通义千问 / Kimi / 智谱 | `OPENAI_API_KEY` / `DASHSCOPE_API_KEY` / `MOONSHOT_API_KEY` / `ZHIPU_API_KEY` | 视平台而定，智谱 glm-4-flash 免费 |

你的 Claude Pro 订阅不能在云端使用（订阅需要在电脑上登录 Claude Code）；云端按量付费的 API 和订阅是两套账户。

## 4. 推送到手机（可选）

网页本身就是每天的阅读入口，推送只是“到点提醒”。想要推送：在 GitHub 添加对应密钥（第 0 节第 4 步），再在“设置 → 推送到手机”勾选渠道。

| 渠道 | 适合 | 要添加的密钥 |
|---|---|---|
| PushPlus | 微信，最省事 | `PUSHPLUS_TOKEN` |
| Server酱 | 微信 | `SERVERCHAN_SENDKEY` |
| 企业微信 / 飞书 / 钉钉 | 群机器人 | `WECOM_WEBHOOK` / `FEISHU_WEBHOOK` / `DINGTALK_WEBHOOK` |
| Bark | iPhone 通知（App Store 装 Bark） | `BARK_KEY` |
| Telegram | Telegram | `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` |
| 邮件 | 邮箱（QQ 邮箱需在设置里开 SMTP 拿“授权码”） | `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`EMAIL_TO` |

注意：北京时间 07:30 推送时，瑞士是凌晨，建议手机对该应用开启“免打扰”或干脆不配推送，早上直接打开网址看。

## 5. 让推荐越来越合你口味（阅读反馈）

1. 读到有用的新闻点 👍，不感兴趣的点 👎（再点一次取消），记录保存在当前浏览器。
2. 攒了一些后，打开“收藏”页，点“提交反馈”：已连接 GitHub 的设备会直接把反馈存进仓库；没连接的设备会打开 GitHub 新建 Issue 页面（内容已填好，点 Submit new issue）。
3. 下次生成时程序合并反馈：同一来源、分类、关注词，每个 👍 加 0.5 分、每个 👎 减 0.5 分，单项最多 ±3 分；AI 挑选时也会参考你赞过/踩过的标题。收藏页会显示程序已学到的偏好；“清零偏好”可重新开始。

## 6. 自定义默认内容（高级）

网页设置页能改的都不需要动文件。想改更深的默认值，可在 GitHub 网页上直接编辑：

- `sources.yaml` 新闻来源：加一个 Google 新闻关键词只需一行，如 `- {name: 搜索·氢能, type: gnews, query: "绿氢 OR 电解槽", tier: 1}`。
- `stocks.yaml` 股票与公告：单日涨跌超过 `alert_pct`（默认 5%）会标 ⚠。
- `topics.yaml` 专题；`glossary.yaml` 术语表（“今日学一个概念”在 AI 不可用时也从这里轮换）。
- `config.yaml` 其他开关，如 `indicator_aliases`（新闻里的数字归入哪个指标）。

网页 `settings.json` 里的同名项优先于这些文件。

## 7. AI 用量与费用

- 每次调用大模型都记录输入、输出、缓存 token 和耗时（`state/usage.json`），“用量”页按天显示，并按 API 价格折算成美元和人民币（汇率按 7.2 估）。
- 参考量级：每天送给 AI 的内容约 8,800 字（40 条候选），合计约 1.3–1.6 万 token；周日多一次专题解读，约再加 4 千 token。DeepSeek 约 ¥0.02/天。
- 如果以后改回在本机用 Claude 订阅（`claude_cli`），可在“设置 → 数量与统计”把口径改成 Claude Pro，用量页会显示“约占套餐”的比例（偏保守的参考值）。

## 8. 运行监控

- “运行”页列出最近 14 次运行：时间、定时/手动、成功或失败原因、条数、AI 供应商、token、推送结果，以及运行提示（AI 不可用、某来源连续 3 天无数据、股价或公告缺失等）。
- 连接 GitHub 后，“运行”页还显示 GitHub 上最近的运行状态（包括还没来得及写入记录就失败的运行）。
- 配置了推送渠道时：运行出错会推送“⚠ 运行失败”和原因链接；北京时间 10:30 还没推送成功会发提醒（`watchdog` 工作流）。
- GitHub 失败时也会给你的 GitHub 邮箱发邮件。网络请求失败会自动重试 3 次；每次修改程序会自动跑离线自测（`tests` 工作流）。

## 9. 隐私与安全

- 仓库是公开的：任何拿到网址的人都能看到简报、设置（关注清单、股票等）和阅读反馈。不要在设置里写个人信息。
- 密钥只在 GitHub Secrets 里，不会出现在网页、仓库文件或运行记录中（网页只显示“已配置/未配置”）。
- 网页上的 GitHub 令牌只保存在你自己设备的浏览器里，只授权这一个仓库；手机丢失或不用时，到 GitHub 令牌页面删除即可。

## 10. 常见问题

- **网页没更新 / 还是昨天的**：先看“运行”页或 GitHub Actions 是否运行成功；成功后 Pages 发布还需 1–2 分钟；浏览器按 Ctrl+F5（Mac 按 Cmd+Shift+R）强制刷新。
- **显示“规则模式”**：AI 供应商都不可用。“设置 → 密钥”看 `DEEPSEEK_API_KEY` 是否“已配置”；已配置仍失败，多半是 DeepSeek 余额不足，看“运行”页日志里“跳过/失败”的原因。
- **Actions 报 “Permission denied” 或推送数据失败**：仓库 Settings → Actions → General → Workflow permissions 选 “Read and write permissions”，保存后重跑。
- **“连接 GitHub”提示令牌权限不足**：重新创建令牌，确认 Contents 和 Actions 都是 Read and write，且只选了 `power-brief` 仓库。
- **定时没有运行**：GitHub 定时常有延迟；公开仓库连续 60 天没有任何提交时会自动停用定时任务（每天的简报提交本身就算活动，一般不会发生），在 Actions 页面重新启用即可。
- **想在本机手动跑一次**（调试用，需要 Python 3.10+）：在本文件夹终端运行 `python -m pip install -r requirements.txt`，然后 `python -m powerbrief --force --no-push`；本机密钥写在 `.env`（复制 `.env.example`）。生成结果在 `docs/`，可双击 `docs/index.html` 查看，但要上传到 GitHub 才会出现在网址上。
- **版本与回滚**：当前版本见 `VERSION` 和网页底部，变更见 `CHANGELOG.md`。代码和每天的数据都在 Git 历史里，可在 GitHub 上回到任一版本。

### 命令行参数（本机调试用）

```bash
python -m powerbrief --force --no-push   # 生成网页数据，不推送
python -m powerbrief --no-ai             # 本次不用大模型
python -m powerbrief --dry-run           # 只看抓取统计和排序，不写文件
python -m powerbrief --weekly            # 非周日也生成周回顾和专题解读
python -m powerbrief --test-push         # 用最近一期测试推送渠道
python tests/test_offline.py             # 离线自测
```

> 免责声明：新闻版权归原作者，摘要仅供个人学习；股价仅供参考，不构成投资建议。
