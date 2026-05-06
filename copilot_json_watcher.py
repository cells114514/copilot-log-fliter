import argparse
import glob
import json
import os
import time
from datetime import datetime, timezone
import logging


def now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(timezone.utc).isoformat()


def extract_one_json_chunk(text: str, decoder: json.JSONDecoder):
    """从文本中尝试提取一个完整的 JSON 对象或数组。"""
    starts = []
    for token in ("{", "["):
        index = text.find(token)
        if index != -1:
            starts.append(index)
    if not starts:
        return None

    for start in sorted(starts):
        try:
            obj, end = decoder.raw_decode(text, start)
            return start, end, obj
        except json.JSONDecodeError:
            continue
    return None


def open_log(log_file: str, from_start: bool):
    """以二进制方式打开日志文件，并返回文件句柄和 inode。"""
    f = open(log_file, "rb")
    if not from_start:
        f.seek(0, os.SEEK_END)
    stat = os.fstat(f.fileno())
    return f, stat.st_ino


def pick_latest_file(pattern: str):
    """按通配符选择最近修改的文件；没有匹配时返回 None。"""
    matches = glob.glob(pattern)
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)

def analyse_json_line(json_obj):
    """根据 JSON 对象的 type 字段分析正在进行的操作，并打印相关信息。"""
    type_str = json_obj.get("type", "")

    handlers = {
        "function": lambda o: f"捕获操作：function：{o.get('name', '未知')}",
        "function_call": lambda o: f"捕获操作：function_call：{o.get('name', '未知')}",
        "function_call_output": lambda o: "捕获操作：function_call_output",
        "custom": lambda o: f"捕获操作：custom：{o.get('name', '未知')}",
        "custom_tool_call": lambda o: f"捕获操作：custom_tool_call：{o.get('name', '未知')}",
        "custom_tool_call_output": lambda o: "捕获操作：custom_tool_call_output",
        "reasoning": lambda o: "reasoning：思考中",
        "message": lambda o: "message：消息S输出",
    }
    

    msg_builder = handlers.get(type_str, lambda o: f"捕获操作：未知类型：{type_str}")
    logging.info(msg_builder(json_obj))


def trim_file_to_last_n_lines(file_path: str, max_lines: int):
    """如果文件行数超过 `max_lines`，则保留最后 `max_lines` 行并覆盖文件。"""
    if max_lines is None or max_lines <= 0:
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= max_lines:
            return
        # 只保留最后 max_lines 行
        keep = lines[-max_lines:]
        tmp_path = file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.writelines(keep)
        os.replace(tmp_path, file_path)
        # logging.info(f"已修剪 {file_path}，保留最后 {max_lines} 行")
    except FileNotFoundError:
        return
    except Exception:
        logging.exception(f"修剪文件时出错: {file_path}")

def main():
    """解析参数并持续监听 Copilot 日志，抽取其中的 JSON 记录。"""
    curr_path = os.path.dirname(os.path.abspath(__file__))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="实时监听 Copilot 日志，提取新增内容中的 JSON 结构并保存为 JSONL。"
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="要监听的日志文件路径（设置后优先于 --log-pattern）。",
    )
    parser.add_argument(
        "--log-pattern",
        default="/home/alan/.copilot/logs/process-*.log",
        help="日志文件通配符，默认监听最新的 process-*.log。",
    )
    parser.add_argument(
        "--output",
        default=curr_path + "/copilot_json_updates.jsonl",
        help="提取结果输出路径（JSONL）。",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=10000,
        help="输出文件最大保留行数，超过则删除最早的行，<=0 表示不限制（默认 10000）。",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="轮询间隔秒数。",
    )
    parser.add_argument(
        "--from-start",
        action="store_true",
        help="从日志文件开头开始读取（默认只读取新增内容）。",
    )
    parser.add_argument(
        "--write-file",
        action="store_true",
        default=False,
        help="是否将捕获的 JSON 对象写入输出文件（默认 False）。",
    )
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    decoder = json.JSONDecoder()

    current_log_file = args.log_file or pick_latest_file(args.log_pattern)
    while not current_log_file:
        logging.info(f"[{now_iso()}] 等待日志文件出现: {args.log_pattern}")
        time.sleep(args.poll_interval)
        current_log_file = args.log_file or pick_latest_file(args.log_pattern)

    log_fp, current_inode = open_log(current_log_file, args.from_start)
    buffer = ""

    logging.info(f"[{now_iso()}] 监听中: {current_log_file}")
    logging.info(f"[{now_iso()}] 输出到: {args.output}")

    while True:
        chunk = log_fp.read()
        if chunk:
            buffer += chunk.decode("utf-8", errors="replace")

            while True:
                found = extract_one_json_chunk(buffer, decoder)
                if not found:
                    if len(buffer) > 1_000_000:
                        buffer = buffer[-50_000:]
                    break

                start, end, obj = found
                record = {
                    "captured_at": now_iso(),
                    "source_file": current_log_file,
                    "json": obj,
                }
                if args.write_file:
                    # 追加新记录，然后按需修剪文件到最大行数
                    with open(args.output, "a", encoding="utf-8") as out_fp:
                        out_fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                        out_fp.flush()

                    # 修剪文件以保持滚动策略（如果设置了最大行数）
                    try:
                        trim_file_to_last_n_lines(args.output, args.max_lines)
                    except Exception:
                        logging.exception("尝试修剪输出文件时失败")
                    buffer = buffer[end:]

                # 此处往后加入分析正在进行的操作
                analyse_json_line(obj)
        else:
            try:
                st = os.stat(current_log_file)
                rotated = st.st_ino != current_inode
                truncated = st.st_size < log_fp.tell()
                if rotated or truncated:
                    log_fp.close()
                    log_fp, current_inode = open_log(current_log_file, True)
                    buffer = ""
            except FileNotFoundError:
                logging.warning(f"日志文件未找到: {current_log_file}")

            if not args.log_file:
                newest = pick_latest_file(args.log_pattern)
                if newest and newest != current_log_file:
                    current_log_file = newest
                    log_fp.close()
                    log_fp, current_inode = open_log(current_log_file, True)
                    buffer = ""
                    logging.info(f"[{now_iso()}] 切换到最新日志: {current_log_file}")

            time.sleep(args.poll_interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("用户中断，退出程序。")
    except Exception as e:
        logging.exception(f"发生错误: {e}")
