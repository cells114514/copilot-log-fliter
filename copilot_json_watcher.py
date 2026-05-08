import argparse
import sys
import glob
import json
import os
import time
from datetime import datetime, timezone
import logging
import threading
from overlay_window import OverlayWindow
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon, QMovie, QPainter
from PyQt5.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon


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


def json_to_dict(jsonfile):
    """从 JSON 文件中加载数据并返回字典。"""
    if not os.path.exists(jsonfile):
        logging.warning(f"JSON 文件未找到: {jsonfile}")
        return None
    with open(jsonfile, "r", encoding="utf-8") as f:
        return json.load(f)
    

def check_gif_available(gif_dict):
    for key, gif in gif_dict.items():
        if not os.path.exists(os.path.join("gifFolder", gif)):
            logging.error(f"GIF 文件未找到: {gif} (对应操作: {key})")
            return False
    return True


def pick_latest_file(pattern: str):
    """按通配符选择最近修改的文件；没有匹配时返回 None。"""
    matches = glob.glob(pattern)
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)

def analyse_json_line(json_obj, window=None, gif_dict=None):
    """根据 JSON 对象的 type 字段分析正在进行的操作，并打印相关信息。"""
    type_str = json_obj.get("type", "")
    logging.info(f"捕获 JSON 类型: {type_str}")
    window.change_gif(type_str, gif_dict)


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

def main(window=None, stop_event: threading.Event = None):
    """解析参数并持续监听 Copilot 日志，抽取其中的 JSON 记录。"""
    curr_path = os.path.dirname(os.path.abspath(__file__))
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    gif_dict = json_to_dict(curr_path + "/gifFolder/gifDict.json")
    if gif_dict:
        logging.info(f"已加载 GIF 字典，包含 {len(gif_dict)} 条目。")
    if not check_gif_available(gif_dict):
        logging.error("部分 GIF 文件未找到，程序将退出。")
        return


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
        default=f"/home/{os.getlogin()}/.copilot/logs/process-*.log",
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

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                logging.info("停止事件收到，结束日志监听循环。")
                break
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
                    analyse_json_line(obj, window, gif_dict)
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
            if stop_event is not None and stop_event.is_set():
                break
            time.sleep(args.poll_interval)
    finally:
        try:
            log_fp.close()
        except Exception:
            pass
        logging.info("日志监听已清理并退出。")


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)

        window = OverlayWindow()
        window.show()

        tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            frame = window._movie.currentPixmap()
            if not frame.isNull():
                tray_icon = QIcon(frame)
            else:
                tray_icon = app.style().standardIcon(QStyle.SP_ComputerIcon)
            tray = QSystemTrayIcon(tray_icon, app)

            tray_menu = QMenu()
            close_action = tray_menu.addAction("关闭")
            close_action.triggered.connect(window.close)
            tray.setContextMenu(tray_menu)
            tray.show()

        stop_event = threading.Event()
        watcher = threading.Thread(target=main, args=(window, stop_event), daemon=True)
        watcher.start()

        try:
            exit_code = app.exec_()
        finally:
            # Qt 事件循环退出或窗口关闭时，通知后台线程停止并等待其结束
            stop_event.set()
            watcher.join(timeout=2)
            if tray is not None:
                try:
                    tray.hide()
                except Exception:
                    pass
            logging.info("应用退出完成。")

    except KeyboardInterrupt:
        logging.info("用户中断，退出程序。")
    except Exception as e:
        logging.exception(f"发生错误: {e}")
