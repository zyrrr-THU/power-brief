/* PowerBrief 扩展页面（云端版与本地版共用同一份文件）：
   - #/report/起/止/每类条数   周报 / 月报：按时间段汇总，复制文字、下载 Markdown、下载 Word
   - #/watch                   关注：近 30 天命中关注清单的新闻，按关注词分组
   - #/search/词/范围/类别/来源  历史检索：筛选 + 每周出现次数趋势图
   数据来自 data/index.js（每条 [id, 标题, 类别, 摘要, 来源, 关注命中, 分数]，旧索引只有前 4 项）和每天的 data/<日期>.js。 */
(function () {
  "use strict";
  var U = window.PB && window.PB.util;
  if (!U || !U.getIndex) return;   // app.js 版本太旧时不启用
  var esc = U.esc, app = U.app, CATS = U.CATS;

  // —— 日期工具（按日历日计算，用中午 12 点避免时区和夏令时误差）——
  function D(s) { return new Date(s + "T12:00:00Z"); }
  function iso(d) { return d.toISOString().slice(0, 10); }
  function addDays(s, n) { var d = D(s); d.setUTCDate(d.getUTCDate() + n); return iso(d); }
  function weekStart(s) { var d = D(s); d.setUTCDate(d.getUTCDate() - (d.getUTCDay() + 6) % 7); return iso(d); }  // 周一
  function md(s) { return s.slice(5); }
  function rows(idx) {
    var out = [];
    ((idx && idx.days) || []).forEach(function (d) {
      (d.items || []).forEach(function (r) {
        out.push({ date: d.date, id: r[0], title: r[1] || "", cat: r[2] || "综合", sum: r[3] || "", origin: r[4] || "",
          watch: r[5] || [], score: r[6] || 0, rich: r.length > 4 });
      });
    });
    return out;
  }
  function latestDate(idx) { return idx && idx.days.length ? idx.days[0].date : U.today(); }
  function go(parts) { location.hash = "#/" + parts.map(function (p) { return encodeURIComponent(p == null ? "" : p); }).join("/"); }
  function download(name, text, type) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: type }));
    a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
  }
  function watchlist(cb) {
    U.getExtra("settings", function (s) {
      var w = s && s.effective && s.effective.config && s.effective.config.watchlist;
      cb(Array.isArray(w) ? w : []);
    });
  }

  // ======================= 周报 / 月报 =======================
  function presets(today) {
    var ws = weekStart(today), m1 = today.slice(0, 8) + "01";
    var pm1 = addDays(m1, -1).slice(0, 8) + "01";
    return [["近 7 天", addDays(today, -6), today], ["本周", ws, today], ["上周", addDays(ws, -7), addDays(ws, -1)],
      ["本月", m1, today], ["上月", pm1, addDays(m1, -1)]];
  }

  function dedupe(list, key) {
    var seen = {}; return list.filter(function (x) { var k = key(x); if (seen[k]) return false; seen[k] = 1; return true; });
  }

  // 汇总成“块”列表，三种输出（预览/Word、Markdown、纯文字）共用
  function buildReport(days, inds, start, end, per) {
    var items = [];
    days.forEach(function (d) { d.items.forEach(function (it) { var x = {}; for (var k in it) x[k] = it[k]; x.date = d.date; items.push(x); }); });
    var B = [], push = function (type, text, url, note) { B.push({ type: type, text: text, url: url || "", note: note || "" }); };
    var kind = (D(end) - D(start)) / 864e5 >= 27 ? "月报" : "周报";
    B.title = "电力行业" + kind + "（" + start + " 至 " + end + "）";

    // 一、概况
    var catN = CATS.map(function (c) { return [c, items.filter(function (it) { return it.category === c; }).length]; }).filter(function (x) { return x[1]; });
    push("h2", "一、概况");
    push("p", "共 " + days.length + " 期简报、" + items.length + " 条新闻：" + catN.map(function (x) { return x[0] + " " + x[1] + " 条"; }).join("，") + "。");
    var wc = {}; items.forEach(function (it) { (it.watch_hit || []).forEach(function (w) { wc[w] = (wc[w] || 0) + 1; }); });
    var wl = Object.keys(wc).sort(function (a, b) { return wc[b] - wc[a]; });
    if (wl.length) push("p", "关注词命中：" + wl.map(function (w) { return w + " " + wc[w] + " 次"; }).join("，") + "。");

    // 二、各类要闻（按重要度排序，同标题只留一条）
    push("h2", "二、各类要闻");
    catN.forEach(function (x) {
      var list = dedupe(items.filter(function (it) { return it.category === x[0]; })
        .sort(function (a, b) { return (b.score || 0) - (a.score || 0); }), function (it) { return it.title; }).slice(0, per);
      push("h3", x[0] + "（共 " + x[1] + " 条，选 " + list.length + " 条）");
      list.forEach(function (it) { push("li", it.title, it.url, md(it.date) + (it.origin ? " · " + it.origin : "") + (it.summary ? "｜" + it.summary : "")); });
    });

    // 三、政策动态
    var pol = dedupe([].concat.apply([], days.map(function (d) { return d.policy; })), function (p) { return p.title; });
    if (pol.length) {
      push("h2", "三、政策动态（" + pol.length + " 条）");
      pol.slice(0, 15).forEach(function (p) { push("li", "[" + (p.policy_type || "政策") + "] " + p.title, p.url, md(p.date || "") + (p.deadline ? " · 截止 " + p.deadline : "")); });
    }

    // 四、关键数据：时间段内首尾值的变化
    var rowsI = [];
    (inds || []).forEach(function (x) {
      var s = (x.series || []).filter(function (p) { return p[0] >= start && p[0] <= end; });
      if (!s.length) return;
      var a = s[0], b = s[s.length - 1], ch = b[1] - a[1];
      var pct = a[1] ? " / " + (ch >= 0 ? "+" : "") + (ch / Math.abs(a[1]) * 100).toFixed(1) + "%" : "";
      rowsI.push(x.name + "：" + (s.length > 1 ? fmt(a[1]) + " → " + fmt(b[1]) + " " + x.unit + "（" + (ch >= 0 ? "+" : "") + fmt(ch) + pct + "，" + md(a[0]) + " 至 " + md(b[0]) + "）"
        : fmt(b[1]) + " " + x.unit + "（" + md(b[0]) + "）"));
    });
    if (rowsI.length) { push("h2", "四、关键数据"); rowsI.forEach(function (t) { push("li", t); }); }

    // 五、重要公告
    var ann = dedupe([].concat.apply([], days.map(function (d) { return d.announcements.filter(function (a) { return a.level === "important"; }); })), function (a) { return a.title; });
    if (ann.length) {
      push("h2", "五、重要公告");
      ann.slice(0, 10).forEach(function (a) { push("li", a.name + "：" + a.title, a.url, (a.published || "").slice(5, 10)); });
    }

    // 六、专题动态：条目最多的 3 个专题
    var tp = {};
    items.forEach(function (it) {
      var names = (it.topic_info || []).map(function (t) { return t.name; });
      if (!names.length && Array.isArray(it.topics)) names = it.topics;
      names.forEach(function (n) { (tp[n] = tp[n] || []).push(it); });
    });
    var tl = Object.keys(tp).sort(function (a, b) { return tp[b].length - tp[a].length; }).slice(0, 3);
    if (tl.length) {
      push("h2", "六、专题动态");
      tl.forEach(function (n) {
        var last = tp[n].slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; })[0];
        push("li", n + "：本期 " + tp[n].length + " 条，最新：" + last.title, last.url, md(last.date));
      });
    }
    return B;
  }
  function fmt(v) { return Math.abs(v) >= 100 ? (+v.toFixed(1)).toLocaleString("zh-CN") : String(+v.toFixed(2)); }

  function toText(B, markdown) {
    var L = [(markdown ? "# " : "") + B.title, ""];
    B.forEach(function (b) {
      if (b.type === "h2") L.push("", (markdown ? "## " : "") + b.text);
      else if (b.type === "h3") L.push((markdown ? "### " : "【") + b.text + (markdown ? "" : "】"));
      else if (b.type === "p") L.push(b.text);
      else L.push((markdown ? "- " + (b.url ? "[" + b.text + "](" + b.url + ")" : b.text) : "· " + b.text) +
        (b.note ? (markdown ? "  \n  " : "\n  ") + b.note : "") + (!markdown && b.url ? "\n  " + b.url : ""));
    });
    return L.join("\n").replace(/\n{3,}/g, "\n\n") + "\n";
  }
  function toHtml(B) {
    var h = [], open = false;
    var close = function () { if (open) { h.push("</ul>"); open = false; } };
    B.forEach(function (b) {
      if (b.type === "li") {
        if (!open) { h.push("<ul>"); open = true; }
        h.push("<li>" + (b.url ? '<a href="' + esc(b.url) + '">' + esc(b.text) + "</a>" : esc(b.text)) +
          (b.note ? '<br><span class="rnote">' + esc(b.note) + "</span>" : "") + "</li>");
      } else { close(); h.push("<" + (b.type === "p" ? "p" : b.type) + ">" + esc(b.text) + "</" + (b.type === "p" ? "p" : b.type) + ">"); }
    });
    close();
    return "<h1>" + esc(B.title) + "</h1>" + h.join("");
  }
  function toWord(B) {
    // Word 能直接打开的 HTML 文档（简化格式，可在 Word 中继续编辑、另存为 docx）
    return "﻿<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word'>" +
      "<head><meta charset='utf-8'><title>" + esc(B.title) + "</title><style>" +
      "body{font-family:'宋体',SimSun,serif;font-size:12pt;line-height:1.5}" +
      "h1{font-family:'黑体',SimHei,sans-serif;font-size:16pt;text-align:center}" +
      "h2{font-family:'黑体',SimHei,sans-serif;font-size:14pt;margin-top:12pt}" +
      "h3{font-family:'楷体',KaiTi,serif;font-size:12pt;font-weight:bold}" +
      "li{margin-bottom:4pt}.rnote{color:#555;font-size:10.5pt}a{color:#1a4f8a}" +
      "</style></head><body>" + toHtml(B) +
      "<p style='color:#888;font-size:9pt'>由电力日报自动生成；新闻版权归原作者所有。</p></body></html>";
  }

  function renderReport(args) {
    U.getIndex(function (idx) {
      var today = U.today(), last = latestDate(idx), ps = presets(today);
      var start = args[0] || ps[0][1], end = args[1] || ps[0][2], per = Math.max(1, Math.min(20, parseInt(args[2], 10) || 6));
      if (start > end) { var t = start; start = end; end = t; }
      var dates = ((idx && idx.days) || []).map(function (d) { return d.date; }).filter(function (d) { return d >= start && d <= end; }).sort();
      app.innerHTML = U.head("周报 / 月报", '<span class="muted small">按时间段汇总简报，可复制或下载</span>') +
        '<section class="card rpt-ctl"><div class="chips">' + ps.map(function (p) {
          return '<button class="chip' + (p[1] === start && p[2] === end ? " on" : "") + '" data-rp="' + p[1] + "|" + p[2] + '">' + p[0] + "</button>"; }).join("") + "</div>" +
        '<div class="rpt-row"><label>从 <input type="date" id="rpS" value="' + start + '" max="' + last + '"></label>' +
        '<label>到 <input type="date" id="rpE" value="' + end + '" max="' + last + '"></label>' +
        '<label>每类最多 <input type="number" id="rpN" min="1" max="20" value="' + per + '" style="width:56px"> 条</label>' +
        '<button class="btn" id="rpGo">生成</button></div>' +
        '<div class="rpt-row"><button class="btn" id="rpCopy" disabled>复制文字</button> <button class="btn" id="rpMd" disabled>下载 Markdown</button> ' +
        '<button class="btn" id="rpDoc" disabled>下载 Word</button> <span class="muted small">Word 版为简化格式，可在 Word 里继续编辑、另存为 docx</span></div></section>' +
        '<section class="card report" id="rpOut"><p class="muted">' + (dates.length ? "正在读取 " + dates.length + " 期简报…" : "这段时间没有简报（数据从 " + (idx && idx.days.length ? idx.days[idx.days.length - 1].date : "—") + " 开始）。") + "</p></section>";
      app.querySelectorAll("[data-rp]").forEach(function (b) { b.onclick = function () { var p = b.dataset.rp.split("|"); go(["report", p[0], p[1], document.getElementById("rpN").value]); }; });
      document.getElementById("rpGo").onclick = function () { go(["report", document.getElementById("rpS").value, document.getElementById("rpE").value, document.getElementById("rpN").value]); };
      if (!dates.length) return;
      var got = {}, n = 0;
      dates.forEach(function (dt) {
        U.getDay(dt, function (d) {
          got[dt] = d; n++;
          if (n < dates.length) return;
          U.getExtra("indicators", function (ind) {
            var days = dates.map(function (x) { return got[x]; }).filter(Boolean);
            var B = buildReport(days, (ind && ind.indicators) || [], start, end, per);
            var out = document.getElementById("rpOut"); if (!out) return;
            out.innerHTML = toHtml(B);
            var name = B.title.replace(/[（）\s]/g, "_").replace(/_+$/, "");
            var en = function (id, f) { var b = document.getElementById(id); b.disabled = false; b.onclick = f; };
            en("rpCopy", function () { U.copyText(toText(B, false), B.title); });
            en("rpMd", function () { download(name + ".md", toText(B, true), "text/markdown;charset=utf-8"); });
            en("rpDoc", function () { download(name + ".doc", toWord(B), "application/msword;charset=utf-8"); });
          });
        });
      });
    });
  }

  // ======================= 关注 =======================
  function renderWatch() {
    U.getIndex(function (idx) {
      watchlist(function (wl) {
        var last = latestDate(idx), from = addDays(last, -29);
        var rs = rows(idx).filter(function (r) { return r.date >= from; });
        var rich = rs.some(function (r) { return r.rich; });
        var g = {};
        rs.forEach(function (r) { r.watch.forEach(function (w) { (g[w] = g[w] || []).push(r); }); });
        var words = Object.keys(g).sort(function (a, b) { return g[b].length - g[a].length; });
        var none = wl.filter(function (w) { return !g[w]; });
        app.innerHTML = U.head("关注", '<span class="muted small">' + md(from) + " 至 " + md(last) + " · 命中 " + words.reduce(function (n, w) { return n + g[w].length; }, 0) + ' 次</span> <a class="btn sm" href="#/settings">修改关注清单</a>') +
          (rich ? "" : '<p class="note">现有数据还没有“关注命中”信息，下一次更新简报后自动补齐。</p>') +
          (words.length ? '<section class="card"><div class="chips">' + words.map(function (w) {
            return '<a class="chip" href="#w-' + encodeURIComponent(w) + '" data-jump="' + esc(w) + '">' + esc(w) + " " + g[w].length + "</a>"; }).join("") + "</div>" +
            (none.length ? '<p class="small muted" style="margin:6px 0 0">近 30 天没有命中：' + esc(none.join("、")) + "</p>" : "") + "</section>" : "") +
          words.map(function (w) {
            return '<section class="card" id="w-' + esc(w) + '"><h2>' + esc(w) + ' <span class="muted small">' + g[w].length + ' 条</span> <a class="small" href="#/search/' + encodeURIComponent(w) + '">看趋势 ›</a></h2>' +
              g[w].map(function (r) { return '<a class="list-row" href="#/d/' + r.date + "/" + esc(r.id) + '"><b>' + esc(r.title) + '</b><span class="muted small">' + md(r.date) + " · " + esc(r.cat) + (r.origin ? " · " + esc(r.origin) : "") + "</span></a>"; }).join("") + "</section>";
          }).join("") + (words.length || !rich ? "" : '<p class="card muted">近 30 天没有命中关注清单的新闻。</p>');
        app.querySelectorAll("[data-jump]").forEach(function (a) {
          a.onclick = function (e) { e.preventDefault(); var el = document.getElementById("w-" + a.dataset.jump); if (el) el.scrollIntoView({ behavior: "smooth" }); };
        });
      });
    });
  }

  // ======================= 历史检索 + 趋势 =======================
  var RANGES = [["7", "近 7 天"], ["30", "近 30 天"], ["90", "近 90 天"], ["all", "全部日期"]];
  function trendSvg(bins, width) {
    var W = width, H = 190, L = 34, R = 8, T = 22, Bm = 30, n = bins.length;
    var mx = Math.max.apply(null, bins.map(function (b) { return b[1]; }).concat([1]));
    var step = mx <= 5 ? 1 : Math.ceil(mx / 4);
    var top = Math.ceil(mx / step) * step, ih = H - T - Bm, bw = (W - L - R) / n;
    var y = function (v) { return T + ih - v / top * ih; };
    var s = ['<svg class="trend" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="每周条数">'];
    s.push('<text x="' + 2 + '" y="12" class="tx">条</text>');
    for (var v = 0; v <= top; v += step) {
      s.push('<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '" class="gl"/>');
      s.push('<text x="' + (L - 6) + '" y="' + (y(v) + 4) + '" class="tx" text-anchor="end">' + v + "</text>");
    }
    var every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((W - L) / 56))));
    bins.forEach(function (b, i) {
      var x = L + i * bw, h = y(0) - y(b[1]);
      if (b[1]) s.push('<rect x="' + (x + bw * 0.15) + '" y="' + y(b[1]) + '" width="' + Math.max(2, bw * 0.7) + '" height="' + h + '" class="bar"><title>' + b[0] + " 那周：" + b[1] + " 条</title></rect>");
      if (i % every === 0 || i === n - 1) s.push('<text x="' + (x + bw / 2) + '" y="' + (H - 10) + '" class="tx" text-anchor="middle">' + md(b[0]) + "</text>");
    });
    s.push("</svg>");
    return s.join("");
  }

  function renderSearch2(args) {
    var q = (args[0] || "").trim(), range = args[1] || "all", cat = args[2] || "", src = args[3] || "";
    var inp = document.getElementById("searchInput"); if (inp && q) inp.value = q;
    U.getIndex(function (idx) {
      watchlist(function (wl) {
        var last = latestDate(idx), all = rows(idx);
        var first = all.length ? all[all.length - 1].date : last;
        var from = range === "all" ? first : addDays(last, -(parseInt(range, 10) - 1));
        var ql = q.toLowerCase();
        var hit = q ? all.filter(function (r) { return r.date >= from && (r.title + " " + r.sum).toLowerCase().indexOf(ql) >= 0; }) : [];
        var srcCount = {}; hit.forEach(function (r) { if (r.origin) srcCount[r.origin] = (srcCount[r.origin] || 0) + 1; });
        var srcs = Object.keys(srcCount).sort(function (a, b) { return srcCount[b] - srcCount[a]; }).slice(0, 40);
        var res = hit.filter(function (r) { return (!cat || r.cat === cat) && (!src || r.origin === src); });
        var sel = function (id, val, opts) { return '<select id="' + id + '">' + opts.map(function (o) { return '<option value="' + esc(o[0]) + '"' + (o[0] === val ? " selected" : "") + ">" + esc(o[1]) + "</option>"; }).join("") + "</select>"; };
        var hl = function (s) { return q ? esc(s).split(esc(q)).join("<mark>" + esc(q) + "</mark>") : esc(s); };
        var chart = "", stat = "";
        if (q && res.length) {
          var bins = [], cnt = {};
          res.forEach(function (r) { var w = weekStart(r.date); cnt[w] = (cnt[w] || 0) + 1; });
          for (var w = weekStart(from); w <= weekStart(last); w = addDays(w, 7)) bins.push([w, cnt[w] || 0]);
          var peak = bins.reduce(function (a, b) { return b[1] > a[1] ? b : a; }, bins[0]);
          var width = Math.max(280, Math.min(760, (app.clientWidth || 760) - 34));
          chart = trendSvg(bins, width);
          stat = '<p class="small muted" style="margin:4px 0 0">按周统计（每周从周一算起）：峰值是 ' + md(peak[0]) + " 那周 " + peak[1] + " 条；最近一周（" + md(bins[bins.length - 1][0]) + " 起）" + bins[bins.length - 1][1] + " 条；合计 " + res.length + " 条。</p>";
        }
        app.innerHTML = U.head(q ? "搜索“" + esc(q) + "”" : "历史检索", q ? '<span class="muted small">' + res.length + " 条</span>" : "") +
          '<section class="card"><div class="rpt-row">' + sel("sRange", range, RANGES) +
          sel("sCat", cat, [["", "全部类别"]].concat(CATS.map(function (c) { return [c, c]; }))) +
          sel("sSrc", src, [["", "全部来源"]].concat(srcs.map(function (s) { return [s, s + "（" + srcCount[s] + "）"]; }))) + "</div>" +
          (wl.length ? '<div class="chips wrapchips"><span class="muted small">关注词</span>' + wl.map(function (w) {
            return '<a class="chip' + (w === q ? " on" : "") + '" href="#/search/' + encodeURIComponent(w) + "/" + range + '">' + esc(w) + "</a>"; }).join("") + "</div>" : "") +
          (q ? "" : '<p class="muted small">在页面顶部搜索框输入关键词（例如“容量电价”“虚拟电厂”），或点上面的关注词。</p>') + "</section>" +
          (chart ? '<section class="card"><h2>每周出现次数</h2><div class="trendwrap">' + chart + "</div>" + stat + "</section>" : "") +
          (q ? '<section class="card">' + (res.slice(0, 200).map(function (r) {
            return '<a class="list-row" href="#/d/' + r.date + "/" + esc(r.id) + '"><b>' + hl(r.title) + '</b><span class="muted small">' + r.date + " · " + esc(r.cat) + (r.origin ? " · " + esc(r.origin) : "") + (r.sum ? " · " + hl(r.sum) : "") + "</span></a>";
          }).join("") || '<p class="muted">没有找到</p>') + (res.length > 200 ? '<p class="muted small">只显示最近 200 条</p>' : "") + "</section>" : "");
        var upd = function () { go(["search", q, document.getElementById("sRange").value, document.getElementById("sCat").value, document.getElementById("sSrc").value]); };
        ["sRange", "sCat", "sSrc"].forEach(function (id) { document.getElementById(id).onchange = upd; });
      });
    });
  }

  // 注册路由（manage.js 会整体重设 PBRoutes，所以本文件在它之后加载并合并）
  window.PBRoutes = window.PBRoutes || {};
  window.PBRoutes.report = function (a) { renderReport(a.map(decodeURIComponent)); };
  window.PBRoutes.watch = function () { renderWatch(); };
  window.PBRoutes.search = function (a) { U.setTab(""); renderSearch2(a.map(decodeURIComponent)); };
  // app.js 先于本文件路由过一次：直接打开这些网址时在这里补一次
  if (/^#\/?(report|watch|search)(\/|$)/.test(location.hash)) U.route();
})();
