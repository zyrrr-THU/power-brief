"""离线自测（不联网、不推送）：python tests/test_offline.py

覆盖：AI 返回解析、AI 失败降级、OpenAI 兼容接口请求格式（本地假服务器）、
推送文本长度限制、旧数据缺字段兼容、同日重跑去重逻辑。
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date  # noqa: E402

from powerbrief import announce, article, feedback, indicators, llm, notify, process, render, status, summarize, topics, usage, util  # noqa: E402,E501
from powerbrief.util import load_yaml  # noqa: E402

# 自测只用代码里的默认配置：不读仓库里网页保存的 settings.json（例如网页上关掉了 AI，会让 AI 相关自测误报失败）
util.SETTINGS_FILE = Path(__file__).resolve().parent / "_no_settings_for_tests.json"

CFG = load_yaml("config.yaml")
GLOSS = load_yaml("glossary.yaml")["terms"]


def fake_items(n=30):
    import random
    rnd = random.Random(1)
    words = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥东南西北山川河海"
    items = []
    for i in range(n):
        uniq = "".join(rnd.choice(words) for _ in range(12))  # 标题互不相似，避免被合并
        items.append({"title": f"{uniq}电力现货市场", "url": f"https://example.com/{i}",
                      "source": "测试", "origin": "测试源", "tier": 2, "lang": "zh", "published": None,
                      "snippet": "这是一段摘录" * 5})
    return process.enrich(process.cluster(items), CFG)


def test_parse_json():
    txt = '好的\n```json\n{"highlights":["a"],"items":[{"i":0}]}\n```'
    assert summarize.parse_json(txt)["items"][0]["i"] == 0


def test_ai_mode_merge(monkeypatch_chain):
    cands = fake_items()
    reply = {"highlights": ["一", "二", "三"],
             "items": [{"i": 3, "importance": 5, "category": "市场与电价", "summary": "摘要", "why": "影响",
                        "terms": [{"term": "现货", "explain": "解释"}]},
                       {"i": 999, "importance": 5}],  # 越界编号应被忽略
             "concept": {"term": "容量电价", "explain": "说明"}}
    monkeypatch_chain(lambda *a, **k: (reply, "fake"))
    res = summarize.summarize(cands, CFG, GLOSS, "2026-11-12")
    assert res["mode"] == "ai" and res["provider"] == "fake"
    assert len(res["items"]) == 1 and res["items"][0]["summary"] == "摘要"
    assert res["concept"]["term"] == "容量电价"


def test_fallback_to_rule(monkeypatch_chain):
    monkeypatch_chain(lambda *a, **k: (None, None))
    res = summarize.summarize(fake_items(), CFG, GLOSS, "2026-11-12")
    assert res["mode"] == "rule" and len(res["items"]) > 0
    assert res["items"][0]["terms"], "规则模式应从术语表匹配到术语"


def test_openai_compatible_request():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen["auth"], seen["model"] = self.headers["Authorization"], body["model"]
            out = json.dumps({"choices": [{"message": {"content": '{"items": []}'}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["PB_TEST_KEY"] = "sk-test"
    ai = {"providers": ["missing", "fake"], "provider_settings": {
        "missing": {"type": "openai_compatible", "base_url": "http://x", "model": "m", "api_key_env": "PB_NO_KEY"},
        "fake": {"type": "openai_compatible", "base_url": f"http://127.0.0.1:{srv.server_port}/v1",
                 "model": "deepseek-chat", "api_key_env": "PB_TEST_KEY"}}}
    data, name = llm.run_chain(ai, "sys", "prompt", summarize.parse_json)
    srv.shutdown()
    assert name == "fake" and data == {"items": []}
    assert seen == {"auth": "Bearer sk-test", "model": "deepseek-chat"}


def test_push_length_limits():
    items = fake_items(40)
    for it in items:
        it.update(summary="很长的摘要" * 20, why="解读", terms=[])
    b = {"highlights": ["a", "b", "c"], "items": items, "stocks": [], "concept": None, "site_url": "https://x"}
    assert len(notify.build_md(b, compact=True, limit=4000).encode("utf-8")) <= 4000
    assert "完整简报" in notify.build_md(b, compact=True, limit=4000)
    assert notify.build_html(b).count("<p>") >= 40


def test_old_data_compat(tmp_dir):
    old = {"date": "2020-01-01", "items": [{"id": "x", "title": "t", "url": "u"}]}
    (tmp_dir / "2020-01-01.json").write_text(json.dumps(old), encoding="utf-8")
    d = render.load_day("2020-01-01")
    assert d["stocks"] == [] and d["items"][0]["terms"] == [] and d["items"][0]["category"] == "综合"


def test_same_day_rerun_keeps_items():
    it = fake_items(1)[0]
    seen = {}
    for k in (process.short_hash(it["url"]), process.short_hash(it["_norm"])):
        seen[k] = "2026-11-12"
    assert process.drop_seen([it], seen, "2026-11-12") == [it]       # 同一天重跑：保留
    assert process.drop_seen([it], seen, "2026-11-13") == []         # 第二天：去掉


def test_carbon_and_power_regex():
    t = date(2026, 11, 12)
    c = indicators.parse_carbon(["11月12日全国碳市场收盘价92.41元／吨 较前一日上涨2.08% - 中国金融信息网",
                                 "12月30日全国碳市场收盘价80元/吨"], t)
    assert c == {"2026-11-12": 92.41, "2025-12-30": 80.0}, c
    m, cum = indicators.parse_power_use(["国家能源局：2026年1-9月全社会用电量同比增长3.9%",
                                         "10月份全社会用电量同比下降1.2%", "前三季度全社会用电量80734亿千瓦时 同比增长3.9%",
                                         "广东前三季度全社会用电量同比增长7.67%", "江苏省10月全社会用电量同比增长9%"], t)
    assert m == {"2026-10": -1.2} and cum == {"2026-09": 3.9}, (m, cum)


def test_data_points_alias():
    store = {}
    aliases = {"秦皇岛5500动力煤价格": ["秦皇岛5500"]}
    items = [{"title": "煤价周报", "url": "u"}]
    kn = indicators.apply_data_points(store, [{"name": "秦皇岛5500大卡动力煤", "value": "845", "unit": "元/吨", "i": 0},
                                              {"name": "广西现货均价", "value": "x"}], aliases, "2026-11-12", items)
    assert store["秦皇岛5500动力煤价格"]["points"] == {"2026-11-12": 845.0}
    assert len(kn) == 1 and kn[0]["url"] == "u"
    s = indicators.summary(store)
    assert s[0]["value"] == 845.0 and s[0]["change"] is None


def test_announcement_classify():
    assert announce.classify("关于新能源换电站建设业务中标暨签署协议的公告") == "important"
    assert announce.classify("关于回购股份事项前十大股东持股情况的公告") == "routine"
    assert announce.classify("2026年第二次临时股东会决议公告") == "routine"
    assert announce._stock_param("hk00836") == ("00836,gshk0000836", "hke")


def test_topics_promote_and_annotate():
    st = {"topics": {}, "candidates": {}}
    known = {"容量电价": ["容量电价"]}
    for i, d in enumerate(["2026-11-01", "2026-11-05", "2026-11-10"]):
        its = [{"id": f"a{i}", "title": "某省容量电价", "url": "u", "topics": ["容量电价", "绿氢管道"]}]
        topics.update(st, its, d, set(known))
    assert len(st["topics"]["容量电价"]["entries"]) == 3
    assert st["topics"]["绿氢管道"]["auto"] is True          # 14 天内 3 次，自动升格
    its = [{"id": "z", "title": "t", "url": "u", "topics": ["容量电价"]}]
    topics.annotate(its, st, "2026-11-12")
    assert its[0]["topic_info"][0] == {"name": "容量电价", "prior": 3, "last": "2026-11-10"}
    tagged = [{"title": "全国碳市场成交量破10亿吨", "summary": ""}]
    topics.tag(tagged, {"全国碳市场": ["碳市场"], "绿证绿电": ["绿证"]})
    assert tagged[0]["topics"] == ["全国碳市场"]


def test_feedback_weights(tmp_dir):
    feedback.VOTES, feedback.WEIGHTS, feedback.INBOX = tmp_dir / "fb.json", tmp_dir / "w.json", tmp_dir / "inbox"
    feedback.INBOX.mkdir(exist_ok=True)
    votes = [{"id": str(i), "v": 1, "origin": "国家能源局", "category": "政策法规", "title": "t"} for i in range(10)]
    votes.append({"id": "x", "v": -1, "origin": "Sohu", "category": "综合", "watch": ["华能"], "title": "软文"})
    (feedback.INBOX / "a.json").write_text(json.dumps({"votes": votes}), encoding="utf-8")
    assert feedback.collect({}) == 1
    w = feedback.load_weights()
    assert w["origin"]["国家能源局"] == 3.0                   # 10 票 × 0.5 被限制在 +3
    assert w["origin"]["Sohu"] == -0.5 and w["watch"]["华能"] == -0.5
    it = {"origin": "Sohu", "category": "综合", "watch_hit": ["华能"]}
    assert feedback.bonus(it, w) == -1.5
    assert "软文" in feedback.prompt_hint(w)
    (feedback.INBOX / "b.json").write_text(json.dumps({"reset": True, "votes": []}), encoding="utf-8")
    feedback.collect({})
    assert feedback.load_weights()["count"] == 0


def test_decode_fallback():
    assert article.decode_gnews("https://www.nea.gov.cn/x.html") == "https://www.nea.gov.cn/x.html"

    class FakeSess:
        def get(self, *a, **k):
            class R:
                text = "<html>no signature</html>"
            return R()
    assert article.decode_gnews("https://news.google.com/rss/articles/ABC?oc=5", FakeSess()) is None


def test_alert_and_new_sections():
    assert notify.build_html({"alert": "出错了"}) == "<p>出错了</p>"
    b = {"highlights": ["a"], "items": [], "stocks": [], "concept": None, "site_url": "",
         "policy": [{"policy_type": "征求意见", "title": "某细则", "url": "u", "deadline": "2026-12-01", "origin": "o"}],
         "indicators": [{"name": "碳价", "value": 92.41, "unit": "元/吨", "change": -1.5, "date": "2026-11-12"}],
         "announcements": [{"name": "华能国际", "title": "中标公告", "url": "p"}], "notes": ["AI 不可用"]}
    h = notify.build_html(b)
    assert "政策雷达" in h and "截止 2026-12-01" in h and "碳价 92.41元/吨（-1.5）" in h and "运行提示" in h
    assert "公告" in notify.build_md(b, compact=True)


def test_usage_record_and_report(tmp_dir):
    usage.FILE = tmp_dir / "usage.json"
    conf = {"type": "claude_cli", "model": "sonnet"}
    usage.record({}, "claude_cli", conf, "daily", {"model": "claude-sonnet-5-5", "input": 8000, "output": 6000,
                                                    "cache_read": 0, "cache_write": 0, "cost_usd": 0.076}, True, 30, 9000)
    usage.record({}, "deepseek", {"type": "openai_compatible", "model": "deepseek-chat"}, "daily",
                 {"model": "deepseek-chat", "input": 1_000_000, "output": 0}, True, 5, 9000)
    usage.record({}, "claude", {"type": "anthropic"}, "daily", None, False, 1, 9000)
    rep = usage.report({"usage": {"plan": "pro"}})
    day = rep["days"][-1]
    assert day["calls"] == 3 and day["failed"] == 1 and day["total"] == 1_014_000
    assert abs(day["cost_usd"] - (0.076 + 0.27)) < 1e-6           # Claude 用返回值，DeepSeek 按价目表估算
    assert rep["plan_fee_usd"] == 20 and rep["plan_share_pct"] == round(day["cost_usd"] * 30 / 20 * 100, 1)
    assert usage.estimate_cost({"model": "sonnet", "input": 1_000_000, "output": 1_000_000}) == 12.0


def test_settings_overlay(tmp_dir):
    """网页保存的 settings.json 覆盖默认值：字典逐键合并、列表整体替换、类型不对或文件损坏时忽略。"""
    orig = util.SETTINGS_FILE
    try:
        util.SETTINGS_FILE = tmp_dir / "settings.json"
        base = util.load_yaml("config.yaml", overlay=False)
        assert util.load_yaml("config.yaml") == base                       # 没有 settings.json：等于默认值
        util.write_json(util.SETTINGS_FILE, {
            "config": {"watchlist": ["测试词"], "run": {"max_items": 9}, "ai": {"provider_settings": {"deepseek": {"model": "x"}}},
                       "notify": "错误类型"},
            "stocks": {"alert_pct": 3}})
        c = util.load_yaml("config.yaml")
        assert c["watchlist"] == ["测试词"]                                 # 列表整体替换
        assert c["run"]["max_items"] == 9 and c["run"]["lookback_hours"] == base["run"]["lookback_hours"]  # 字典逐键
        assert c["ai"]["provider_settings"]["deepseek"]["model"] == "x"
        assert c["ai"]["provider_settings"]["deepseek"]["base_url"] == base["ai"]["provider_settings"]["deepseek"]["base_url"]
        assert c["notify"] == base["notify"]                               # 类型不对：保留默认
        assert util.load_yaml("stocks.yaml")["alert_pct"] == 3
        assert util.load_yaml("glossary.yaml") == util.load_yaml("glossary.yaml", overlay=False)  # 术语表不受影响
        util.SETTINGS_FILE.write_text("{坏的 json", encoding="utf-8")
        assert util.load_yaml("config.yaml") == base                       # 文件损坏：当作没有改动
    finally:
        util.SETTINGS_FILE = orig


def test_status_export_no_secret_values(tmp_dir):
    """网页设置页只能看到密钥“是否已配置”，不能出现密钥内容；运行记录正确导出。"""
    orig = (render.DATA, status.RUNLOG)
    secret = "sk-SECRET-should-not-leak-123"
    os.environ["DEEPSEEK_API_KEY"] = secret
    os.environ.pop("PUSHPLUS_TOKEN", None)
    try:
        render.DATA = tmp_dir / "data"
        status.RUNLOG = tmp_dir / "runlog.json"
        for i in range(35):
            status.record_run({"date": "2026-11-16", "ok": i != 34, "items": i, "error": "" if i != 34 else "Boom"})
        obj = status.export_settings()
        text = (render.DATA / "settings.js").read_text(encoding="utf-8")
        assert text.startswith("PB.onExtra_settings(")
        assert secret not in text and secret not in json.dumps(obj, ensure_ascii=False)
        assert obj["secrets"]["DEEPSEEK_API_KEY"] is True and obj["secrets"]["PUSHPLUS_TOKEN"] is False
        assert obj["defaults"]["config"]["run"]["mode"] == "github"
        rl = json.loads((render.DATA / "runlog.json").read_text(encoding="utf-8"))
        assert len(rl["runs"]) == status.SHOW_RUNS and rl["runs"][0]["error"] == "Boom"   # 最新的在前
        assert len(json.loads(status.RUNLOG.read_text(encoding="utf-8"))) == status.KEEP_RUNS
        assert obj["last_run"]["ok"] is False
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)
        render.DATA, status.RUNLOG = orig


def test_scheduled_skip_rule(tmp_dir):
    """多个定时时段：今天已有成功的定时运行才跳过；只有网页手动运行、失败的定时运行、昨天的定时运行都不跳过。"""
    from powerbrief import main
    orig = status.RUNLOG
    try:
        status.RUNLOG = tmp_dir / "runlog_skip.json"
        today = "2026-11-17"
        cases = [
            ([], False),
            ([{"date": today, "ok": True, "trigger": "dispatch"}], False),
            ([{"date": today, "ok": False, "trigger": "schedule"}], False),
            ([{"date": "2026-11-16", "ok": True, "trigger": "schedule"}], False),
            ([{"date": today, "ok": True, "trigger": "dispatch"}, {"date": today, "ok": True, "trigger": "schedule"}], True),
        ]
        for runs, want in cases:
            util.write_json(status.RUNLOG, runs)
            assert main.scheduled_done(today) is want, (runs, want)
    finally:
        status.RUNLOG = orig


def test_announce_parallel_same_as_serial():
    """公告并发查询后结果与逐个查询一致（顺序也一致）；单个查询失败不影响其他。"""
    import time

    class Resp:
        def __init__(self, d):
            self.d = d

        def json(self):
            return self.d

    def ann(i, tag):
        return {"announcementId": f"{tag}{i}", "announcementTitle": f"{tag}公告{i}", "secName": "测试", "secCode": "600000",
                "announcementTime": 1763300000000, "adjunctUrl": f"x/{tag}{i}.pdf"}

    class Sess:
        def post(self, url, data=None, **kw):
            time.sleep(0.05)
            code = data["stock"].split(",")[0]
            if code == "000002":
                raise RuntimeError("模拟超时")
            return Resp({"announcements": [ann(1, code), ann(2, code)]})

        def get(self, url, params=None, **kw):
            time.sleep(0.05)
            return Resp({"announcements": [ann(1, params["searchkey"])]})

    stocks = [{"code": c} for c in ("sh600900", "sz000002", "sh601985", "sz300750", "sh600011", "sz003816")]
    t = time.time()
    par = announce.fetch_watch(stocks, 2, Sess())
    took = time.time() - t
    old = announce.WORKERS
    try:
        announce.WORKERS = 1
        ser = announce.fetch_watch(stocks, 2, Sess())
    finally:
        announce.WORKERS = old
    assert [r["id"] for r in par] == [r["id"] for r in ser] and len(par) == 10   # 失败的那只不影响其他 5 只
    assert took < 0.25, took                                                   # 6 次 × 0.05 秒，并发后明显更快
    kws = announce.fetch_keywords(["储能", "光伏", "核电"], 2, Sess())
    assert [r["origin"] for r in kws] == ["关键词·储能", "关键词·光伏", "关键词·核电"]


def test_index_rows_extended(tmp_dir):
    """索引每条为 [id, 标题, 类别, 摘要, 来源, 关注命中, 分数]；旧数据缺字段时用空值，不报错。"""
    orig = render.DATA
    try:
        render.DATA = tmp_dir / "idx22"
        render.DATA.mkdir(parents=True, exist_ok=True)
        util.write_json(render.DATA / "2026-11-15.json", {"date": "2026-11-15", "items": [
            {"id": "a", "title": "旧条目", "category": "综合"}]})
        util.write_json(render.DATA / "2026-11-16.json", {"date": "2026-11-16", "items": [
            {"id": "b", "title": "虚拟电厂新规", "category": "政策法规", "summary": "摘要" * 40, "origin": "能源局",
             "watch_hit": ["虚拟电厂"], "score": 9.87}]})
        render.rebuild_index()
        idx = json.loads((render.DATA / "index.json").read_text(encoding="utf-8"))
        new, old = idx["days"][0]["items"][0], idx["days"][1]["items"][0]
        assert new == ["b", "虚拟电厂新规", "政策法规", ("摘要" * 40)[:60], "能源局", ["虚拟电厂"], 9.9]
        assert old == ["a", "旧条目", "综合", "", "", [], 0.0]
        assert "onIndex(" in (render.DATA / "index.js").read_text(encoding="utf-8")
    finally:
        render.DATA = orig


def test_push_watch_section():
    """推送开头单独列出“你关注的”；没有命中时不出现这一段。"""
    def brief(hit):
        return {"highlights": ["要点一"], "items": [
            {"title": "国家电网发布新规", "url": "https://e.com/1", "category": "政策法规", "origin": "测试",
             "watch_hit": ["国家电网"] if hit else []},
            {"title": "其他新闻", "url": "https://e.com/2", "category": "综合", "origin": "测试", "watch_hit": []}]}
    b = brief(True)
    html_ = notify.build_html(b)
    assert "你关注的（1 条）" in html_ and html_.index("你关注的") < html_.index("政策法规")
    assert "国家电网：[国家电网发布新规](https://e.com/1)" in notify.build_md(b)
    assert "★ 关注 1 条" in notify.build_text(b)
    nb = brief(False)
    assert "你关注的" not in notify.build_html(nb) and "你关注的" not in notify.build_md(nb) and "关注" not in notify.build_text(nb)


def test_domestic_sources_in_cloud():
    """云端版包含中国电力新闻网 8 个频道，均为列表页抓取并限定链接范围。"""
    src = [s for s in load_yaml("sources.yaml")["sources"] if s["name"].startswith("中电新闻·")]
    assert len(src) == 8
    assert all(s["type"] == "html_list" and s["url"].startswith("https://www.cpnn.com.cn/news/")
               and s["link_contains"].startswith("cpnn.com.cn/news/") and "domestic" not in s for s in src)


def test_alerts_real_failures_only(tmp_dir):
    """在线误报复现：抓到了但都被过滤（保留 0）不报；搜索类 0 条不报；连续 3 天失败、列表页 0 条才报。"""
    orig = render.DATA
    try:
        render.DATA = tmp_dir / "alerts221"
        render.DATA.mkdir(parents=True, exist_ok=True)
        stats = {"生态环境部": 0, "政策·内蒙古": 0, "坏来源": -1, "空列表": 0}
        raw = {"生态环境部": 6, "空列表": 0}          # 搜索类（政策·内蒙古）不记录原始条数
        for d in ("2026-11-21", "2026-11-22"):
            util.write_json(render.DATA / f"{d}.json", {"date": d, "items": [], "source_stats": stats, "source_raw": raw})
        assert sorted(render.source_alerts("2026-11-23", stats, raw=raw)) == ["坏来源", "空列表"]
        # 升级前的旧数据没有 source_raw：保留 0 的不算故障，误报立即消失
        for d in ("2026-11-21", "2026-11-22"):
            util.write_json(render.DATA / f"{d}.json", {"date": d, "items": [], "source_stats": {"生态环境部": 0, "坏来源": -1}})
        assert render.source_alerts("2026-11-23", {"生态环境部": 0, "坏来源": -1}, raw={"生态环境部": 6}) == ["坏来源"]
    finally:
        render.DATA = orig


def test_monday_lookback():
    """周一回看延长到 72 小时覆盖周末；其他日子不变；配置为 0 不延长；平时已超过 72 小时的不缩短。"""
    from powerbrief import main as m
    cfg = {"run": {"lookback_hours": 24, "monday_lookback_hours": 72}}
    assert m.monday_lookback(cfg, "2026-11-23") == 72 and cfg["run"]["lookback_hours"] == 72
    cfg = {"run": {"lookback_hours": 24, "monday_lookback_hours": 72}}
    assert m.monday_lookback(cfg, "2026-11-24") == 24
    cfg = {"run": {"lookback_hours": 24, "monday_lookback_hours": 0}}
    assert m.monday_lookback(cfg, "2026-11-23") == 24
    cfg = {"run": {"lookback_hours": 96}}
    assert m.monday_lookback(cfg, "2026-11-23") == 96
    assert load_yaml("config.yaml", overlay=False)["run"]["monday_lookback_hours"] == 72


def test_source_alerts_ignore_filtered(tmp_dir):
    """抓到了但全被“电力相关”过滤掉（保留 0 条）不算故障；真失败（-1）或网页 0 条才提醒；被跳过的来源不提醒。"""
    orig = render.DATA
    try:
        render.DATA = tmp_dir / "alerts"
        render.DATA.mkdir(parents=True, exist_ok=True)
        for d in ("2026-11-14", "2026-11-15"):
            util.write_json(render.DATA / f"{d}.json", {"date": d, "items": [],
                            "source_stats": {"发改委": 0, "坏来源": -1, "空页面": 0, "Google": -1},
                            "source_raw": {"发改委": 25, "空页面": 0}})
        stats = {"发改委": 0, "坏来源": -1, "空页面": 0}
        raw = {"发改委": 25, "空页面": 0}
        assert sorted(render.source_alerts("2026-11-16", stats, raw=raw)) == ["坏来源", "空页面"]
        # 旧数据没有 source_raw：只把失败算作故障
        for d in ("2026-11-14", "2026-11-15"):
            util.write_json(render.DATA / f"{d}.json", {"date": d, "items": [], "source_stats": {"发改委": 0, "坏来源": -1}})
        assert render.source_alerts("2026-11-16", {"发改委": 0, "坏来源": -1}, raw={"发改委": 25}) == ["坏来源"]
    finally:
        render.DATA = orig


if __name__ == "__main__":
    import tempfile

    orig_chain = summarize.run_chain

    def patch(fn):
        summarize.run_chain = fn

    tmp = Path(tempfile.mkdtemp())
    orig_data = render.DATA
    orig_fb = (feedback.VOTES, feedback.WEIGHTS, feedback.INBOX)
    os.chdir(Path(__file__).resolve().parent.parent)
    usage.FILE = tmp / "usage_all.json"   # 自测不写入真实用量记录
    tests = [
        (test_alerts_real_failures_only, (tmp,)), (test_monday_lookback, ()),
        (test_source_alerts_ignore_filtered, (tmp,)),
        (test_index_rows_extended, (tmp,)), (test_push_watch_section, ()),
        (test_domestic_sources_in_cloud, ()),
        (test_parse_json, ()), (test_ai_mode_merge, (patch,)), (test_fallback_to_rule, (patch,)),
        (test_openai_compatible_request, ()), (test_push_length_limits, ()),
        (test_old_data_compat, (tmp,)), (test_same_day_rerun_keeps_items, ()),
        (test_carbon_and_power_regex, ()), (test_data_points_alias, ()), (test_announcement_classify, ()),
        (test_topics_promote_and_annotate, ()), (test_feedback_weights, (tmp,)), (test_decode_fallback, ()),
        (test_alert_and_new_sections, ()), (test_usage_record_and_report, (tmp,)),
        (test_settings_overlay, (tmp,)), (test_status_export_no_secret_values, (tmp,)),
        (test_scheduled_skip_rule, (tmp,)), (test_announce_parallel_same_as_serial, ()),
    ]
    failed = 0
    for fn, args in tests:
        render.DATA = tmp if fn is test_old_data_compat else orig_data
        try:
            fn(*args)
            print("PASS", fn.__name__)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("FAIL", fn.__name__, repr(e))
        finally:
            summarize.run_chain = orig_chain
            render.DATA = orig_data
            feedback.VOTES, feedback.WEIGHTS, feedback.INBOX = orig_fb
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    sys.exit(1 if failed else 0)
