import os
import sys
from pathlib import Path

def _configure_qt_plugin_paths() -> None:
    """优先让 Qt 从当前虚拟环境中的 PyQt5 插件目录加载平台与图像插件。"""
    pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    plugin_root = Path(sys.prefix) / "lib" / pyver / "site-packages" / "PyQt5" / "Qt5" / "plugins"
    if not plugin_root.exists():
        return
    if not os.environ.get("QT_PLUGIN_PATH"):
        os.environ["QT_PLUGIN_PATH"] = str(plugin_root)
    if not os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH"):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugin_root / "platforms")


def _resolve_gif_path(gif_path: str) -> str:
    """将相对 GIF 路径解析到项目根目录，避免依赖当前工作目录。"""
    path = Path(gif_path)
    if path.is_absolute():
        return str(path)
    # 使用预计算的项目根目录，避免每次调用时执行 Path.resolve()
    project_root = PROJECT_ROOT
    gif_folder_candidate = project_root / "gifFolder" / gif_path
    if gif_folder_candidate.exists():
        return str(gif_folder_candidate)
    candidate = project_root / gif_path
    if candidate.exists():
        return str(candidate)
    return str(path)


_configure_qt_plugin_paths()

# 预计算项目根目录，避免在频繁调用中使用 Path.resolve() 导致阻塞
try:
    PROJECT_ROOT = Path(__file__).parent
except Exception:
    PROJECT_ROOT = Path('.')

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QIcon, QMovie, QPainter
from PyQt5.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon, QWidget


class _GifEmitter(QObject):
    """线程安全的信号发射器：从后台线程 emit 信号请求 GUI 更改 GIF。"""

    change_requested = pyqtSignal(str, dict)


class OverlayWindow(QWidget):
    def __init__(self, gif_path: str = "sleep.gif") -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        if hasattr(Qt, "WindowTransparentForInput"):
            self.setWindowFlag(Qt.WindowTransparentForInput, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._movie = QMovie(_resolve_gif_path(gif_path))
        self._movie.frameChanged.connect(self._on_frame_changed)

        # 保护机制：跟踪最后一次请求的 GIF，避免在 gif_dict 为 None 时抛错
        self._last_requested_key = None

        # 线程安全的信号发射器，用于从后台线程请求 GUI 更改
        self._emitter = _GifEmitter()
        self._emitter.change_requested.connect(self.change_gif)

        if not self._movie.isValid():
            self.resize(400, 300)
        else:
            self._movie.start()
            first_frame = self._movie.currentPixmap()
            if not first_frame.isNull():
                self.resize(first_frame.size())
            else:
                frame_rect = self._movie.frameRect()
                if frame_rect.isValid():
                    self.resize(frame_rect.size())
                else:
                    self.resize(400, 300)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        pixmap = self._movie.currentPixmap()
        if not pixmap.isNull():
            painter.drawPixmap(0, 0, pixmap)

    def change_gif(self, key: str, gif_dict: dict) -> None:
        # 防御性编程：如果没有传入 gif_dict 或 key 为空，则忽略
        if not gif_dict or not key:
            return
        # 避免重复处理相同 key
        if key == self._last_requested_key:
            return
        self._last_requested_key = key

        if self._movie.state() == QMovie.Running:
            self._movie.stop()
        try:
            new_gif_path = _resolve_gif_path(f"gifFolder/{gif_dict.get(key, 'sleep.gif')}")
        except Exception:
            return
        if not QMovie(new_gif_path).isValid():
            return
        self._movie.setFileName(new_gif_path)
        self._movie.start()

    def emit_change(self, key: str, gif_dict: dict) -> None:
        """线程安全地向 GUI 线程请求改变 GIF。可从任意线程调用。"""
        try:
            self._emitter.change_requested.emit(key, gif_dict)
        except Exception:
            # 如果窗口正在关闭或对象被删除，忽略发射错误
            pass

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._move_to_bottom_right()

    def _on_frame_changed(self, _frame: int) -> None:
        pixmap = self._movie.currentPixmap()
        if not pixmap.isNull() and pixmap.size() != self.size():
            self.resize(pixmap.size())
            self._move_to_bottom_right()
        self.update()

    def _move_to_bottom_right(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move(available.right() - self.width() + 1, available.bottom() - self.height() + 1)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._movie.frameChanged.disconnect(self._on_frame_changed)
        self._movie.stop()
        event.accept()
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)


def main() -> int:
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

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
