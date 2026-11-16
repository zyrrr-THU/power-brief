"""上市公司公告（巨潮资讯）：关注股票的近期公告 + 全市场能源关键词公告（覆盖中小企业）。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .util import http, log, short_hash

QUERY = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
SEARCH = "http://www.cninfo.com.cn/new/fulltextSearch/full"
PDF = "http://static.cninfo.com.cn/"

IMPORTANT = ("业绩", "利润", "营收", "中标", "合同", "投资", "收购", "并购", "出售", "核准", "投产", "并网", "开工",
             "增持", "减持", "回购", "定增", "发行", "分红", "签署", "协议", "项目", "电站", "装机", "发电量", "电价",
             "补贴", "重大", "战略", "合作", "设立", "处罚", "诉讼", "停产", "事故")
ROUTINE = ("法律意见", "独立董事", "董事会决议", "监事会决议", "股东会", "股东大会", "会议通知", "提示性公告",
           "核查意见", "保荐", "持续督导", "章程", "制度", "证券变动月报", "翌日披露", "高级管理人员变更",
           "工商变更", "募集资金", "担保", "关联交易", "授信", "可转债", "可交换", "权益变动", "质押", "解除",
           "前十大股东", "前十名股东", "持股情况", "持股信息", "已回购股份", "回购进展", "海外监管公告", "债券发行",
           "超短期融资券", "中期票据", "付息", "兑付")
ENERGY = ("电力", "电站", "电网", "储能", "光伏", "风电", "风电场", "核电", "氢能", "煤", "新能源", "售电", "发电",
          "能源", "充电", "换电", "电池", "特高压", "输变电", "电价")


def _clean(t):
    return re.sub(r"</?em>", "", t or "").strip()


def classify(title):
    """返回 'important' / 'routine' / 'other'。"""
    if any(k in title for k in ROUTINE):
        return "routine"
    if any(k in title for k in IMPORTANT):
        return "important"
    return "other"


def _row(a, origin):
    title = _clean(a.get("announcementTitle"))
    name = _clean(a.get("secName"))
    if title.startswith(name + "："):
        title = title[len(name) + 1:]
    ts = a.get("announcementTime")
    pub = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat() if ts else None
    return {"id": short_hash(a.get("adjunctUrl") or title), "code": a.get("secCode", ""), "name": name,
            "title": title, "url": PDF + (a.get("adjunctUrl") or ""), "published": pub, "origin": origin,
            "level": classify(title)}


def _stock_param(code):
    """sh600900 → 600900,gssh0600900；sz003816 → 003816,gssz0003816；hk00836 → 00836,gshk0000836"""
    m, num = code[:2], code[2:]
    org = {"sh": f"gssh0{num}", "sz": f"gssz0{num}", "hk": f"gshk00{num}"}[m]
    col = {"sh": "sse", "sz": "szse", "hk": "hke"}[m]
    return f"{num},{org}", col


def fetch_watch(stocks, days, sess):
    end = datetime.now(timezone(timedelta(hours=8))).date()
    se = f"{end - timedelta(days=days)}~{end}"
    out = []
    for s in stocks:
        try:
            stock, col = _stock_param(s["code"])
            d = sess.post(QUERY, timeout=15, data={
                "pageNum": 1, "pageSize": 30, "column": col, "tabName": "fulltext", "stock": stock,
                "searchkey": "", "seDate": se, "isHLtitle": "true"},
                headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}).json()
            for a in d.get("announcements") or []:
                r = _row(a, "关注股票")
                r["stock"] = s["code"]
                out.append(r)
        except Exception as e:  # noqa: BLE001
            log.debug("公告查询失败 %s: %s", s["code"], e)
    return out


def fetch_keywords(keywords, days, sess):
    end = datetime.now(timezone(timedelta(hours=8))).date()
    out = []
    for kw in keywords:
        try:
            d = sess.get(SEARCH, timeout=15, params={
                "searchkey": kw, "sdate": str(end - timedelta(days=days)), "edate": str(end),
                "isfulltext": "false", "sortName": "pubdate", "sortType": "desc", "pageNum": 1, "pageSize": 30}).json()
            for a in d.get("announcements") or []:
                code = a.get("secCode", "")
                if code[:2] in ("15", "16", "50", "51", "52", "56", "58"):  # 基金/ETF
                    continue
                out.append(_row(a, f"关键词·{kw}"))
        except Exception as e:  # noqa: BLE001
            log.debug("公告关键词失败 %s: %s", kw, e)
    return out


def fetch_announcements(stocks_conf):
    conf = stocks_conf.get("announcements", {}) or {}
    if conf.get("enabled", True) is False:
        return [], 0
    days = int(conf.get("days", 2))
    sess = http()
    watch = fetch_watch(stocks_conf.get("stocks", []), days, sess)
    kws = fetch_keywords(conf.get("keywords", ["储能", "光伏", "风电", "电站", "核电", "售电", "虚拟电厂", "氢能", "电网"]),
                         days, sess)
    seen, rows = set(), []
    for r in watch + kws:
        if r["id"] in seen or r["level"] == "routine":
            continue
        if r["origin"] != "关注股票":
            # 全市场公告需同时和能源相关且属于重要事项
            if r["level"] != "important" or not any(k in r["title"] + r["name"] for k in ENERGY):
                continue
        seen.add(r["id"])
        rows.append(r)
    # 重要事项优先、关注股票优先，同层级内按时间倒序
    rows.sort(key=lambda r: r["published"] or "", reverse=True)
    rows.sort(key=lambda r: (r["level"] != "important", r["origin"] != "关注股票"))
    limit = int(conf.get("max_items", 12))
    log.info("公告：关注股票 %d 条、关键词 %d 条，保留 %d 条", len(watch), len(kws), min(limit, len(rows)))
    return rows[:limit], len(watch) + len(kws)
