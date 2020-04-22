import sys
from PySide2.QtWidgets import QApplication, QWidget
from PySide2.QtGui import QPainter, QColor, QPixmap, QPen, QTabletEvent
from PySide2.QtCore import Qt, QEvent, QRect

MAX_RADIUS = 100

class Overlay(QWidget):
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

        self.pixmap = QPixmap(self.width(), self.height())
        self.pixmap.fill(QColor(0, 0, 0, 1))

        self.setCursor(Qt.CrossCursor)

    def resizeEvent(self, e):
        new_pixmap = QPixmap(self.width() , self.height())
        new_pixmap.fill(QColor(0, 0, 0, 1))
        painter = QPainter(new_pixmap)
        painter.drawPixmap(0, 0, self.pixmap)
        painter.end()
        self.pixmap = new_pixmap

    def paintEvent(self, e):
        painter = QPainter(self);
        painter.setBrush(QColor(0, 0, 0, 100))
        #painter.drawRect(e.rect());
        painter.drawPixmap(e.rect().topLeft(), self.pixmap, e.rect());
        painter.end()

    def tabletEvent(self, e):
        print(e.posF(), e.device(), hex(e.buttons()), e.pointerType(), e.pressure(), e.rotation(), e.xTilt(), e.yTilt())
        e.accept()
        if e.type() == QEvent.TabletPress:
            self.last_point = e.posF(), e.pressure()
        elif e.type() == QEvent.TabletMove:
            painter = QPainter(self.pixmap)
            if e.pointerType() == QTabletEvent.Eraser:
                painter.setPen(QPen(QColor(255, 255, 255, 0), e.pressure()**2*MAX_RADIUS))
                painter.setCompositionMode(QPainter.CompositionMode_Clear)
            else:
                painter.setPen(QPen(QColor(0, 0, 0, 200), e.pressure()*MAX_RADIUS/10))
            painter.setRenderHint(QPainter.Antialiasing)
            self.paint(painter, e)
            self.last_point = e.posF(), e.pressure()
        elif e.type() == QEvent.TabletRelease:
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
    def event(self, e):
        print(e)
        if e.type() == QEvent.TabletEnterProximity:
            print('enter')
            w.grabMouse()
            return True
        elif e.type() == QEvent.TabletLeaveProximity:
            print('leave')
            w.releaseMouse()
            return True
        elif e.type() == QEvent.TabletTrackingChange:
            print('track')
            return True
        return False


if __name__ == '__main__':
    app = Application(sys.argv)
    w = Overlay()

    for screen in app.screens():
        if screen.manufacturer().startswith('Wacom'):
            geom = screen.geometry()
            w.move(geom.left(), geom.top())
            w.resize(geom.width(), geom.height())

    w.showFullScreen()

    sys.exit(app.exec_())
