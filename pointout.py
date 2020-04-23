import sys
import contextlib
import time

from PySide2.QtWidgets import QApplication, QWidget
from PySide2.QtGui import QPainter, QColor, QPixmap, QPen, QTabletEvent
from PySide2.QtGui import QPainterPath, QCursor
from PySide2.QtCore import Qt, QEvent, QRect, QTimer

MAX_RADIUS = 100

class Overlay():
    def __init__(self, topleft=None, pixmap=None):
        self.pixmap = pixmap
        if topleft and pixmap:
            self.rect = QRect(
                self.topleft.x(), self.topleft.y(),
                pixmap.width(), pixmap.height()
            )
        else:
            self.rect = None

    def paint(self, painter):
        if self.rect:
            painter.drawPixmap(self.rect.topLeft(), self.pixmap)

    def reserve(self, rect):
        if self.rect:
            new_rect = self.rect.united(rect)
        else:
            new_rect = rect
        new_pixmap = QPixmap(new_rect.width(), new_rect.height())
        new_pixmap.fill(QColor(0, 0, 0, 0))
        if self.pixmap:
            painter = QPainter(new_pixmap)
            painter.drawPixmap(
                self.rect.left() - new_rect.left(),
                self.rect.top() - new_rect.top(),
                self.pixmap
            )
            painter.end()
        self.pixmap = new_pixmap
        self.rect = new_rect

    def add(self, other_overlay):
        if self.rect:
            self.reserve(other_overlay.rect)
            painter = QPainter(self.pixmap)
            painter.drawPixmap(
                other_overlay.rect.left() - self.rect.left(),
                other_overlay.rect.top() - self.rect.top(),
                other_overlay.pixmap
            )
            painter.end()
        else:
            self.pixmap = other_overlay.pixmap.copy()
            self.rect = other_overlay.rect

    @contextlib.contextmanager
    def painter_context(self):
        if self.pixmap:
            painter = QPainter(self.pixmap)
            painter.translate(-self.rect.topLeft())
            try:
                yield painter
            finally:
                painter.end()
        else:
            yield None

class OverlayWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            self.windowFlags()
            | Qt.Window
            | Qt.WindowTransparentForInput
            | Qt.WindowDoesNotAcceptFocus
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TabletTracking)

        self.scribbles = []
        self.current_wet = Overlay()

        self.setCursor(Qt.CrossCursor)

        self.anim_timer = QTimer()
        self.anim_timer.timeout.connect(self.anim_update)
        self.anim_timer.start(1000//30)
        self.anim_timer.setTimerType(Qt.CoarseTimer)
        self.last_update = time.monotonic()

    def _handle_timeout(self):
        self.anim_update()
        if self.scribble_parts:
            del self.scribble_parts[0]
        self.scribble_parts.append(Overlay())
        if self.current_part:
            for part in self.scribble_parts:
                part.add(self.current_part)
            if not self.scribbles:
                self.scribbles.append(Overlay())
            self.scribbles[-1].add(self.current_part)
            self.current_part = None
        self.anim_update()

    def anim_update(self):
        if self.current_wet and self.current_wet.rect is not None:
            print(self.last_update, self.last_update + 4, time.monotonic())
            with self.current_wet.painter_context() as painter:
                painter.setBrush(QColor(0, 0, 0, 255))
                painter.setPen(QPen(0))
                painter.setOpacity(0.1)
                painter.setCompositionMode(QPainter.CompositionMode_DestinationOut)
                painter.drawRect(self.current_wet.rect)
            self.update(self.current_wet.rect)
            if self.last_update + 1 < time.monotonic():
                self.current_wet = Overlay()

    def paintEvent(self, e):
        painter = QPainter(self);
        painter.setOpacity(0.5)
        for scribble in self.scribbles:
            scribble.paint(painter)
        painter.setOpacity(1)
        if self.current_wet:
            self.current_wet.paint(painter)
        painter.end()

    def tabletEvent(self, e):
        #print(e.posF(), e.device(), hex(e.buttons()), e.pointerType(), e.pressure(), e.rotation(), e.xTilt(), e.yTilt())
        e.accept()
        if e.type() == QEvent.TabletPress:
            self.last_point = e.posF()
            if not self.current_wet.rect:
                self.scribbles.append(Overlay())
        if e.type() in (QEvent.TabletMove, QEvent.TabletRelease):
            if not self.scribbles:
                self.scribbles.append(Overlay())
            if self.last_point:
                size = e.pressure()*MAX_RADIUS
                if e.pointerType() != QTabletEvent.Eraser:
                    size /= 10
                alpha = 255
                if size < 1:
                    alpha = int(255 * size)
                    size = 1
                update_rect = QRect(self.last_point.toPoint(), e.pos())
                update_rect = update_rect.normalized().adjusted(
                    -size-1, -size-1, size+1, size+1,
                )
                if e.pointerType() == QTabletEvent.Eraser:
                    pen = QPen(
                        QColor(255, 255, 255, 255),
                        size,
                        Qt.SolidLine,
                        Qt.RoundCap,
                        Qt.BevelJoin,
                    )
                    self.current_wet.reserve(update_rect)
                    with self.current_wet.painter_context() as painter:
                        painter.setPen(pen)
                        painter.setRenderHint(QPainter.Antialiasing)
                        painter.drawLine(self.last_point, e.posF())
                    for overlay in self.scribbles:
                        with overlay.painter_context() as painter:
                            if overlay.rect:
                                painter.setPen(pen)
                                painter.setRenderHint(QPainter.Antialiasing)
                                painter.setCompositionMode(QPainter.CompositionMode_Clear)
                                painter.drawLine(self.last_point, e.posF())
                else:
                    pen = QPen(
                        QColor(0, 0, 0, alpha),
                        size,
                        Qt.SolidLine,
                        Qt.RoundCap,
                        Qt.BevelJoin,
                    )
                    for overlay in self.scribbles[-1], self.current_wet:
                        overlay.reserve(update_rect)
                        with overlay.painter_context() as painter:
                            painter.setPen(pen)
                            painter.setRenderHint(QPainter.Antialiasing)
                            painter.drawLine(self.last_point, e.posF())
                self.update(update_rect)
            self.last_point = e.posF()
            self.last_update = time.monotonic()
        if e.type() == QEvent.TabletRelease:
            pass
        e.accept()

    def paint(self, painter, e):
        if not self.last_point:
            return
        last_pos, last_pressure = self.last_point
        painter.drawLine(last_pos, e.posF())
        self.update(QRect(last_pos.toPoint(), e.pos()).normalized().adjusted(
            -MAX_RADIUS, -MAX_RADIUS, MAX_RADIUS, MAX_RADIUS))


class Application(QApplication):
    global grabbing_mouse
    def __init__(self, *args):
        super().__init__(*args)
        self._grabbing_mouse = False
        self._last_cursor_pos = QCursor.pos()


        def update_pos():
            if not self._grabbing_mouse:
                self._last_cursor_pos = QCursor.pos()

        self._timer = QTimer()
        self._timer.timeout.connect(update_pos)
        self._timer.start(100)

    def event(self, e):
        if e.type() == QEvent.TabletEnterProximity:
            print('enter')
            w.grabMouse()
            self._grabbing_mouse = True
            return True
        elif e.type() == QEvent.TabletLeaveProximity:
            print('leave')
            w.releaseMouse()
            self._grabbing_mouse = False
            QCursor.setPos(self._last_cursor_pos)
            return True
        elif e.type() == QEvent.TabletTrackingChange:
            print('track')
            return True
        return False


if __name__ == '__main__':
    app = Application(sys.argv)
    w = OverlayWidget()

    for screen in app.screens():
        if screen.manufacturer().startswith('Wacom'):
            geom = screen.geometry()
            w.move(geom.left(), geom.top())
            w.resize(geom.width(), geom.height())

    w.showFullScreen()

    sys.exit(app.exec_())
