/* PowerBrief 前端：纯静态，数据以 data/*.js 形式加载（本地双击打开也能用）。 */
(function () {
  "use strict";
  var APP_VERSION = "2.2.1";
  var CATS = ["政策法规", "市场与电价", "新能源与储能", "电网与技术", "企业动态", "国际", "综合"];
  var WATCH = "★ 关注";   // 今日页的特殊分类：只看命中关注清单的条目
  var state = { index: null, days: {}, glossary: null, extra: {}, cat: "全部", market: "A股", ptype: "全部" };
  var app = document.getElementById("app");

  // —— 本地存储（失败时退化为内存） ——
  var mem = {};
  function load(k, d) { try { var v = localStorage.getItem("pb_" + k); return v ? JSON.parse(v) : d; } catch (e) { return mem[k] || d; } }
  function save(k, v) { mem[k] = v; try { localStorage.setItem("pb_" + k, JSON.stringify(v)); } catch (e) { /* 忽略 */ } }
  var stars = load("stars", {});   // id -> item（含日期）
  var reads = load("reads", {});   // id -> 1
  var votes = load("votes", {});   // id -> {v, origin, source, category, watch, title, date}

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  // —— 数据加载：JSONP 风格，兼容 file:// ——
  var waiters = {};
  window.PB = {
    onIndex: function (d) { state.index = d; resolve("index", d); },
    onDay: function (d) { normalizeDay(d); state.days[d.date] = d; resolve("day:" + d.date, d); },
    onGlossary: function (d) { state.glossary = d; resolve("glossary", d); }
  };
  ["indicators", "topics", "policy", "weights", "usage", "settings", "runlog"].forEach(function (n) {
    window.PB["onExtra_" + n] = function (d) { state.extra[n] = d; resolve("extra:" + n, d); };
  });
  function resolve(key, d) { (waiters[key] || []).forEach(function (f) { f(d); }); delete waiters[key]; }
  var bust = 0;     // 网页检测到新数据后设为当前时间，强制重新下载数据（绕过浏览器缓存）
  var routeSeq = 0; // 每次切换页面加 1；数据加载完时页面已切走就不再渲染，避免旧页面盖掉新页面
  function loadScript(src, key, cb) {
    var first = !waiters[key], seq = routeSeq;
    (waiters[key] = waiters[key] || []).push(function (d) { if (seq === routeSeq) cb(d); });
    if (!first) return;
    var s = document.createElement("script");
    s.src = src + "?t=" + (bust || Math.floor(Date.now() / 60000));
    s.onerror = function () { resolve(key, null); };
    document.head.appendChild(s);
  }
  function getIndex(cb) { state.index ? cb(state.index) : loadScript("data/index.js", "index", cb); }
  function getDay(date, cb) { state.days[date] ? cb(state.days[date]) : loadScript("data/" + date + ".js", "day:" + date, cb); }
  function getGlossary(cb) { state.glossary ? cb(state.glossary) : loadScript("data/glossary.js", "glossary", cb); }
  function getExtra(n, cb) { state.extra[n] ? cb(state.extra[n]) : loadScript("data/" + n + ".js", "extra:" + n, cb); }

  // 旧数据缺字段时补默认值
  function normalizeDay(d) {
    d.highlights = d.highlights || []; d.stocks = d.stocks || []; d.items = d.items || [];
    d.source_stats = d.source_stats || {}; d.source_alerts = d.source_alerts || [];
    ["policy", "announcements", "key_numbers", "indicators", "notes"].forEach(function (k) { d[k] = d[k] || []; });
    d.items.forEach(function (it) {
      it.terms = it.terms || []; it.category = it.category || "综合"; it.summary = it.summary || "";
      it.why = it.why || ""; it.watch_hit = it.watch_hit || []; it.also = it.also || []; it.coverage = it.coverage || 1;
      it.topic_info = it.topic_info || []; it.policy_type = it.policy_type || "";
    });
  }

  // —— 工具 ——
  var WEEK = "日一二三四五六";
  function todayStr() { var d = new Date(Date.now() + 8 * 3600e3); return d.toISOString().slice(0, 10); }
  function weekday(date) { return "周" + WEEK[new Date(date + "T12:00:00").getDay()]; }
  function hm(iso) {
    if (!iso) return "";
    var d = new Date(iso); if (isNaN(d)) return "";
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }
  function pct(p) { return (p > 0 ? "+" : "") + Number(p).toFixed(2) + "%"; }
  function cls(p) { return p > 0 ? "up" : p < 0 ? "down" : ""; }
  function num(v) { return typeof v === "number" ? (Math.abs(v) >= 1000 ? v.toLocaleString("zh-CN", { maximumFractionDigits: 1 }) : String(+v.toFixed(3))) : esc(v); }
  function spark(arr) {
    if (!arr || arr.length < 2) return "";
    var mn = Math.min.apply(null, arr), mx = Math.max.apply(null, arr), r = (mx - mn) || 1;
    var pts = arr.map(function (v, i) { return (i * 54 / (arr.length - 1)).toFixed(1) + "," + (16 - (v - mn) / r * 14 + 1).toFixed(1); });
    var color = arr[arr.length - 1] >= arr[0] ? "var(--up)" : "var(--down)";
    return '<svg class="spark" viewBox="0 0 54 18" aria-hidden="true"><polyline fill="none" stroke="' + color +
      '" stroke-width="1.5" points="' + pts.join(" ") + '"/></svg>';
  }
  // 带坐标轴的折线图（数据页用）：series = [[日期, 值], ...]
  function lineChart(series, unit) {
    if (!series || !series.length) return '<p class="muted small">暂无数据</p>';
    var W = 320, H = 130, L = 44, R = 8, T = 10, B = 22;
    var vals = series.map(function (p) { return p[1]; });
    var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
    if (mn === mx) { mn -= 1; mx += 1; }
    var pad = (mx - mn) * 0.1; mn -= pad; mx += pad;
    var x = function (i) { return L + (series.length === 1 ? (W - L - R) / 2 : i * (W - L - R) / (series.length - 1)); };
    var y = function (v) { return T + (1 - (v - mn) / (mx - mn)) * (H - T - B); };
    var pts = series.map(function (p, i) { return x(i).toFixed(1) + "," + y(p[1]).toFixed(1); }).join(" ");
    var fmt = function (v) { return String(+v.toFixed(Math.abs(v) < 10 ? 2 : 1)); };
    var dots = series.length <= 40 ? series.map(function (p, i) { return '<circle cx="' + x(i).toFixed(1) + '" cy="' + y(p[1]).toFixed(1) + '" r="2" fill="var(--accent)"><title>' + esc(p[0]) + "：" + p[1] + esc(unit) + "</title></circle>"; }).join("") : "";
    return '<svg class="chart" viewBox="0 0 ' + W + " " + H + '" role="img">' +
      '<line x1="' + L + '" y1="' + T + '" x2="' + L + '" y2="' + (H - B) + '" stroke="var(--line)"/>' +
      '<line x1="' + L + '" y1="' + (H - B) + '" x2="' + (W - R) + '" y2="' + (H - B) + '" stroke="var(--line)"/>' +
      '<text x="' + (L - 4) + '" y="' + (T + 4) + '" text-anchor="end">' + fmt(mx) + "</text>" +
      '<text x="' + (L - 4) + '" y="' + (H - B) + '" text-anchor="end">' + fmt(mn) + "</text>" +
      '<text x="' + (L - 4) + '" y="' + ((H - B + T) / 2 + 4) + '" text-anchor="end">' + esc(unit) + "</text>" +
      '<text x="' + L + '" y="' + (H - 6) + '">' + esc(series[0][0]) + "</text>" +
      '<text x="' + (W - R) + '" y="' + (H - 6) + '" text-anchor="end">' + esc(series[series.length - 1][0]) + "</text>" +
      '<polyline fill="none" stroke="var(--accent)" stroke-width="1.8" points="' + pts + '"/>' + dots + "</svg>";
  }
  function setTab(t) {
    Array.prototype.forEach.call(document.querySelectorAll("#tabs a"), function (a) {
      a.classList.toggle("on", a.getAttribute("data-tab") === t); });
  }
  function head(title, extra) { return '<div class="dayhead"><h1>' + title + "</h1>" + (extra || "") + "</div>"; }
  function changeText(x) {
    if (x.change == null) return "";
    var u = x.unit === "%" ? "个百分点" : x.unit;
    return '<span class="' + cls(x.change) + '">' + (x.change > 0 ? "+" : "") + num(x.change) + esc(u) + "</span>";
  }

  // —— 提示与复制 ——
  function toast(msg, bad) {
    var t = document.createElement("div"); t.className = "toast" + (bad ? " bad" : ""); t.textContent = msg;
    document.body.appendChild(t); setTimeout(function () { t.remove(); }, 2200);
  }
  function copyFallback(text) {
    var ta = document.createElement("textarea"); ta.value = text; ta.setAttribute("readonly", "");
    ta.style.position = "fixed"; ta.style.top = "-1000px"; document.body.appendChild(ta); ta.select();
    var ok = false; try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove(); return ok;
  }
  function copyText(text, what) {
    var done = function () { toast("已复制" + (what ? "：" + what : "")); };
    var fail = function () { if (copyFallback(text)) done(); else toast("复制失败，请手动选中文字复制", true); };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fail); else fail();
  }
  function copyBtn(key, label) { return '<button class="cbtn" data-copy="' + esc(key) + '" title="复制为文字">' + (label || "复制") + "</button>"; }
  function ext(url, label) { return url ? '<a class="ext" href="' + esc(url) + '" target="_blank" rel="noopener" title="打开原文">' + (label || "↗") + "</a>" : ""; }

  // 文本构建：md=true 为 Markdown，否则纯文字（适合直接贴到微信）
  var TXT = {
    h: function (t, md) { return md ? "\n## " + t : "\n【" + t + "】"; },
    item: function (it, md) {
      var L = [md ? "**【" + it.category + "】" + it.title + "**" : "【" + it.category + "】" + it.title];
      if (it.summary) L.push(it.summary);
      if (it.why) L.push("👉 " + it.why);
      (it.terms || []).forEach(function (t) { L.push("📖 " + t.term + "：" + t.explain); });
      L.push([it.origin, hm(it.published)].filter(Boolean).join(" · "));
      if (it.url) L.push(md ? "[原文](" + it.url + ")" : it.url);
      return L.join("\n");
    },
    policyList: function (list, md) {
      return list.map(function (p, i) {
        return (i + 1) + ". [" + p.policy_type + "] " + (md ? "[" + p.title + "](" + p.url + ")" : p.title) +
          (p.deadline ? "（意见截止 " + p.deadline + "）" : "") + " —— " + p.origin + (p.date ? " " + p.date : "") +
          (md || !p.url ? "" : "\n   " + p.url);
      }).join("\n");
    },
    annList: function (list, md) {
      return list.map(function (a, i) {
        return (i + 1) + ". " + a.name + "：" + (md ? "[" + a.title + "](" + a.url + ")" : a.title + "\n   " + a.url);
      }).join("\n");
    },
    indicators: function (list) {
      return list.map(function (x) {
        var ch = x.change == null ? "" : "，较上期 " + (x.change > 0 ? "+" : "") + num(x.change) + (x.unit === "%" ? "个百分点" : x.unit);
        return "· " + x.name + "：" + num(x.value) + x.unit + "（" + x.date + ch + "）";
      }).join("\n");
    },
    numbers: function (list, md) {
      return list.map(function (k) {
        return "· " + k.name + "：" + num(k.value) + k.unit + (k.url ? (md ? " [来源](" + k.url + ")" : "  " + k.url) : "");
      }).join("\n");
    },
    stocks: function (list) {
      var top = list.slice().sort(function (a, b) { return Math.abs(b.pct) - Math.abs(a.pct); }).slice(0, 5);
      list.forEach(function (s) { if (s.alert && top.indexOf(s) < 0) top.push(s); });
      return top.map(function (s) { return "· " + s.name + " " + Number(s.price).toFixed(2) + "（" + pct(s.pct) + (s.alert ? " 异动" : "") + "）"; }).join("\n");
    },
    timeline: function (t, md) {
      return "专题：" + t.name + "（共 " + t.count + " 条）\n" + t.entries.map(function (e) {
        return e.date + "  " + (md ? "[" + e.title + "](" + e.url + ")" : e.title) + (e.summary ? "\n    " + e.summary : "") +
          (md || !e.url ? "" : "\n    " + e.url);
      }).join("\n");
    },
    items: function (list, md) {
      return list.map(function (it) { return TXT.item(it, md); }).join("\n\n");
    },
    brief: function (d, md, cat) {
      var all = !cat || cat === "全部";
      var items = d.items.filter(function (it) { return all || (cat === WATCH ? (it.watch_hit || []).length : it.category === cat); });
      var L = [(md ? "# " : "") + "⚡ 电力日报 " + d.date + " " + weekday(d.date) + (all ? "" : " · " + cat) +
        "（" + (d.mode === "ai" ? "AI 解读" : "规则模式") + "）"];
      if (all) {
        L.push(TXT.h("今日三件事", md)); d.highlights.forEach(function (h, i) { L.push((i + 1) + ". " + h); });
        if (d.policy.length) { L.push(TXT.h("政策雷达", md)); L.push(TXT.policyList(d.policy.slice(0, 6), md)); }
        if (d.indicators.length) { L.push(TXT.h("关键数据", md)); L.push(TXT.indicators(d.indicators)); }
        if (d.stocks.length) { L.push(TXT.h("能源股（涨跌幅前 5 与异动）", md)); L.push(TXT.stocks(d.stocks)); }
        if (d.announcements.length) { L.push(TXT.h("公司公告", md)); L.push(TXT.annList(d.announcements.slice(0, 5), md)); }
      }
      CATS.forEach(function (c) {
        var its = items.filter(function (it) { return it.category === c; });
        if (!its.length) return;
        L.push(TXT.h(c + "（" + its.length + " 条）", md));
        its.forEach(function (it, i) {
          L.push((i + 1) + ". " + (md ? "[" + it.title + "](" + it.url + ")" : it.title));
          if (it.summary) L.push("   " + it.summary);
          if (it.why) L.push("   👉 " + it.why);
          if (!md && it.url) L.push("   " + it.url);
        });
      });
      if (d.concept && all) { L.push(TXT.h("今日学一个概念：" + d.concept.term, md)); L.push(d.concept.explain); }
      return L.join("\n").replace(/\n{3,}/g, "\n\n") + "\n";
    }
  };

  // —— 渲染：单日 ——
  function itemCard(it, date) {
    var starred = !!stars[it.id], v = (votes[it.id] || {}).v || 0;
    var terms = it.terms.map(function (t) {
      return '<button class="term" data-ex="' + esc(t.explain) + '">📖 ' + esc(t.term) + "</button>"; }).join("");
    var threads = (it.topic_info || []).map(function (t) {
      return '<a class="thread" href="#/topic/' + encodeURIComponent(t.name) + '">🧵 ' + esc(t.name) +
        (t.prior ? " · 此前 " + t.prior + " 条" + (t.last ? "，上次 " + esc(t.last.slice(5)) : "") : " · 新专题") + "</a>"; }).join("");
    var also = it.also.length ? " · 同报：" + esc(it.also.join("、")) : "";
    return '<article class="card item' + (reads[it.id] ? " read" : "") + '" id="i-' + esc(it.id) + '" data-id="' + esc(it.id) + '">' +
      '<span class="cat c-' + esc(it.category) + '">' + esc(it.category) + "</span>" +
      (it.policy_type ? ' <span class="ptag">' + esc(it.policy_type) + "</span>" : "") +
      (it.watch_hit.length ? ' <span class="star small" title="命中关注清单">★ ' + esc(it.watch_hit.join("、")) + "</span>" : "") +
      (it.importance >= 4 ? ' <span class="badge">重要</span>' : "") +
      "<h3>" + esc(it.title) + "</h3>" +
      (it.summary ? "<p>" + esc(it.summary) + "</p>" : "") +
      (it.why ? '<p class="why">👉 ' + esc(it.why) + "</p>" : "") +
      (terms ? '<div class="terms">' + terms + "</div>" : "") +
      (threads ? '<div class="terms">' + threads + "</div>" : "") +
      '<div class="meta"><span>' + esc(it.origin) + "</span><span>" + hm(it.published) + "</span><span>" + also + "</span>" +
      '<span class="acts">' +
      (it.url ? '<a class="abtn" href="' + esc(it.url) + '" target="_blank" rel="noopener" data-read="' + esc(it.id) + '">原文 ↗</a>' : "") +
      '<button data-copy="item:' + esc(date) + ":" + esc(it.id) + '">复制</button>' +
      '<button data-vote="1" data-id="' + esc(it.id) + '" data-date="' + esc(date) + '" class="' + (v > 0 ? "on" : "") + '" title="有用，多推类似">👍</button>' +
      '<button data-vote="-1" data-id="' + esc(it.id) + '" data-date="' + esc(date) + '" class="' + (v < 0 ? "on" : "") + '" title="不感兴趣，少推类似">👎</button>' +
      '<button data-star="' + esc(it.id) + '" data-date="' + esc(date) + '" class="' + (starred ? "on" : "") + '">' +
      (starred ? "★ 已收藏" : "☆ 收藏") + "</button></span></div></article>";
  }

  function stockCard(d) {
    if (!d.stocks.length) return "";
    var anns = {}; d.announcements.forEach(function (a) { anns[a.id] = a; });
    var rows = d.stocks.filter(function (s) { return (s.market || "A股") === state.market; }).map(function (s) {
      var links = (s.anns || []).map(function (id) { return anns[id]; }).filter(Boolean).map(function (a) {
        return '<div class="small">📄 ' + esc(a.title) + " " + ext(a.url) + "</div>"; }).join("");
      return "<tr><td>" + esc(s.name) + '<div class="muted small">' + esc(s.group || "") + "</div>" + (s.alert ? links : "") + "</td>" +
        '<td class="num">' + spark(s.trend5) + "</td>" +
        '<td class="num">' + Number(s.price).toFixed(2) + "</td>" +
        '<td class="num ' + cls(s.pct) + (s.alert ? " alert" : "") + '">' + (s.alert ? "⚠ " : "") + pct(s.pct) + "</td>" +
        '<td class="num small ' + cls(s.week_pct) + '">' + (s.week_pct == null ? "" : "周" + pct(s.week_pct)) + "</td></tr>";
    }).join("");
    return '<section class="card"><h2>能源股 <span class="seg">' +
      ["A股", "港股"].map(function (m) { return '<button data-market="' + m + '" class="' + (state.market === m ? "on" : "") + '">' + m + "</button>"; }).join("") +
      '</span></h2><table class="stocks">' + rows + '</table><p class="muted small" style="margin:6px 0 0">红涨绿跌；⚠ 为单日涨跌超阈值；曲线为近 5 个交易日收盘价</p></section>';
  }

  function indicatorMini(d) {
    if (!d.indicators.length) return "";
    return '<section class="card"><h2>📊 关键数据 <a class="small muted" href="#/data">全部 ›</a>' + copyBtn("ind:" + d.date) + '</h2><div class="minis">' +
      d.indicators.map(function (x) {
        return '<div class="mini"><div class="muted small">' + esc(x.name) + '</div><b>' + num(x.value) + '</b> <span class="small">' + esc(x.unit) + "</span>" +
          '<div class="small">' + changeText(x) + ' <span class="muted">' + esc(x.date.slice(5) || x.date) + "</span></div>" +
          spark((x.series || []).map(function (p) { return p[1]; }).slice(-20)) + "</div>"; }).join("") + "</div></section>";
  }

  function policyCard(d) {
    if (!d.policy.length) return "";
    var today = todayStr();
    return '<section class="card"><h2>📜 政策雷达 <a class="small muted" href="#/policy">全部 ›</a>' + copyBtn("policy:" + d.date) + '</h2><ul class="plist">' +
      d.policy.slice(0, 6).map(function (p) {
        var open = p.deadline && p.deadline >= today;
        return '<li><span class="ptag">' + esc(p.policy_type) + "</span> " + esc(p.title) + " " + ext(p.url) +
          (p.deadline ? ' <span class="dl' + (open ? " open" : "") + '">截止 ' + esc(p.deadline) + "</span>" : "") +
          ' <span class="muted small">' + esc(p.origin) + "</span></li>"; }).join("") + "</ul></section>";
  }

  function annCard(d) {
    if (!d.announcements.length) return "";
    return '<section class="card"><h2>🏛 公司公告' + copyBtn("ann:" + d.date) + '</h2><ul class="plist small">' + d.announcements.map(function (a) {
      return "<li><b>" + esc(a.name) + "</b> " + esc(a.title) + " " + ext(a.url) +
        (a.origin !== "关注股票" ? ' <span class="muted">' + esc(a.origin) + "</span>" : "") + "</li>"; }).join("") +
      '</ul><p class="muted small" style="margin:6px 0 0">来源：巨潮资讯，链接为公告 PDF</p></section>';
  }

  function numbersCard(d) {
    if (!d.key_numbers.length) return "";
    return '<section class="card"><h2>🔢 新闻中的关键数字' + copyBtn("nums:" + d.date) + '</h2><ul class="plist small">' + d.key_numbers.map(function (k) {
      return "<li>" + esc(k.name) + "：<b>" + num(k.value) + "</b>" + esc(k.unit) +
        " " + ext(k.url, "来源 ↗") + "</li>"; }).join("") + "</ul></section>";
  }

  function renderDay(date) {
    setTab("day");
    var asked = date;
    getIndex(function (idx) {
      if (!idx || !idx.days.length) { app.innerHTML = '<p class="center muted">还没有简报。请先在电脑上运行一次程序。</p>'; return; }
      var dates = idx.days.map(function (x) { return x.date; });
      date = date || dates[0];
      getDay(date, function (d) {
        if (!d) { app.innerHTML = '<p class="center muted">找不到 ' + esc(date) + " 的简报。</p>"; return; }
        var i = dates.indexOf(date), prev = dates[i + 1], next = dates[i - 1];
        var nWatch = d.items.filter(function (it) { return it.watch_hit.length; }).length;
        var cats = ["全部"].concat(nWatch ? [WATCH] : []).concat(CATS.filter(function (c) { return d.items.some(function (it) { return it.category === c; }); }));
        if (cats.indexOf(state.cat) < 0) state.cat = "全部";
        var items = d.items.filter(function (it) { return state.cat === "全部" || (state.cat === WATCH ? it.watch_hit.length : it.category === state.cat); });
        var minutes = Math.max(1, Math.round(d.items.reduce(function (n, it) { return n + it.title.length + it.summary.length + it.why.length; }, 0) / 400));
        var mode = d.mode === "ai" ? "AI 解读 · " + esc(d.provider || "") : "规则模式";
        app.innerHTML =
          head(esc(date.slice(5).replace("-", "月")) + "日 " + weekday(date) + '<span class="badge">' + mode + "</span>",
            '<span class="nav"><details class="copymenu"><summary>' + (state.cat === "全部" ? "复制简报" : "复制当前分类") + "</summary><div>" +
            '<button data-copy="brief:' + date + ':txt">纯文字（适合微信）</button><button data-copy="brief:' + date + ':md">Markdown（适合笔记）</button></div></details> ' +
            '<a class="' + (prev ? "" : "off") + '" href="#/d/' + (prev || "") + '">‹ 前一天</a> ' +
            '<a class="' + (next ? "" : "off") + '" href="#/d/' + (next || "") + '">后一天 ›</a></span>') +
          (d.notes.length ? '<p class="note">⚠ ' + d.notes.map(esc).join("；") + "</p>" : "") +
          '<div class="grid"><div>' +
          '<section class="card hl"><h2>今日三件事 <span class="muted small">· ' + d.items.length + " 条 · 约 " + minutes + " 分钟读完</span></h2><ol>" +
          d.highlights.map(function (h) { return "<li>" + esc(h) + "</li>"; }).join("") + "</ol></section>" +
          policyCard(d) +
          '<div class="chips">' + cats.map(function (c) {
            var n = c === "全部" ? d.items.length : c === WATCH ? nWatch : d.items.filter(function (it) { return it.category === c; }).length;
            return '<button class="chip' + (state.cat === c ? " on" : "") + '" data-cat="' + esc(c) + '">' + esc(c) + " " + n + "</button>"; }).join("") + "</div>" +
          items.map(function (it) { return itemCard(it, date); }).join("") +
          '</div><aside class="side">' + indicatorMini(d) + stockCard(d) + annCard(d) + numbersCard(d) +
          (d.concept ? '<section class="card"><h2>💡 今日学一个概念</h2><b>' + esc(d.concept.term) + '</b><p style="margin:4px 0 0;font-size:14px">' + esc(d.concept.explain) + "</p></section>" : "") +
          weeklyCard(d) + healthCard(d) + "</aside></div>";
        // 默认打开最新一期时，由管理脚本判断“今天还没生成”并在顶部显示提示/进度
        if (!asked && window.PBonLatest) { app.insertAdjacentHTML("afterbegin", '<div id="todayBanner"></div>'); window.PBonLatest(date); }
        var parts = location.hash.split("/");
        if (parts[1] === "d" && parts[3]) { var el = document.getElementById("i-" + parts[3]); if (el) el.scrollIntoView(); }
      });
    });
  }

  function weeklyCard(d) {
    var w = d.weekly; if (!w) return "";
    var tp = w.topic;
    return '<section class="card"><h2>📅 本周回顾</h2><ol style="margin:0;padding-left:20px;font-size:14px">' +
      (w.top || []).map(function (t) { return "<li>" + esc(t.title) + " " + ext(t.url) + "</li>"; }).join("") + "</ol>" +
      ((w.stock_week || []).length ? '<p class="small" style="margin:8px 0 0">股价周涨跌：' + w.stock_week.map(function (s) {
        return esc(s.name) + ' <span class="' + cls(s.week_pct) + '">' + pct(s.week_pct) + "</span>"; }).join("，") + "</p>" : "") +
      (tp ? '<h2 style="margin-top:12px">🧵 本周专题：<a href="#/topic/' + encodeURIComponent(tp.name) + '">' + esc(tp.name) + "</a></h2>" +
        (tp.deep_dive ? '<div class="deep">' + esc(tp.deep_dive).replace(/\n/g, "<br>") + "</div>"
          : '<ul class="plist small">' + (tp.entries || []).map(function (e) { return "<li>" + esc(e.date.slice(5)) + " " + esc(e.title) + "</li>"; }).join("") + "</ul>") : "") +
      "</section>";
  }

  function healthCard(d) {
    var names = Object.keys(d.source_stats); if (!names.length) return "";
    var alerts = d.source_alerts.length ? '<p class="small" style="color:var(--warn);margin:4px 0">⚠ 连续 3 天抓取失败：' + esc(d.source_alerts.join("、")) + "（可能需要更新抓取规则）</p>" : "";
    var raw = d.source_raw || {};
    var art = d.article_stats ? '<p class="small muted" style="margin:4px 0">原文：解码 ' + d.article_stats.decoded + " 条，抓到正文 " + d.article_stats.text + " 条</p>" : "";
    return '<section class="card small"><details><summary>来源健康（' + names.length + " 个来源）</summary>" + alerts + art +
      '<table class="health">' + names.map(function (n) {
        var v = d.source_stats[n], r = raw[n];
        // 保留 0 条但抓到了内容：说明网站正常，只是这段时间没有电力相关或足够新的文章
        var cell = v < 0 ? '<span style="color:var(--warn)">失败</span>' : v === 0 && r > 0 ? '0 条 <span class="muted">（抓到 ' + r + " 条，均不相关或较旧）</span>" : v + " 条";
        return "<tr><td>" + esc(n) + '</td><td class="num">' + cell + "</td></tr>"; }).join("") +
      "</table></details></section>";
  }

  // —— 政策 ——
  function renderPolicy() {
    setTab("policy");
    getExtra("policy", function (d) {
      var all = (d && d.policy) || [], today = todayStr();
      var types = ["全部", "征求意见中", "正式文件", "征求意见", "政策解读"];
      all = all.slice().sort(function (a, b) { return b.date.localeCompare(a.date) || (b.official ? 1 : 0) - (a.official ? 1 : 0); });
      var list = all.filter(function (p) {
        if (state.ptype === "全部") return true;
        if (state.ptype === "征求意见中") return p.policy_type === "征求意见" && (!p.deadline || p.deadline >= today);
        return p.policy_type === state.ptype;
      });
      state.policyList = list;
      app.innerHTML = head("政策雷达 <span class=\"badge\">近 60 天 " + all.length + " 条</span>", copyBtn("policyPage", "复制列表（" + list.length + " 条）")) +
        '<div class="chips">' + types.map(function (t) { return '<button class="chip' + (state.ptype === t ? " on" : "") + '" data-ptype="' + t + '">' + t + "</button>"; }).join("") + "</div>" +
        '<section class="card">' + (list.map(function (p) {
          var open = p.deadline && p.deadline >= today;
          return '<div class="list-row"><b><span class="ptag">' + esc(p.policy_type) + "</span> " + esc(p.title) + "</b> " + ext(p.url, "原文 ↗") + "<br>" +
            (p.summary ? '<span class="small">' + esc(p.summary) + "</span><br>" : "") +
            '<span class="muted small">' + esc(p.date) + " · " + esc(p.origin) + "</span>" +
            (p.deadline ? ' <span class="dl' + (open ? " open" : "") + '">意见截止 ' + esc(p.deadline) + (open ? "" : "（已过）") + "</span>" : "") + "</div>";
        }).join("") || '<p class="muted">暂无</p>') + "</section>";
    });
  }

  // —— 数据 ——
  function renderData() {
    setTab("data");
    getExtra("indicators", function (d) {
      var list = (d && d.indicators) || [];
      getIndex(function (idx) {
        var latest = idx && idx.days.length ? idx.days[0].date : null;
        var draw = function (day) {
          state.dataList = list;
          app.innerHTML = head("行业数据", '<span class="muted small">' + list.length + " 个指标</span> " + copyBtn("dataPage", "复制全部指标")) +
            '<div class="dgrid">' + list.map(function (x) {
              return '<section class="card"><h2>' + esc(x.name) + '</h2><div><b class="big">' + num(x.value) + '</b> <span class="small">' + esc(x.unit) + "</span> " +
                changeText(x) + ' <span class="muted small">' + esc(x.date) + "</span></div>" + lineChart(x.series, x.unit) +
                '<p class="muted small" style="margin:2px 0 0">来源：' + esc(x.source) + "</p></section>"; }).join("") + "</div>" +
            (day && day.key_numbers.length ? numbersCard(day) : "") +
            '<p class="muted small">碳价、用电量取自公开报道中的数字，油气为新浪财经国际期货行情；其他指标由 AI 从新闻中摘录并按名称归类，仅供参考。</p>';
        };
        if (latest) getDay(latest, draw); else draw(null);
      });
    });
  }

  // —— 专题 ——
  function renderTopics(name) {
    setTab("topics");
    getExtra("topics", function (d) {
      var list = (d && d.topics) || [];
      if (name) {
        var t = list.filter(function (x) { return x.name === name; })[0];
        state.topicCur = t;
        app.innerHTML = head("🧵 " + esc(name), (t ? copyBtn("topic", "复制时间线") + " " : "") + '<a class="btn" href="#/topics">全部专题</a>') +
          (t ? '<section class="card"><p class="muted small" style="margin-top:0">共 ' + t.count + " 条，最近 " + esc(t.last) + (t.auto ? " · AI 自动发现的专题" : "") + '</p><ol class="timeline">' +
            t.entries.map(function (e) {
              return '<li><span class="muted small">' + esc(e.date) + "</span><br><b>" + esc(e.title) + "</b> " + ext(e.url) +
                (e.summary ? '<div class="small">' + esc(e.summary) + "</div>" : "") + "</li>"; }).join("") + "</ol></section>"
            : '<p class="card muted">这个专题还没有内容。</p>');
        return;
      }
      app.innerHTML = head("专题追踪", '<span class="muted small">' + list.length + " 个</span>") +
        '<section class="card">' + (list.map(function (t) {
          return '<a class="list-row" href="#/topic/' + encodeURIComponent(t.name) + '"><b>' + esc(t.name) + (t.auto ? ' <span class="badge">自动</span>' : "") +
            ' <span class="badge">' + t.count + " 条</span></b>" + '<span class="muted small">最近 ' + esc(t.last) + " · " + esc((t.entries[0] || {}).title || "") + "</span></a>";
        }).join("") || '<p class="muted">运行几天后，这里会把同一议题的新闻串成时间线。</p>') + "</section>";
    });
  }

  // —— 归档 / 收藏 / 术语 / 搜索 ——
  function renderArchive() {
    setTab("archive");
    getIndex(function (idx) {
      var days = (idx && idx.days) || [];
      app.innerHTML = head("归档", '<span class="muted small">共 ' + days.length + " 期</span>") +
        '<section class="card">' + (days.map(function (x) {
          return '<a class="list-row" href="#/d/' + x.date + '"><b>' + x.date + " " + weekday(x.date) + ' <span class="badge">' + x.count + " 条</span></b>" +
            '<span class="muted small">' + esc(x.headline) + "</span></a>"; }).join("") || '<p class="muted">暂无</p>') + "</section>";
    });
  }

  function renderStars() {
    setTab("stars");
    var list = Object.keys(stars).map(function (k) { return stars[k]; }).sort(function (a, b) { return (b._date || "").localeCompare(a._date || ""); });
    getExtra("weights", function (w) {
      w = w || {};
      var nv = Object.keys(votes).length;
      var top = function (o, sign) { return Object.keys(o || {}).filter(function (k) { return o[k] * sign > 0; })
        .sort(function (a, b) { return Math.abs(o[b]) - Math.abs(o[a]); }).slice(0, 6).map(function (k) { return esc(k) + "（" + (o[k] > 0 ? "+" : "") + o[k] + "）"; }).join("、") || "暂无"; };
      var merged = {}; ["origin", "category", "watch"].forEach(function (k) { Object.keys(w[k] || {}).forEach(function (n) { merged[n] = w[k][n]; }); });
      app.innerHTML = head("收藏 <span class=\"badge\">" + list.length + "</span>", list.length ? copyBtn("stars", "复制全部收藏") + ' <button class="btn" id="exportMd">导出 Markdown</button>' : "") +
        '<section class="card"><h2>阅读偏好</h2><p class="small" style="margin:0">本机已标记 👍👎 <b>' + nv + "</b> 条。程序已学到（共 " + (w.count || 0) + " 条反馈）：</p>" +
        '<p class="small" style="margin:4px 0">偏好：' + top(merged, 1) + '<br>减少：' + top(merged, -1) + "</p>" +
        '<button class="btn" id="sendFb"' + (nv ? "" : " disabled") + ">提交反馈</button> " +
        '<button class="btn" id="resetFb">清零偏好</button>' +
        '<p class="muted small" style="margin:6px 0 0">' + (w.repo ? "提交会打开 GitHub Issue 页面，点“Submit new issue”即可；下次运行时生效。"
          : "将下载 feedback.json，请把它放进程序的 state/feedback_inbox/ 文件夹，下次运行时生效。") + "</p></section>" +
        (list.length ? list.map(function (it) { return itemCard(it, it._date); }).join("") : '<p class="card muted">点击新闻卡片上的“☆ 收藏”，就会出现在这里，可导出为 Markdown 笔记。</p>');
    });
  }

  function submitFeedback(reset) {
    getExtra("weights", function (w) {
      var arr = Object.keys(votes).map(function (id) { var v = votes[id]; return { id: id, v: v.v, origin: v.origin, source: v.source, category: v.category, watch: v.watch, title: (v.title || "").slice(0, 40), date: v.date }; }).slice(-150);
      var payload = JSON.stringify(reset ? { reset: true, votes: [] } : { votes: arr });
      var gh = window.PBgh;
      if (gh && gh.connected()) {
        // 已连接 GitHub：直接把反馈存进仓库 state/feedback_inbox/，下次更新时生效
        gh.writeFile("state/feedback_inbox/feedback-" + Date.now() + ".json", payload, null, "阅读反馈 " + todayStr())
          .then(function () { toast("反馈已提交，下次更新时生效"); }, function (e) { toast("提交失败：" + e.message, true); });
      } else if (w && w.repo) {
        var url = "https://github.com/" + w.repo + "/issues/new?title=" + encodeURIComponent("feedback " + todayStr()) + "&body=" + encodeURIComponent(payload);
        window.open(url, "_blank", "noopener");
      } else {
        var a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([payload], { type: "application/json" }));
        a.download = "feedback-" + Date.now() + ".json"; document.body.appendChild(a); a.click(); a.remove();
      }
      if (reset) { votes = {}; save("votes", votes); renderStars(); }
    });
  }

  function exportMd() {
    var list = Object.keys(stars).map(function (k) { return stars[k]; }).sort(function (a, b) { return (a._date || "").localeCompare(b._date || ""); });
    var md = "# 电力日报收藏\n\n" + list.map(function (it) {
      return "## " + it.title + "\n\n- 日期：" + (it._date || "") + "　来源：" + it.origin + "　分类：" + it.category + "\n- 链接：" + it.url +
        (it.summary ? "\n- 摘要：" + it.summary : "") + (it.why ? "\n- 解读：" + it.why : "") +
        it.terms.map(function (t) { return "\n- 术语 " + t.term + "：" + t.explain; }).join("") + "\n";
    }).join("\n");
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown;charset=utf-8" }));
    a.download = "电力日报收藏.md"; document.body.appendChild(a); a.click(); a.remove();
  }

  function renderGlossary(q) {
    setTab("glossary");
    getGlossary(function (g) {
      g = g || {};
      var keys = Object.keys(g).filter(function (k) { return !q || k.indexOf(q) >= 0 || g[k].indexOf(q) >= 0; });
      app.innerHTML = head("术语表 <span class=\"badge\">" + keys.length + "</span>") +
        '<section class="card"><input id="glossQ" placeholder="筛选术语…" value="' + esc(q || "") +
        '" style="width:100%;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)">' +
        '<dl class="gl">' + keys.map(function (k) { return "<dt>" + esc(k) + "</dt><dd>" + esc(g[k]) + "</dd>"; }).join("") + "</dl></section>";
      var inp = document.getElementById("glossQ");
      inp.oninput = function () { var v = inp.value; clearTimeout(inp._t); inp._t = setTimeout(function () { renderGlossary(v); var n = document.getElementById("glossQ"); n.focus(); n.setSelectionRange(v.length, v.length); }, 250); };
    });
  }

  function renderSearch(q) {
    setTab("");
    getIndex(function (idx) {
      var res = [], ql = q.toLowerCase();
      ((idx && idx.days) || []).forEach(function (d) {
        d.items.forEach(function (r) { if ((r[1] + r[3]).toLowerCase().indexOf(ql) >= 0) res.push({ date: d.date, id: r[0], title: r[1], cat: r[2], sum: r[3] }); });
      });
      var hl = function (s) { return esc(s).split(esc(q)).join("<mark>" + esc(q) + "</mark>"); };
      app.innerHTML = head("搜索“" + esc(q) + "”", '<span class="muted small">' + res.length + " 条</span>") +
        '<section class="card">' + (res.slice(0, 200).map(function (r) {
          return '<a class="list-row" href="#/d/' + r.date + "/" + esc(r.id) + '"><b>' + hl(r.title) + '</b><span class="muted small">' + r.date + " · " + esc(r.cat) + (r.sum ? " · " + hl(r.sum) : "") + "</span></a>";
        }).join("") || '<p class="muted">没有找到</p>') + "</section>";
    });
  }

  function doCopy(key) {
    var k = key.split(":"), day = state.days[k[1]];
    if (k[0] === "item") {
      var it = findItem(k[2], k[1]); if (it) copyText(TXT.item(it, false), "这条新闻");
    } else if (k[0] === "brief" && day) {
      copyText(TXT.brief(day, k[2] === "md", state.cat), state.cat === "全部" ? "整份简报" : state.cat);
    } else if (k[0] === "policy" && day) copyText("政策雷达 " + day.date + "\n" + TXT.policyList(day.policy, false), "政策雷达");
    else if (k[0] === "ann" && day) copyText("公司公告 " + day.date + "\n" + TXT.annList(day.announcements, false), "公司公告");
    else if (k[0] === "ind" && day) copyText("关键数据\n" + TXT.indicators(day.indicators), "关键数据");
    else if (k[0] === "nums" && day) copyText("新闻中的关键数字 " + day.date + "\n" + TXT.numbers(day.key_numbers, false), "关键数字");
    else if (k[0] === "policyPage") copyText("政策雷达（" + state.ptype + "）\n" + TXT.policyList(state.policyList || [], false), "政策列表");
    else if (k[0] === "dataPage") copyText("行业数据\n" + TXT.indicators(state.dataList || []), "全部指标");
    else if (k[0] === "topic" && state.topicCur) copyText(TXT.timeline(state.topicCur, false), "专题时间线");
    else if (k[0] === "stars") {
      var list = Object.keys(stars).map(function (id) { return stars[id]; });
      copyText("电力日报收藏（" + list.length + " 条）\n\n" + TXT.items(list, false), "全部收藏");
    }
  }

  // —— 事件 ——
  function findItem(id, date) {
    var day = state.days[date];
    return (day && day.items.filter(function (x) { return x.id === id; })[0]) || stars[id];
  }
  app.addEventListener("click", function (e) {
    var t = e.target.closest("button, a"); if (!t) return;
    if (t.dataset.cat) { state.cat = t.dataset.cat; route(); }
    else if (t.dataset.ptype) { state.ptype = t.dataset.ptype; route(); }
    else if (t.dataset.market) { state.market = t.dataset.market; route(); }
    else if (t.classList.contains("term")) {
      var nx = t.parentNode.nextElementSibling;
      if (nx && nx.classList.contains("term-ex") && nx.dataset.term === t.textContent) { nx.remove(); return; }
      if (nx && nx.classList.contains("term-ex")) nx.remove();
      var div = document.createElement("div"); div.className = "term-ex"; div.dataset.term = t.textContent;
      div.textContent = t.textContent.replace("📖 ", "") + "：" + t.dataset.ex; t.parentNode.after(div);
    } else if (t.dataset.vote) {
      var id = t.dataset.id, v = +t.dataset.vote, it = findItem(id, t.dataset.date);
      if (votes[id] && votes[id].v === v) delete votes[id];
      else if (it) votes[id] = { v: v, origin: it.origin, source: it.source, category: it.category, watch: it.watch_hit, title: it.title, date: t.dataset.date };
      save("votes", votes);
      var box = t.parentNode;
      Array.prototype.forEach.call(box.querySelectorAll("[data-vote]"), function (b) { b.classList.toggle("on", !!votes[id] && votes[id].v === +b.dataset.vote); });
    } else if (t.dataset.star) {
      var sid = t.dataset.star;
      if (stars[sid]) delete stars[sid];
      else { var si = findItem(sid, t.dataset.date); if (si) { stars[sid] = JSON.parse(JSON.stringify(si)); stars[sid]._date = t.dataset.date; } }
      save("stars", stars);
      t.classList.toggle("on", !!stars[sid]); t.textContent = stars[sid] ? "★ 已收藏" : "☆ 收藏";
    } else if (t.dataset.copy) {
      doCopy(t.dataset.copy);
      var menu = t.closest("details"); if (menu) menu.open = false;
    } else if (t.id === "exportMd") exportMd();
    else if (t.id === "sendFb") submitFeedback(false);
    else if (t.id === "resetFb") { if (window.confirm("清零后程序学到的偏好会全部作废，确定吗？")) submitFeedback(true); }
    else if (t.dataset.read) {
      reads[t.dataset.read] = 1; save("reads", reads);
      var card = t.closest(".item"); if (card) card.classList.add("read");
    }
  });
  document.getElementById("searchForm").addEventListener("submit", function (e) {
    e.preventDefault(); var q = document.getElementById("searchInput").value.trim();
    if (q) location.hash = "#/search/" + encodeURIComponent(q);
  });
  document.getElementById("themeBtn").addEventListener("click", function () {
    var cur = document.documentElement.getAttribute("data-theme");
    var dark = cur ? cur === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    var nxt = dark ? "light" : "dark"; document.documentElement.setAttribute("data-theme", nxt); save("theme", nxt);
  });
  var th = load("theme", null); if (th) document.documentElement.setAttribute("data-theme", th);

  function route() {
    routeSeq++;
    var h = location.hash.replace(/^#\/?/, "").split("/");
    if (h[0] === "d") renderDay(h[1]);
    else if (h[0] === "policy") renderPolicy();
    else if (h[0] === "data") renderData();
    else if (h[0] === "topics") renderTopics(null);
    else if (h[0] === "topic") renderTopics(decodeURIComponent(h[1] || ""));
    else if (h[0] === "archive") renderArchive();
    else if (h[0] === "stars") renderStars();
    else if (h[0] === "glossary") renderGlossary("");
    else if (h[0] === "search" && !(window.PBRoutes && window.PBRoutes.search)) renderSearch(decodeURIComponent(h[1] || ""));
    else if (window.PBRoutes && window.PBRoutes[h[0]]) { setTab(h[0]); window.PBRoutes[h[0]](h.slice(1)); }
    else renderDay(null);
  }
  window.addEventListener("hashchange", function () { route(); window.scrollTo(0, 0); });
  window.PB.util = { esc: esc, head: head, setTab: setTab, getExtra: getExtra, num: num, route: route, app: app,
    toast: toast, copyText: copyText, TXT: TXT, seq: function () { return routeSeq; },
    getIndex: getIndex, getDay: getDay, CATS: CATS, WATCH: WATCH, weekday: weekday, ext: ext, today: todayStr, todayStr: todayStr,
    // 新数据发布后：清掉已读入的数据，重新下载并原地刷新当前页面
    refresh: function (stay) { bust = Date.now(); state.index = null; state.days = {}; state.extra = {}; if (!stay) route(); } };
  document.getElementById("foot").innerHTML = "PowerBrief v" + APP_VERSION + " · 新闻版权归原作者所有，摘要仅供个人学习参考 · 股价与数据仅供参考，不构成投资建议";
  route();

  if ("serviceWorker" in navigator && location.protocol.indexOf("http") === 0) {
    navigator.serviceWorker.register("sw.js").catch(function () { /* 忽略 */ });
  }
})();
