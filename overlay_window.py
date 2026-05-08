import sys
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon, QMovie, QPainter
from PyQt5.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon, QWidget


class OverlayWindow(QWidget):
    def __init__(self, gif_path: str = "sleep.gif") -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        if hasattr(Qt, "WindowTransparentForInput"):
            self.setWindowFlag(Qt.WindowTransparentForInput, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._movie = QMovie(gif_path)
        self._movie.frameChanged.connect(self._on_frame_changed)

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
        if self._movie.state() == QMovie.Running:
            self._movie.stop()
        new_gif_path = f"gifFolder/{gif_dict.get(key, 'sleep.gif')}"
        if not QMovie(new_gif_path).isValid():
            return
        self._movie.setFileName(new_gif_path)
        self._movie.start()

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
