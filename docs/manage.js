/* PowerBrief 管理页面（v2.0 云端版）：设置、运行、用量。
   - 阅读不需要登录；改设置、立即更新需要在本设备“连接 GitHub”一次（粘贴只授权本仓库的访问令牌，只存在本浏览器）。
   - 设置保存为仓库根目录的 settings.json（只记录与默认值不同的项），下次生成简报时生效；旧版本留在 Git 历史里。
   - 密钥（DeepSeek、PushPlus 等）只在 GitHub 仓库的 Secrets 页面填写，网页只显示“已配置/未配置”。 */
(function () {
  "use strict";
  var U = window.PB.util, esc = U.esc, app = U.app;
  var API = "https://api.github.com";
  var WORKFLOW = "daily.yml";
  var CNY = 7.2; // 美元折人民币，仅用于显示

  // —— 小工具 ——
  function $(id) { return document.getElementById(id); }
  function toast(msg, bad) { U.toast(msg, bad); }
  function clone(o) { return JSON.parse(JSON.stringify(o == null ? {} : o)); }
  function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function list(v) { return (v || "").split(/[\n,，、;；]+/).map(function (x) { return x.trim(); }).filter(Boolean); }
  function num(v, d) { var n = parseFloat(v); return isNaN(n) ? d : n; }
  function field(label, html, hint) {
    return '<label class="fld"><span>' + label + "</span>" + html + (hint ? '<small class="muted">' + hint + "</small>" : "") + "</label>";
  }
  function input(id, val, type, attrs) { return '<input id="' + id + '" type="' + (type || "text") + '" value="' + esc(val == null ? "" : val) + '" ' + (attrs || "") + ">"; }
  function select(id, val, opts) {
    return '<select id="' + id + '">' + opts.map(function (o) { return '<option value="' + esc(o[0]) + '"' + (String(o[0]) === String(val) ? " selected" : "") + ">" + esc(o[1]) + "</option>"; }).join("") + "</select>";
  }
  function store(k, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem("pb_" + k) || "null"); if (v === null) localStorage.removeItem("pb_" + k); else localStorage.setItem("pb_" + k, JSON.stringify(v)); } catch (e) { return null; } }
  function b64enc(s) { return btoa(unescape(encodeURIComponent(s))); }
  function b64dec(s) { return decodeURIComponent(escape(atob(String(s).replace(/\s/g, "")))); }
  function localTime(iso) {
    if (!iso) return "";
    var d = new Date(iso); if (isNaN(d)) return iso;
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return (d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }
  function getPath(o, path) { for (var i = 0; i < path.length; i++) { if (o == null) return undefined; o = o[path[i]]; } return o; }
  function setPath(o, path, v) { for (var i = 0; i < path.length - 1; i++) { if (typeof o[path[i]] !== "object" || o[path[i]] === null || Array.isArray(o[path[i]])) o[path[i]] = {}; o = o[path[i]]; } o[path[path.length - 1]] = v; }
  function delPath(o, path) {
    var stack = [o];
    for (var i = 0; i < path.length - 1; i++) { o = o && o[path[i]]; if (!o || typeof o !== "object") return; stack.push(o); }
    delete o[path[path.length - 1]];
    for (var j = stack.length - 1; j > 0; j--) { if (Object.keys(stack[j]).length === 0) delete stack[j - 1][path[j - 1]]; }
  }
  // 与 Python 端 deep_merge 相同：字典逐键合并，列表和单值整体替换
  function merge(base, over) {
    if (over === undefined || over === null) return clone(base);
    if (base && typeof base === "object" && !Array.isArray(base) && typeof over === "object" && !Array.isArray(over)) {
      var out = clone(base); Object.keys(over).forEach(function (k) { out[k] = merge(base[k], over[k]); }); return out;
    }
    return clone(over);
  }
  function mergedAll(defaults, overlay) {
    var o = {}; ["config", "stocks", "sources", "topics"].forEach(function (k) { o[k] = merge((defaults || {})[k] || {}, (overlay || {})[k]); }); return o;
  }

  // —— GitHub 连接 ——
  function guessRepo(S) {
    var h = location.hostname, m = h.match(/^([^.]+)\.github\.io$/i), seg = location.pathname.split("/").filter(Boolean)[0];
    if (m && seg) return m[1] + "/" + seg;
    return (S && S.repo) || "";
  }
  var GH = {
    conf: function () { return store("gh") || null; },
    connected: function () { var c = GH.conf(); return !!(c && c.token && c.repo); },
    req: function (path, opt, conf) {
      var c = conf || GH.conf(); opt = opt || {};
      var headers = { Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" };
      if (c && c.token) headers.Authorization = "Bearer " + c.token;
      if (opt.body) headers["Content-Type"] = "application/json";
      return fetch(API + "/repos/" + c.repo + path, { method: opt.method || "GET", headers: headers, body: opt.body ? JSON.stringify(opt.body) : undefined, cache: "no-store" })
        .then(function (r) {
          if (r.status === 204) return {};
          return r.json().catch(function () { return {}; }).then(function (j) {
            if (r.ok) return j;
            var e = new Error(GH.explain(r.status, j.message)); e.status = r.status; throw e;
          });
        }, function () { throw new Error("连不上 GitHub，请检查网络"); });
    },
    explain: function (st, msg) {
      if (st === 401) return "令牌无效或已过期，请在“连接 GitHub”里重新粘贴";
      if (st === 403) return "令牌权限不足：需要本仓库的 Contents 和 Actions 读写权限（" + (msg || "") + "）";
      if (st === 404) return "找不到仓库或文件：检查仓库名，以及令牌是否授权了这个仓库";
      if (st === 409) return "保存冲突：设置刚被别处修改过，请刷新后重试";
      if (st === 422) return "GitHub 拒绝了请求：" + (msg || "");
      return "GitHub 返回错误 " + st + "：" + (msg || "");
    },
    connect: function (repo, token) {
      var c = { repo: repo.trim().replace(/^https?:\/\/github\.com\//, "").replace(/\/+$/, ""), token: token.trim() };
      return GH.req("", {}, c).then(function (r) {
        if (!r.permissions || !r.permissions.push) throw new Error("令牌没有写权限：创建令牌时 Contents 要选 Read and write");
        c.branch = r.default_branch || "main"; c.private = !!r.private; store("gh", c); return c;
      });
    },
    disconnect: function () { store("gh", null); },
    readFile: function (path) {
      var c = GH.conf();
      return GH.req("/contents/" + path + "?ref=" + encodeURIComponent(c.branch)).then(function (r) { return { text: b64dec(r.content || ""), sha: r.sha }; },
        function (e) { if (e.status === 404) return { text: null, sha: null }; throw e; });
    },
    writeFile: function (path, text, sha, msg) {
      var c = GH.conf(), body = { message: msg, content: b64enc(text), branch: c.branch };
      if (sha) body.sha = sha;
      return GH.req("/contents/" + path, { method: "PUT", body: body });
    },
    readOverlay: function () {
      return GH.readFile("settings.json").then(function (f) {
        var d = {}; if (f.text) { try { d = JSON.parse(f.text); } catch (e) { throw new Error("仓库里的 settings.json 不是有效的 JSON，请在 GitHub 上修正或删除它"); } }
        return { data: d && typeof d === "object" ? d : {}, sha: f.sha };
      });
    },
    dispatch: function (push) {
      var c = GH.conf();
      return GH.req("/actions/workflows/" + WORKFLOW + "/dispatches", { method: "POST", body: { ref: c.branch, inputs: { push: push ? "true" : "false" } } });
    },
    runs: function (n) { return GH.req("/actions/workflows/" + WORKFLOW + "/runs?per_page=" + (n || 6)).then(function (r) { return r.workflow_runs || []; }); }
  };
  window.PBgh = GH;

  function repoUrl(repo, path) { return "https://github.com/" + repo + (path || ""); }

  // —— 设置 ——
  var CHANNELS = [["pushplus", "微信 PushPlus"], ["serverchan", "微信 Server酱"], ["wecom", "企业微信机器人"], ["feishu", "飞书机器人"],
    ["dingtalk", "钉钉机器人"], ["bark", "iPhone Bark"], ["telegram", "Telegram"], ["email", "邮件"]];
  var PNAMES = { claude_cli: "Claude 命令行（只能本机用）", claude: "Claude API", deepseek: "DeepSeek", openai: "OpenAI (ChatGPT)", qwen: "通义千问", kimi: "Kimi", zhipu: "智谱 GLM" };
  var SECRET_HELP = {
    DEEPSEEK_API_KEY: "platform.deepseek.com → API keys → 创建", ANTHROPIC_API_KEY: "console.anthropic.com → API Keys",
    OPENAI_API_KEY: "platform.openai.com → API keys", PUSHPLUS_TOKEN: "pushplus.plus 微信扫码登录 → 一对一推送 → 复制 token"
  };
  var S = null;        // data/settings.js：上次生成时的生效配置
  var cur = null;      // 当前显示的配置（默认值 + 最新 settings.json）
  var latest = null;   // 仓库里最新的 settings.json {data, sha}
  var authErr = "";    // 读取仓库失败的原因（如令牌过期），显示在连接卡片里

  function secretBadge(name) {
    var on = S && S.secrets && S.secrets[name];
    return '<span class="badge ' + (on ? "ok" : "bad") + '">' + esc(name) + (on ? " 已配置" : " 未配置") + "</span>";
  }

  function connectCard(repo) {
    var c = GH.conf();
    if (GH.connected()) {
      return '<section class="card"><h2>🔗 GitHub 连接</h2><p class="small">本设备已连接 <b>' + esc(c.repo) + "</b>（分支 " + esc(c.branch) + "）。可以修改设置、立即更新。</p>" +
        (authErr ? '<p class="small bad">⚠ ' + esc(authErr) + "</p>" : "") +
        '<p class="small"><a href="' + repoUrl(c.repo, "/commits/" + c.branch + "/settings.json") + '" target="_blank" rel="noopener">设置修改历史 ↗</a> · ' +
        '<a href="' + repoUrl(c.repo, "/actions") + '" target="_blank" rel="noopener">运行记录（GitHub）↗</a></p>' +
        '<button class="btn" id="ghOff">断开本设备</button></section>';
    }
    return '<section class="card ghconnect"><h2>🔗 连接 GitHub（每台设备一次）</h2>' +
      '<p class="small">连接后才能在网页上改设置、点“立即更新”。阅读简报不需要连接。</p>' +
      field("仓库", input("ghRepo", repo, "text", 'placeholder="用户名/power-brief" autocomplete="off"')) +
      field("访问令牌", input("ghToken", "", "password", 'placeholder="github_pat_…" autocomplete="off"'),
        '在 <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">GitHub → 新建细粒度令牌 ↗</a> 创建：' +
        "Repository access 只选这个仓库；Permissions 里 Contents 和 Actions 都选 Read and write。令牌只保存在本浏览器。") +
      '<button class="btn" id="ghOn">连接</button></section>';
  }

  function renderSettings() {
    app.innerHTML = U.head("设置") + '<p class="muted">读取中…</p>';
    U.getExtra("settings", function (s) {
      S = s;
      if (!S) {
        app.innerHTML = U.head("设置") + '<section class="card"><p>还没有设置数据：完成一次云端运行后这里会显示当前设置。</p></section>' + connectCard(guessRepo(null));
        bindConnect(); return;
      }
      if (!GH.connected()) { latest = null; cur = clone(S.effective); draw(); return; }
      var seq = U.seq();
      GH.readOverlay().then(function (ov) {
        if (seq !== U.seq()) return;
        authErr = ""; latest = ov; cur = mergedAll(S.defaults, ov.data); draw();
      }).catch(function (e) {
        if (seq !== U.seq()) return;
        authErr = e.message; latest = null; cur = clone(S.effective); draw();
      });
    });
  }

  function draw() {
    var c = cur.config, ai = c.ai || {}, ps = ai.provider_settings || {}, st = cur.stocks || {}, so = cur.sources || {};
    var on = GH.connected(), repo = (GH.conf() || {}).repo || guessRepo(S);
    var order = (ai.providers || []).concat(Object.keys(ps).filter(function (k) { return (ai.providers || []).indexOf(k) < 0; }));
    var pending = on && latest && !same(latest.data || {}, S.overlay || {});
    var keyNames = []; (ai.providers || []).forEach(function (k) { if (ps[k] && ps[k].api_key_env) keyNames.push(ps[k].api_key_env); });
    ((c.notify || {}).channels || []).forEach(function (ch) { keyNames = keyNames.concat((S.channel_secrets || {})[ch] || []); });
    var dis = on ? "" : " disabled";

    app.innerHTML = U.head("设置", '<span class="muted small">保存后下次更新生效 · 上次生成 ' + esc(localTime(S.generated)) + "</span>") +
      (pending ? '<div class="note">有已保存、尚未生效的修改。<button class="btn sm" id="goRun">立即更新</button> 或等明早自动更新。</div>' : "") +
      (on ? "" : '<div class="note">当前为只读：连接 GitHub 后才能保存。也可以改好后点页面底部“下载 settings.json”，在 GitHub 网页上传到仓库根目录。</div>') +
      '<div class="sgrid">' +
      connectCard(repo) +
      // 密钥
      '<section class="card"><h2>🔑 密钥</h2><p class="small muted">密钥不经过网页，只在 GitHub 仓库的 Secrets 页面填写；这里显示上次运行时是否读到。</p>' +
      '<div class="badges">' + (keyNames.length ? keyNames.map(secretBadge).join("") : '<span class="muted small">当前设置不需要密钥</span>') + "</div>" +
      '<ul class="small plist">' + keyNames.filter(function (n) { return SECRET_HELP[n]; }).map(function (n) { return "<li><b>" + esc(n) + "</b>：" + esc(SECRET_HELP[n]) + "</li>"; }).join("") + "</ul>" +
      (repo ? '<a class="btn" href="' + repoUrl(repo, "/settings/secrets/actions/new") + '" target="_blank" rel="noopener">在 GitHub 添加密钥 ↗</a>' : "") + "</section>" +
      // AI
      '<section class="card"><h2>🧠 AI 解读</h2>' +
      '<label class="chk"><input type="checkbox" id="aiOn"' + (ai.enabled ? " checked" : "") + "> 开启 AI 解读（关闭则用规则模式）</label>" +
      '<p class="small muted">勾选要用的供应商，用 ↑↓ 调整顺序：前一个不可用（没密钥或出错）时自动换下一个。</p><ul class="plist2" id="provList">' +
      order.map(function (k) {
        var p = ps[k] || {};
        return '<li data-p="' + esc(k) + '"><label class="chk"><input type="checkbox" class="provOn"' + ((ai.providers || []).indexOf(k) >= 0 ? " checked" : "") + "> " + esc(PNAMES[k] || k) + "</label>" +
          ' <input class="provModel" value="' + esc(p.model || "") + '" title="模型名">' +
          '<span class="mv"><button class="btn sm" data-mv="-1">↑</button><button class="btn sm" data-mv="1">↓</button></span></li>'; }).join("") + "</ul>" +
      field("每天送给 AI 的候选条数", input("maxCand", ai.max_candidates || 40, "number", 'min="10" max="80"'), "越多覆盖越全，token 越多") +
      saveBtns("ai", dis) + "</section>" +
      // 推送
      '<section class="card"><h2>📲 推送到手机</h2><div class="chgrid">' + CHANNELS.map(function (ch) {
        var chk = ((c.notify || {}).channels || []).indexOf(ch[0]) >= 0;
        return '<label class="chk"><input type="checkbox" class="chOn" value="' + ch[0] + '"' + (chk ? " checked" : "") + "> " + ch[1] + "</label>"; }).join("") + "</div>" +
      '<p class="small muted">勾选后还要在 GitHub Secrets 填对应密钥（见“密钥”卡片）。不勾选任何渠道 = 只更新网页。</p>' +
      field("推送标题前缀", input("titlePrefix", (c.notify || {}).title_prefix || "")) +
      saveBtns("notify", dis) + "</section>" +
      // 数量与用量
      '<section class="card"><h2>⏰ 数量与统计</h2>' +
      '<div class="row2">' + field("抓取最近几小时", input("lookback", (c.run || {}).lookback_hours, "number")) +
      field("周一回看几小时", input("mondayLb", (c.run || {}).monday_lookback_hours == null ? 72 : c.run.monday_lookback_hours, "number"), "覆盖周末，0 = 不延长") +
      field("每天精选条数", input("maxItems", (c.run || {}).max_items, "number")) + "</div>" +
      '<div class="row2">' + field("每类最多几条", input("perCat", (c.run || {}).max_per_category, "number")) +
      field("用量统计口径", select("usagePlan", (c.usage || {}).plan || "api", [["api", "按 API 实际费用"], ["pro", "Claude Pro 套餐"], ["max5", "Claude Max 5x"], ["max20", "Claude Max 20x"]])) + "</div>" +
      '<p class="small muted">每天北京时间 06:47 起自动生成（你这里约 ' + esc(beijingToLocal("06:47")) + "）。GitHub 定时可能延迟或漏掉，所以设了 06:47、07:17、07:47、08:47 四个时段，先成功的那次生效。改时间需改 .github/workflows/daily.yml，见使用说明。</p>" +
      saveBtns("run", dis) + "</section>" +
      // 内容偏好
      '<section class="card"><h2>🎯 内容偏好</h2>' +
      field("关注清单（命中置顶标★）", '<textarea id="watch" rows="3">' + esc((c.watchlist || []).join("、")) + "</textarea>", "用顿号、逗号或换行分隔") +
      field("降权词（排序靠后）", '<textarea id="penalty" rows="2">' + esc((c.penalty_keywords || []).join("、")) + "</textarea>") +
      field("政策雷达跟踪省份", input("provinces", (c.policy_provinces || []).join("、"))) +
      saveBtns("content", dis) + "</section>" +
      // 股票
      '<section class="card"><h2>📈 关注股票与公告</h2><table class="stbl" id="stockTbl"><tr><th>代码</th><th>名称</th><th>分组</th><th></th></tr>' +
      (st.stocks || []).map(stockRow).join("") + '</table><button class="btn sm" id="addStock">＋ 添加</button>' +
      '<p class="small muted">沪市 sh+6 位、深市 sz+6 位、港股 hk+5 位，如 sh600900</p>' +
      '<div class="row2">' + field("异动阈值（%）", input("alertPct", st.alert_pct, "number", 'step="0.5"')) +
      field("全市场公告关键词", input("annKw", ((st.announcements || {}).keywords || []).join("、"))) + "</div>" +
      saveBtns("stocks", dis) + "</section>" +
      // 来源
      '<section class="card"><h2>📰 新闻来源</h2><ul class="plist2" id="srcList">' + (so.sources || []).map(function (s, i) {
        return '<li><label class="chk"><input type="checkbox" class="srcOn" data-i="' + i + '"' + (s.enabled === false ? "" : " checked") + "> " + esc(s.name) + '</label> <span class="muted small">' + esc(s.type === "gnews" ? s.query : s.type) + "</span></li>"; }).join("") +
      '</ul><div class="row2">' + field("新增搜索：名称", input("newSrcName", "", "text", 'placeholder="搜索·氢能"')) + field("搜索词", input("newSrcQuery", "", "text", 'placeholder="绿氢 OR 电解槽"')) + "</div>" +
      saveBtns("sources", dis) + "</section>" +
      // 专题
      '<section class="card"><h2>🧵 专题关键词</h2>' + field("每行一个：专题名: 词1, 词2", '<textarea id="topicsTxt" rows="8">' +
        esc(Object.keys((cur.topics || {}).topics || {}).map(function (k) { return k + ": " + (cur.topics.topics[k] || []).join(", "); }).join("\n")) + "</textarea>") +
      saveBtns("topics", dis) + "</section>" +
      "</div>" +
      '<section class="card"><h2>备份与恢复</h2><p class="small muted">网页上的修改只记录与默认值不同的项（settings.json）。每次保存都是一次 Git 提交，可在“设置修改历史”里查看和找回。</p>' +
      '<button class="btn" id="dlSettings">下载 settings.json</button> <button class="btn" id="resetAll"' + dis + ">全部恢复默认</button></section>";
    bindConnect(); bindSettings();
  }

  function saveBtns(key, dis) {
    return '<div class="sbtns"><button class="btn" data-save="' + key + '"' + dis + '>保存</button> <button class="btn sm ghost" data-reset="' + key + '"' + dis + ">恢复默认</button></div>";
  }
  function stockRow(s) {
    return '<tr><td><input class="sc" value="' + esc(s.code || "") + '"></td><td><input class="sn" value="' + esc(s.name || "") + '"></td><td><input class="sg" value="' + esc(s.group || "") + '"></td><td><button class="btn sm delStock">删</button></td></tr>';
  }
  function beijingToLocal(hm) {
    // 北京时间 = UTC+8，没有夏令时；换算成浏览器所在时区的今天的时刻
    var p = hm.split(":"), now = new Date(), q = function (n) { return (n < 10 ? "0" : "") + n; };
    var x = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), +p[0] - 8, +p[1]));
    return q(x.getHours()) + ":" + q(x.getMinutes());
  }

  function bindConnect() {
    var onBtn = $("ghOn"), off = $("ghOff");
    if (onBtn) onBtn.onclick = function () {
      var repo = $("ghRepo").value, tok = $("ghToken").value;
      if (!/^[\w.-]+\/[\w.-]+$/.test(repo.trim().replace(/^https?:\/\/github\.com\//, "").replace(/\/+$/, ""))) return toast("仓库格式应为 用户名/仓库名", true);
      if (!tok.trim()) return toast("请粘贴访问令牌", true);
      onBtn.disabled = true;
      GH.connect(repo, tok).then(function () { toast("已连接"); U.route(); }).catch(function (e) { toast(e.message, true); onBtn.disabled = false; });
    };
    if (off) off.onclick = function () { if (confirm("断开后本设备不能再修改设置（令牌会从本浏览器删除）。确定？")) { GH.disconnect(); U.route(); } };
    var go = $("goRun"); if (go) go.onclick = function () { location.hash = "#/run"; };
  }

  // 每个设置区块对应的字段路径；保存时与默认值相同的项会从 settings.json 删除
  var PATHS = {
    ai: [["config", "ai", "enabled"], ["config", "ai", "providers"], ["config", "ai", "max_candidates"]],
    notify: [["config", "notify", "channels"], ["config", "notify", "title_prefix"]],
    run: [["config", "run", "lookback_hours"], ["config", "run", "monday_lookback_hours"], ["config", "run", "max_items"], ["config", "run", "max_per_category"], ["config", "usage", "plan"]],
    content: [["config", "watchlist"], ["config", "penalty_keywords"], ["config", "policy_provinces"]],
    stocks: [["stocks", "stocks"], ["stocks", "alert_pct"], ["stocks", "announcements", "keywords"]],
    sources: [["sources", "sources"]],
    topics: [["topics", "topics"]]
  };
  function sectionPaths(key) {
    var ps = PATHS[key].slice();
    if (key === "ai") Object.keys(((S.defaults.config || {}).ai || {}).provider_settings || {}).forEach(function (k) { ps.push(["config", "ai", "provider_settings", k, "model"]); });
    return ps;
  }

  function collect(key) {
    var v = {};
    if (key === "ai") {
      v["config.ai.enabled"] = $("aiOn").checked; v["config.ai.max_candidates"] = num($("maxCand").value, 40);
      var order = [];
      app.querySelectorAll("#provList li").forEach(function (li) {
        var name = li.dataset.p; if (li.querySelector(".provOn").checked) order.push(name);
        var m = li.querySelector(".provModel").value.trim(); if (m) v["config.ai.provider_settings." + name + ".model"] = m;
      });
      v["config.ai.providers"] = order;
    } else if (key === "notify") {
      var chs = []; app.querySelectorAll(".chOn").forEach(function (cb) { if (cb.checked) chs.push(cb.value); });
      v["config.notify.channels"] = chs; v["config.notify.title_prefix"] = $("titlePrefix").value;
    } else if (key === "run") {
      v["config.run.lookback_hours"] = num($("lookback").value, 36); v["config.run.monday_lookback_hours"] = num($("mondayLb").value, 72); v["config.run.max_items"] = num($("maxItems").value, 22);
      v["config.run.max_per_category"] = num($("perCat").value, 6); v["config.usage.plan"] = $("usagePlan").value;
    } else if (key === "content") {
      v["config.watchlist"] = list($("watch").value); v["config.penalty_keywords"] = list($("penalty").value); v["config.policy_provinces"] = list($("provinces").value);
    } else if (key === "stocks") {
      var arr = [], bad = null;
      app.querySelectorAll("#stockTbl tr").forEach(function (tr) {
        var code = tr.querySelector(".sc"); if (!code) return;
        var x = code.value.trim().toLowerCase(); if (!x) return;
        if (!/^(sh\d{6}|sz\d{6}|hk\d{5})$/.test(x)) bad = x;
        arr.push({ code: x, name: tr.querySelector(".sn").value.trim(), group: tr.querySelector(".sg").value.trim() });
      });
      if (bad) throw new Error("股票代码格式不对：" + bad);
      // 保留默认清单里的其他字段（如市场标记）
      var old = {}; ((cur.stocks || {}).stocks || []).forEach(function (s) { old[s.code] = s; });
      v["stocks.stocks"] = arr.map(function (s) { return Object.assign({}, old[s.code] || {}, s); });
      v["stocks.alert_pct"] = num($("alertPct").value, 5); v["stocks.announcements.keywords"] = list($("annKw").value);
    } else if (key === "sources") {
      var src = clone((cur.sources || {}).sources || []);
      app.querySelectorAll(".srcOn").forEach(function (cb) { var s = src[+cb.dataset.i]; if (cb.checked) delete s.enabled; else s.enabled = false; });
      var nn = $("newSrcName").value.trim(), nq = $("newSrcQuery").value.trim();
      if (nn && nq) src.push({ name: nn, type: "gnews", query: nq, tier: 1 });
      else if (nn || nq) throw new Error("新增搜索需要同时填名称和搜索词");
      v["sources.sources"] = src;
    } else if (key === "topics") {
      var tp = {};
      $("topicsTxt").value.split("\n").forEach(function (line) {
        var m = line.split(/[:：]/); if (m.length < 2 || !m[0].trim()) return; tp[m[0].trim()] = list(m.slice(1).join(":"));
      });
      v["topics.topics"] = tp;
    }
    return v;
  }

  // 把一个区块的新值写进覆盖层：与默认值相同就删除，不同才记录
  function applyTo(ov, key, values) {
    sectionPaths(key).forEach(function (p) {
      var k = p.join(".");
      if (!(k in values)) { delPath(ov, p); return; }
      if (same(values[k], getPath(S.defaults, p))) delPath(ov, p); else setPath(ov, p, values[k]);
    });
    return ov;
  }

  function saveOverlay(mutate, msg) {
    // 先读最新版本再改，避免覆盖其他设备刚保存的修改
    return GH.readOverlay().then(function (ov) {
      var data = mutate(clone(ov.data));
      if (same(data, ov.data)) return "nochange";
      return GH.writeFile("settings.json", JSON.stringify(data, null, 1) + "\n", ov.sha, msg).then(function () { return "ok"; });
    });
  }

  var TITLES = { ai: "AI 解读", notify: "推送", run: "数量与统计", content: "内容偏好", stocks: "股票与公告", sources: "新闻来源", topics: "专题关键词" };
  function bindSettings() {
    app.querySelector("#provList").onclick = function (e) {
      var b = e.target.closest("[data-mv]"); if (!b) return;
      var li = b.closest("li"), mv = +b.dataset.mv;
      if (mv < 0 && li.previousElementSibling) li.parentNode.insertBefore(li, li.previousElementSibling);
      if (mv > 0 && li.nextElementSibling) li.parentNode.insertBefore(li.nextElementSibling, li);
    };
    $("addStock").onclick = function () { $("stockTbl").insertAdjacentHTML("beforeend", stockRow({})); };
    $("stockTbl").onclick = function (e) { if (e.target.classList.contains("delStock")) e.target.closest("tr").remove(); };
    app.querySelectorAll("[data-save]").forEach(function (b) {
      b.onclick = function () {
        var key = b.dataset.save, values;
        try { values = collect(key); } catch (e) { return toast(e.message, true); }
        b.disabled = true;
        saveOverlay(function (ov) { return applyTo(ov, key, values); }, "设置：" + TITLES[key])
          .then(function (r) { toast(r === "nochange" ? "没有改动" : "已保存，下次更新生效"); renderSettings(); })
          .catch(function (e) { toast("保存失败：" + e.message, true); b.disabled = false; });
      };
    });
    app.querySelectorAll("[data-reset]").forEach(function (b) {
      b.onclick = function () {
        var key = b.dataset.reset;
        if (!confirm("把“" + TITLES[key] + "”恢复为默认值？")) return;
        b.disabled = true;
        saveOverlay(function (ov) { sectionPaths(key).forEach(function (p) { delPath(ov, p); }); return ov; }, "设置：" + TITLES[key] + " 恢复默认")
          .then(function (r) { toast(r === "nochange" ? "已经是默认值" : "已恢复默认，下次更新生效"); renderSettings(); })
          .catch(function (e) { toast("失败：" + e.message, true); b.disabled = false; });
      };
    });
    $("resetAll").onclick = function () {
      if (!confirm("清空网页上做过的所有修改，全部恢复默认值？（可在设置修改历史里找回）")) return;
      saveOverlay(function () { return {}; }, "设置：全部恢复默认").then(function () { toast("已全部恢复默认"); renderSettings(); })
        .catch(function (e) { toast("失败：" + e.message, true); });
    };
    $("dlSettings").onclick = function () {
      // 未连接时：把页面上所有区块的当前值算进覆盖层再下载
      var ov = clone(latest ? latest.data : S.overlay), err = null;
      Object.keys(PATHS).forEach(function (k) { try { applyTo(ov, k, collect(k)); } catch (e) { err = e; } });
      if (err) return toast(err.message, true);
      var a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(ov, null, 1) + "\n"], { type: "application/json" }));
      a.download = "settings.json"; document.body.appendChild(a); a.click(); a.remove();
    };
  }

  // —— 运行 ——
  var job = null; // 当前跟踪的“立即更新”：{since, push, run, phase}
  function runStatusText(r) {
    if (!r) return "等待 GitHub 开始运行…";
    if (r.status === "queued" || r.status === "waiting" || r.status === "pending" || r.status === "requested") return "排队中…";
    if (r.status === "in_progress") return "运行中（抓取新闻、AI 解读，约 1–2 分钟）…";
    if (r.status === "completed") return r.conclusion === "success" ? "已完成" : "运行失败（" + r.conclusion + "）";
    return r.status;
  }
  function trigLabel(t) { return { schedule: "定时", dispatch: "手动", manual: "本机" }[t] || t || "—"; }

  function renderRun() {
    var on = GH.connected(), repo = (GH.conf() || {}).repo || "";
    app.innerHTML = U.head("运行") +
      '<section class="card"><h2>立即更新</h2>' +
      (on ? '<div class="runbtns"><button class="runbtn" data-dispatch="0"><b>更新网页</b><small class="muted">重新抓取并生成今天的简报，不推送</small></button>' +
        '<button class="runbtn" data-dispatch="1"><b>更新并推送到手机</b><small class="muted">今天已推送过也会再推一次</small></button></div>' +
        '<p class="small" id="jobLine"></p>'
        : '<p class="small">需要先在“设置”页连接 GitHub。也可以在 GitHub 仓库的 Actions → daily-brief → Run workflow 手动运行。</p><a class="btn" href="#/settings">去连接</a>') +
      '<p class="small muted">每天北京时间 06:47 起自动运行（你这里约 ' + esc(beijingToLocal("06:47")) + "），设了 4 个时段防止 GitHub 漏跑，最晚 08:47。</p></section>" +
      '<section class="card"><h2>最近运行</h2><div id="runlog"><p class="muted small">读取中…</p></div></section>' +
      (on ? '<section class="card"><h2>GitHub 上的运行</h2><div id="ghRuns"><p class="muted small">读取中…</p></div>' +
        '<p class="small"><a href="' + repoUrl(repo, "/actions/workflows/" + WORKFLOW) + '" target="_blank" rel="noopener">在 GitHub 查看全部 ↗</a></p></section>' : "") +
      '<section class="card"><details><summary>上次运行的日志</summary><pre class="logbox" id="logTail"></pre></details></section>';
    app.querySelectorAll("[data-dispatch]").forEach(function (b) { b.onclick = function () { startJob(b.dataset.dispatch === "1"); }; });
    loadRunlog(function (rl) { drawRunlog(rl); });
    if (on) GH.runs(6).then(drawGhRuns).catch(function (e) { var el = $("ghRuns"); if (el) el.innerHTML = '<p class="bad small">' + esc(e.message) + "</p>"; });
    showJob();
  }

  function loadRunlog(cb) {
    // 网络读取（带时间戳绕过缓存）；file:// 打开时退回脚本方式
    if (location.protocol.indexOf("http") === 0) {
      fetch("data/runlog.json?t=" + Date.now(), { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; })
        .then(cb, function () { cb(null); });
    } else U.getExtra("runlog", cb);
  }

  function drawRunlog(rl) {
    var el = $("runlog"); if (!el) return;
    var runs = (rl && rl.runs) || [];
    if (!runs.length) { el.innerHTML = '<p class="muted small">还没有运行记录（v2.0 云端第一次运行后出现）。</p>'; return; }
    el.innerHTML = '<table class="stbl"><tr><th>时间</th><th>方式</th><th>结果</th><th class="num">条数</th><th>AI</th><th class="num">token</th><th>推送</th></tr>' +
      runs.map(function (r) {
        return "<tr" + (r.ok ? "" : ' class="bad"') + "><td>" + (r.run_url ? '<a href="' + esc(r.run_url) + '" target="_blank" rel="noopener">' + esc(localTime(r.time)) + "</a>" : esc(localTime(r.time))) +
          "</td><td>" + esc(trigLabel(r.trigger)) + "</td><td>" + (r.ok ? "成功" : "失败：" + esc(r.error || "")) +
          '</td><td class="num">' + (r.items == null ? "—" : r.items) + "</td><td>" + esc(r.mode === "ai" ? (r.provider || "AI") : r.ok ? "规则模式" : "—") +
          '</td><td class="num">' + (r.tokens ? Number(r.tokens).toLocaleString() : "—") + "</td><td>" + esc(r.push || "—") + "</td></tr>" +
          ((r.notes || []).length ? '<tr><td></td><td colspan="6" class="small muted">' + r.notes.map(esc).join("；") + "</td></tr>" : "");
      }).join("") + "</table>";
    var lt = $("logTail"); if (lt) lt.textContent = ((rl && rl.log_tail) || []).join("\n") || "（无）";
  }

  function drawGhRuns(runs) {
    var el = $("ghRuns"); if (!el) return;
    if (!runs.length) { el.innerHTML = '<p class="muted small">GitHub 上还没有运行过。</p>'; return; }
    el.innerHTML = '<table class="stbl"><tr><th>开始</th><th>方式</th><th>状态</th></tr>' + runs.map(function (r) {
      var bad = r.status === "completed" && r.conclusion !== "success";
      return "<tr" + (bad ? ' class="bad"' : "") + '><td><a href="' + esc(r.html_url) + '" target="_blank" rel="noopener">' + esc(localTime(r.run_started_at || r.created_at)) + "</a></td><td>" +
        esc(r.event === "schedule" ? "定时" : r.event === "workflow_dispatch" ? "手动" : r.event) + "</td><td>" + esc(runStatusText(r)) + "</td></tr>";
    }).join("") + "</table>";
  }

  // 三段进度：排队 → 生成 → 发布。job.run 为 GitHub 上的这次运行；也可以“跟上”一次已经在跑的定时运行。
  var tick = null;
  function startJob(push) {
    if (job && job.phase !== "done") return toast("已有一次更新在进行中", true);
    if (push && !confirm("更新后会推送到手机（今天已推送过也会再推一次）。继续？")) return;
    job = { since: Date.now() - 60000, push: push, run: null, phase: "dispatch", started: Date.now() };
    showJob();
    GH.dispatch(push).then(function () { job.phase = "wait"; showJob(); setTimeout(pollJob, 3000); })
      .catch(function (e) { job.phase = "done"; job.error = e.message; showJob(); });
  }
  function followRun(r) {
    // 打开网页时已有运行在进行（定时或别处点的）：直接显示它的进度
    if (job && job.phase !== "done") return;
    job = { since: 0, push: r.event === "schedule", run: r, phase: "wait", started: new Date(r.created_at).getTime(), follow: true };
    if (r.status === "in_progress") job.genAt = new Date(r.run_started_at || r.created_at).getTime();
    showJob(); setTimeout(pollJob, 3000);
  }

  function pollJob() {
    if (!job || job.phase === "done") return;
    if (Date.now() - job.started > 25 * 60000) { job.phase = "done"; job.error = "等待超时，请在 GitHub 查看运行状态"; showJob(); return; }
    if (job.phase === "publish") {
      // 运行完成后等 GitHub Pages 发布新数据：网站上的运行记录里出现本次运行编号即为已发布
      loadRunlog(function (rl) {
        var hit = rl && (rl.runs || []).some(function (r) { return String(r.run_id) === String(job.run.id); });
        if (hit) {
          job.phase = "done"; job.ok = true; job.pubDone = Date.now(); showJob();
          toast("网页已更新"); U.refresh(/^#\/?settings/.test(location.hash));   // 设置页可能有未保存的修改，不重绘
        } else if (Date.now() - job.doneAt > 6 * 60000) { job.phase = "done"; job.ok = true; job.slow = true; showJob(); }
        else setTimeout(pollJob, 5000);
      });
      return;
    }
    GH.runs(6).then(function (runs) {
      drawGhRuns(runs);
      var r = job.run && job.run.id ? runs.filter(function (x) { return x.id === job.run.id; })[0]
        : runs.filter(function (x) { return x.event === "workflow_dispatch" && new Date(x.created_at).getTime() >= job.since; })[0];
      if (r) job.run = r;
      if (r && r.status === "in_progress" && !job.genAt) job.genAt = Date.now();
      if (r && r.status === "completed") {
        if (r.conclusion === "success") { job.phase = "publish"; job.doneAt = Date.now(); job.genAt = job.genAt || job.doneAt; }
        else if (r.conclusion === "skipped" || r.conclusion === "cancelled") { job.phase = "done"; job.error = "这次运行被取消或跳过，点链接看原因"; }
        else { job.phase = "done"; job.error = "运行失败（" + r.conclusion + "），点链接看原因"; }
      }
      showJob(); if (job.phase !== "done") setTimeout(pollJob, job.phase === "publish" ? 3000 : 5000);
    }).catch(function (e) { job.phase = "done"; job.error = e.message; showJob(); });
  }

  function mmss(ms) { var t = Math.max(0, Math.round(ms / 1000)); return Math.floor(t / 60) + ":" + (t % 60 < 10 ? "0" : "") + (t % 60); }
  function stepsHtml() {
    // 排队（含请求 GitHub）→ 生成（约 1 分钟）→ 发布（约 30 秒）；各段显示已用时间
    var now = Date.now(), gen = job.genAt, pub = job.doneAt, end = job.pubDone;
    var st = [["排队", job.started, gen || pub], ["生成（约 1 分钟）", gen, pub], ["发布（约 30 秒）", pub, end]];
    return '<span class="steps">' + st.map(function (x) {
      var cls = x[2] ? "done" : x[1] ? "on" : "";
      var t = x[1] ? " " + mmss((x[2] || now) - x[1]) : "";
      return '<span class="' + cls + '">' + (x[2] ? "✓ " : x[1] ? "⏳ " : "") + x[0] + t + "</span>";
    }).join('<span class="muted"> → </span>') + "</span>";
  }
  function jobHtml() {
    if (!job) return "";
    var link = job.run ? ' <a href="' + esc(job.run.html_url) + '" target="_blank" rel="noopener">运行详情 ↗</a>' : "";
    if (job.phase === "dispatch") return "正在请求 GitHub…";
    if (job.phase === "wait" || job.phase === "publish") return (job.follow ? (job.push ? "定时任务正在运行：" : "已有一次更新在运行：") : "") + stepsHtml() + link;
    if (job.error) return '<span class="bad">' + esc(job.error) + "</span>" + link;
    return '<span class="ok">✓ 更新完成，共用时 ' + mmss((job.pubDone || Date.now()) - job.started) + "</span>" +
      (job.slow ? "（网页发布较慢，稍后刷新即可）" : "（页面已自动刷新）") + link;
  }
  function showJob() {
    var active = !!job && job.phase !== "done";
    if (active && !tick) tick = setInterval(showJob, 1000);
    if (!active && tick) { clearInterval(tick); tick = null; }
    app.querySelectorAll("[data-dispatch]").forEach(function (b) { b.disabled = active; });
    var html = jobHtml();
    var el = $("jobLine"); if (el) el.innerHTML = html;
    var bn = $("todayBanner");
    if (bn && job && (active || job.ok || job.error)) bn.innerHTML = '<p class="note genbar">' + html + "</p>";
  }

  // —— 今日页：今天的简报还没生成时提示，并可一键生成（GitHub 定时任务可能延迟或漏跑） ——
  var runsChecked = 0;
  function onLatest(latestDate) {
    var bn = $("todayBanner"); if (!bn) return;
    if (job && (job.phase !== "done" || job.ok)) { showJob(); return; }
    var today = U.todayStr(), bjHour = new Date(Date.now() + 8 * 3600e3).getUTCHours();
    if (latestDate === today || bjHour < 7) return;   // 已是今天的，或还没到生成时间
    var repo = (GH.conf() || {}).repo || guessRepo(S);
    var actions = repo ? ' <a href="' + esc(repoUrl(repo, "/actions/workflows/" + WORKFLOW)) + '" target="_blank" rel="noopener">在 GitHub 查看 ↗</a>' : "";
    if (!GH.connected()) {
      bn.innerHTML = '<p class="note">今天（' + esc(today.slice(5)) + "）的简报还没生成：GitHub 定时任务可能延迟，" +
        (bjHour >= 9 ? "今天可能漏跑了。" : "通常 9 点前会完成。") + "在“设置”里连接 GitHub 后，这里可以一键生成。" + actions + "</p>";
      return;
    }
    bn.innerHTML = '<p class="note">今天（' + esc(today.slice(5)) + "）的简报还没生成：GitHub 定时任务可能延迟或漏跑。 " +
      '<button class="btn sm" id="genNow">立即生成</button>' + actions + "</p>";
    $("genNow").onclick = function () { startJob(false); };
    if (Date.now() - runsChecked < 30000) return;   // 30 秒内不重复查询
    runsChecked = Date.now();
    GH.runs(3).then(function (runs) {
      var r = runs.filter(function (x) { return x.status !== "completed"; })[0];
      if (r && $("todayBanner")) followRun(r);
    }, function () { /* 查不到就保留按钮 */ });
  }
  window.PBonLatest = onLatest;

  // —— 用量 ——
  function barChart(days) {
    if (!days.length) return '<p class="muted small">还没有用量记录：开启 AI 并配置密钥后运行一次就会出现。</p>';
    var W = 640, H = 170, L = 52, B = 22, T = 10, bw = Math.max(4, Math.min(28, (W - L - 10) / days.length - 4));
    var mx = Math.max.apply(null, days.map(function (d) { return d.total; })) || 1;
    var y = function (v) { return T + (1 - v / mx) * (H - T - B); };
    var bars = days.map(function (d, i) {
      var x = L + 6 + i * (bw + 4), parts = [["input", "var(--c-policy)"], ["cache_read", "var(--c-intl)"], ["cache_write", "var(--c-grid)"], ["output", "var(--c-market)"]], acc = 0;
      return parts.map(function (p) {
        var v = d[p[0]] || 0; if (!v) return "";
        var y1 = y(acc + v), y0 = y(acc); acc += v;
        return '<rect x="' + x + '" y="' + y1.toFixed(1) + '" width="' + bw + '" height="' + Math.max(0.5, y0 - y1).toFixed(1) + '" fill="' + p[1] + '"><title>' + esc(d.date) + " " + p[0] + "：" + v.toLocaleString() + "</title></rect>";
      }).join("");
    }).join("");
    var fmt = function (v) { return v >= 1000 ? (v / 1000).toFixed(v >= 1e5 ? 0 : 1) + "k" : String(v); };
    return '<div class="legend small"><i style="background:var(--c-policy)"></i>输入 <i style="background:var(--c-intl)"></i>缓存读取 <i style="background:var(--c-grid)"></i>缓存写入 <i style="background:var(--c-market)"></i>输出</div>' +
      '<svg class="chart" viewBox="0 0 ' + W + " " + H + '">' +
      '<line x1="' + L + '" y1="' + T + '" x2="' + L + '" y2="' + (H - B) + '" stroke="var(--line)"/><line x1="' + L + '" y1="' + (H - B) + '" x2="' + W + '" y2="' + (H - B) + '" stroke="var(--line)"/>' +
      '<text x="' + (L - 4) + '" y="' + (T + 4) + '" text-anchor="end">' + fmt(mx) + '</text><text x="' + (L - 4) + '" y="' + (H - B) + '" text-anchor="end">0</text>' +
      '<text x="' + (L - 4) + '" y="' + ((H - B + T) / 2 + 4) + '" text-anchor="end">token</text>' +
      '<text x="' + L + '" y="' + (H - 6) + '">' + esc(days[0].date) + '</text><text x="' + W + '" y="' + (H - 6) + '" text-anchor="end">' + esc(days[days.length - 1].date) + "</text>" + bars + "</svg>";
  }

  function renderUsage() {
    U.getExtra("usage", function (r) {
      if (!r) { app.innerHTML = U.head("AI 用量") + '<p class="card muted">还没有用量数据。</p>'; return; }
      var days = r.days || [];
      var tile = function (label, val, sub) { return '<div class="tile"><div class="muted small">' + label + '</div><b>' + val + "</b>" + (sub ? '<div class="small muted">' + sub + "</div>" : "") + "</div>"; };
      var usd = function (v) { return "$" + (v || 0).toFixed(v < 1 ? 3 : 2); };
      var cny = function (v) { return "约 ¥" + ((v || 0) * CNY).toFixed(2); };
      var planTile = r.plan_fee_usd ? tile("约占套餐", r.plan_share_pct == null ? "—" : r.plan_share_pct + "%", "折算费用 ÷ 月费 $" + r.plan_fee_usd)
        : tile("每月费用", cny(r.month_cost_usd), "按 API 实际价格，汇率按 " + CNY + " 估");
      app.innerHTML = U.head("AI 用量", '<span class="muted small">口径：' + esc(r.plan_name) + "</span>") +
        '<section class="card"><div class="tiles">' +
        tile("平均每天 token", (r.avg_tokens_per_day || 0).toLocaleString(), "近 30 天有用量的 " + r.days_with_usage + " 天") +
        tile("平均每天费用", usd(r.avg_cost_per_day_usd), cny(r.avg_cost_per_day_usd)) +
        tile("每月约", (r.month_tokens || 0).toLocaleString() + " token", usd(r.month_cost_usd)) + planTile +
        "</div>" + (r.plan_fee_usd ? '<p class="small muted" style="margin:8px 0 0">' + esc(r.note) + "</p>" : "") + "</section>" +
        '<section class="card"><h2>每日 token</h2>' + barChart(days.slice(-30)) + "</section>" +
        '<section class="card"><h2>调用明细</h2><div class="tblwrap"><table class="stbl usage"><tr><th>日期</th><th>用途</th><th>供应商 / 模型</th><th class="num">输入</th><th class="num">缓存</th><th class="num">输出</th><th class="num">费用</th><th class="num">耗时</th></tr>' +
        days.slice().reverse().slice(0, 30).map(function (d) {
          return d.detail.map(function (c) {
            return "<tr" + (c.ok ? "" : ' class="bad"') + "><td>" + esc(d.date.slice(5)) + "</td><td>" + esc(c.purpose === "weekly" ? "周专题" : "日报") + "</td><td>" + esc(c.provider) + '<div class="muted small">' + esc(c.model) + "</div></td>" +
              '<td class="num">' + (c.input || 0).toLocaleString() + '</td><td class="num">' + ((c.cache_read || 0) + (c.cache_write || 0)).toLocaleString() +
              '</td><td class="num">' + (c.output || 0).toLocaleString() + '</td><td class="num">' + (c.cost_usd == null ? "—" : usd(c.cost_usd)) + (c.cost_source === "估算" ? "*" : "") +
              '</td><td class="num">' + c.seconds + "s</td></tr>"; }).join(""); }).join("") +
        '</table></div><p class="small muted">* 按价目表估算。失败的调用标红，通常 token 为 0。</p></section>';
    });
  }

  window.PBRoutes = { settings: renderSettings, run: renderRun, usage: renderUsage };
  // app.js 先于本文件加载并已路由过一次：直接打开 #/settings 等网址时在这里补一次
  if (window.PBRoutes[location.hash.replace(/^#\/?/, "").split("/")[0]]) U.route();
})();
