"""Parse a creator-center Excel export and strictly match one planned work."""
from __future__ import annotations

import argparse
import json
import re
import math
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl

HEADER_ALIASES = {
    "title": ["作品名称", "名称", "标题"],
    "published_at": ["发布时间", "发布时刻", "时间"],
    "播放量": ["播放量", "播放"],
    "点赞数": ["点赞量", "点赞数", "点赞"],
    "评论数": ["评论量", "评论数", "评论"],
    "分享数": ["分享量", "分享数", "分享"],
    "收藏数": ["收藏量", "收藏数", "收藏"],
    "涨粉数": ["粉丝增量", "涨粉数", "涨粉"],
    "主页访问": ["主页访问量", "主页访问"],
    "平均播放时长（秒）": ["平均播放时长", "平均观看时长"],
    "完播率": ["完播率"],
    "5秒完播率": ["5s完播率", "5秒完播率", "5s完播", "5秒完播"],
    "2秒跳出率": ["2s跳出率", "2秒跳出率", "2s跳出", "2秒跳出", "跳出率"],
    "封面点击率": ["封面点击率", "封面点击"],
}
COUNT_FIELDS = {"播放量", "点赞数", "评论数", "分享数", "收藏数", "涨粉数", "主页访问"}
PERCENT_FIELDS = {"完播率", "5秒完播率", "2秒跳出率", "封面点击率"}
BULK_REQUIRED = {
    "播放量", "点赞数", "评论数", "分享数", "收藏数", "涨粉数",
    "平均播放时长（秒）", "完播率", "5秒完播率", "2秒跳出率",
}


def normalize_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", "", text)
    return text.replace("：", ":").replace("｜", "|")


def parse_datetime(value: Any) -> tuple[datetime | None, bool]:
    if isinstance(value, datetime):
        return value, True
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()), False
    text = str(value or "").strip()
    if not text:
        return None, False
    has_time = bool(re.search(r"\d{1,2}:\d{2}:\d{2}", text))
    text = text.replace("年", "-").replace("月", "-").replace("日", " ").replace("/", "-")
    text = re.sub(r"\s+", " ", text).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%m-%d %H:%M":
                parsed = parsed.replace(year=datetime.now().year)
            return parsed, has_time
        except ValueError:
            continue
    return None, False


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if value is None or str(value).strip() in {"", "-", "--", "None"}:
        return None
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def count(value: Any) -> int | None:
    parsed = number(value)
    if parsed is None or not math.isfinite(parsed) or parsed < 0 or not parsed.is_integer():
        return None
    return int(parsed)


def percent(value: Any) -> float | None:
    if value is None or str(value).strip() in {"", "-", "--", "None"}:
        return None
    raw = str(value).strip()
    had_sign = "%" in raw
    parsed = number(raw.replace("%", ""))
    if parsed is None or parsed < 0:
        return None
    if had_sign or parsed > 1:
        parsed /= 100
    return parsed if 0 <= parsed <= 1 else None


def duration_seconds(value: Any) -> float | None:
    parsed = number(value)
    if parsed is not None:
        return parsed if parsed >= 0 else None
    text = str(value or "").strip()
    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})", text)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    return float(hours * 3600 + int(match.group(2)) * 60 + int(match.group(3)))


def find_columns(headers: list[str]) -> dict[str, int | None]:
    columns: dict[str, int | None] = {}
    for field, aliases in HEADER_ALIASES.items():
        match = None
        exact = [index for index, header in enumerate(headers) if header in aliases]
        if len(exact) > 1:
            raise ValueError('AMBIGUOUS_COLUMN:' + field)
        if exact:
            columns[field] = exact[0]
            continue
        for alias in aliases:
            for index, header in enumerate(headers):
                if re.fullmatch(re.escape(alias) + r'(?:[（(].*[）)])?', header):
                    match = index
                    break
            if match is not None:
                break
        columns[field] = match
    return columns


def serializable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def parse_export(xlsx: Path, plan: dict[str, Any], node_name: str, actual_at: datetime) -> dict[str, Any]:
    if actual_at.tzinfo is None:
        raise ValueError('ACTUAL_TIME_TIMEZONE_REQUIRED')
    if xlsx.stat().st_size > 50 * 1024 * 1024:
        raise ValueError('EXCEL_TOO_LARGE')
    workbook = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    sheet = workbook.active
    try:
        rows = []
        for row in sheet.iter_rows(values_only=True):
            if len(rows) >= 100000:
                raise ValueError('EXCEL_TOO_MANY_ROWS')
            rows.append(row)
    finally:
        workbook.close()
    if not rows:
        raise ValueError("EXCEL_EMPTY")
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    columns = find_columns(headers)
    if columns["title"] is None or columns["published_at"] is None:
        raise ValueError("EXCEL_MISSING_IDENTITY_COLUMNS")

    target_title = normalize_title(plan.get("title"))
    target_published = datetime.fromisoformat(plan["published_at"].replace("Z", "+00:00"))
    matches: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows[1:], start=2):
        if not any(value is not None for value in row):
            continue
        row_title = normalize_title(row[columns["title"]])
        row_published, has_time = parse_datetime(row[columns["published_at"]])
        if not row_title or row_published is None:
            continue
        title_match = row_title == target_title
        if not title_match:
            continue
        if row_published.tzinfo is None:
            row_published = row_published.replace(tzinfo=target_published.tzinfo)
        if has_time:
            publish_match = abs((row_published - target_published).total_seconds()) < 1
            match_basis = "title+publish_time"
        else:
            publish_match = False
            match_basis = "title+publish_date"
        if publish_match:
            matches.append({
                "row_number": row_number,
                "row": row,
                "title": str(row[columns["title"]] or ""),
                "published_at": row_published,
                "match_basis": match_basis,
            })
    if not matches:
        raise ValueError("TARGET_WORK_NOT_FOUND")
    if len(matches) != 1:
        raise ValueError(f"TARGET_WORK_AMBIGUOUS:{len(matches)}")

    selected = matches[0]
    row = selected["row"]
    metrics: dict[str, Any] = {}
    for field, index in columns.items():
        if field in {"title", "published_at"} or index is None:
            continue
        value = row[index]
        if field in COUNT_FIELDS:
            metrics[field] = count(value)
        elif field in PERCENT_FIELDS:
            metrics[field] = percent(value)
        elif field == "平均播放时长（秒）":
            metrics[field] = duration_seconds(value)

    missing = sorted(field for field in BULK_REQUIRED if metrics.get(field) is None)
    if missing:
        raise ValueError(f"EXCEL_MISSING_REQUIRED_METRICS:{','.join(missing)}")
    for field, value in metrics.items():
        if value is None:
            continue
        if type(value) not in (float, int) or not math.isfinite(value):
            raise ValueError('INVALID_METRIC:' + field)
        if field in PERCENT_FIELDS and not 0 <= value <= 1:
            raise ValueError('INVALID_PERCENT:' + field)
        if field not in PERCENT_FIELDS and value < 0 and field != '涨粉数':
            raise ValueError('NEGATIVE_METRIC:' + field)

    planned_at = next(
        datetime.fromisoformat(item["planned_at"].replace("Z", "+00:00"))
        for item in plan["nodes"]
        if item["node"] == node_name
    )
    if actual_at < planned_at:
        raise ValueError('CAPTURE_BEFORE_PLANNED_TIME')
    lateness_seconds = int((actual_at - planned_at).total_seconds())
    return {
        "ok": True,
        "schema_version": 1,
        "capture_level": "standard_export",
        "work_id": plan["work_id"],
        "title": selected["title"],
        "published_at": selected["published_at"].isoformat(),
        "identity_match": selected["match_basis"],
        "node": node_name,
        "planned_at": planned_at.isoformat(),
        "actual_at": actual_at.isoformat(),
        "lateness_seconds": lateness_seconds,
        "within_30m": lateness_seconds <= 1800,
        "suggested_base_status": "成功" if lateness_seconds <= 1800 else "延迟补采",
        "data_source": "创作者中心导出",
        "data_completeness": "部分缺失",
        "metrics": metrics,
        "missing_detail_fields": ["流量来源"],
        "source": {
            "xlsx": str(xlsx.resolve()),
            "sheet": sheet.title,
            "row_number": selected["row_number"],
            "headers": headers,
            "raw_row": [serializable(value) for value in row],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--output")
    parser.add_argument("--actual-at")
    args = parser.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    actual_at = (
        datetime.fromisoformat(args.actual_at.replace("Z", "+00:00"))
        if args.actual_at
        else datetime.now().astimezone()
    )
    try:
        result = parse_export(Path(args.xlsx), plan, args.node, actual_at)
    except Exception as error:  # The caller needs a structured failure artifact.
        result = {"ok": False, "error": str(error), "xlsx": str(Path(args.xlsx).resolve())}
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
