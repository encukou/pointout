import sys
import contextlib
import time

from PySide2.QtWidgets import QApplication, QWidget
from PySide2.QtGui import QPainter, QColor, QPixmap, QPen, QTabletEvent
from PySide2.QtGui import QPainterPath, QCursor, QBitmap
from PySide2.QtCore import Qt, QEvent, QRect, QTimer, QFile, QObject, QSize
from PySide2.QtUiTools import QUiLoader

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
        self.blend_with_next = False

    def __repr__(self):
        return f'<Overlay {self.rect}>'

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
        self.setWindowTitle('pointout canvas')
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
        self.undo_stack = []

        cursor_bitmap = QBitmap.fromData(QSize(5, 5), bytes((
            0b00000, 0b00000, 0b00100, 0b00000, 0b00000,
        )))
        mask_bitmap = QBitmap.fromData(QSize(5, 5), bytes((
            0b00100, 0b00000, 0b10101, 0b00000, 0b00100,
        )))
        self.setCursor(QCursor(cursor_bitmap, mask_bitmap))

        self.anim_timer = QTimer()
        self.anim_timer.timeout.connect(self.anim_update)
        self.anim_timer.start(1000//30)
        self.anim_timer.setTimerType(Qt.CoarseTimer)
        self.wet_end = time.monotonic()

        self.tools = {
            'marker': Marker(),
            'highlighter': Highlighter(),
            'eraser': Eraser(),
        }
        self.tool = self.tools['marker']

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
            with self.current_wet.painter_context() as painter:
                painter.setBrush(QColor(0, 0, 0, 255))
                painter.setPen(QPen(0))
                painter.setOpacity(0.1)
                painter.setCompositionMode(QPainter.CompositionMode_DestinationOut)
                painter.drawRect(self.current_wet.rect)
            self.update(self.current_wet.rect)
            if self.wet_end < time.monotonic():
                self.current_wet = Overlay()

    def paintEvent(self, e):
        painter = QPainter(self);
        painter.setOpacity(0.5)
        canvas = None
        for scribble in self.scribbles:
            if scribble.rect:
                if scribble.blend_with_next:
                    if canvas is None:
                        canvas = Overlay()
                    canvas.add(scribble)
                else:
                    if canvas:
                        canvas.add(scribble)
                        canvas.paint(painter)
                        canvas = None
                    else:
                        scribble.paint(painter)
        if canvas:
            canvas.paint(painter)
        painter.setOpacity(1)
        if self.current_wet:
            self.current_wet.paint(painter)
        painter.end()

    def tabletEvent(self, e):
        #print(e.posF(), e.device(), hex(e.buttons()), e.pointerType(), e.pressure(), e.rotation(), e.xTilt(), e.yTilt())
        e.accept()
        if e.type() == QEvent.TabletPress:
            self.last_point = e.posF()
            if self.current_wet.rect and self.scribbles:
                self.scribbles[-1].blend_with_next = True
            self.scribbles.append(Overlay())
        if e.type() in (QEvent.TabletMove, QEvent.TabletRelease):
            tool = self.tool
            if self.tool is None:
                return
            if e.pointerType() == QTabletEvent.Eraser:
                tool = self.tools['eraser']
            if not self.scribbles:
                self.scribbles.append(Overlay())
            if self.last_point:
                tool.set_size(e.pressure())
                update_rect = QRect(self.last_point.toPoint(), e.pos())
                update_rect = update_rect.normalized().adjusted(
                    -tool.size-1, -tool.size-1, tool.size+1, tool.size+1,
                )
                tool.draw(
                    self.last_point, e.posF(),
                    update_rect,
                    self.scribbles, self.current_wet
                )
                self.update(update_rect)
            self.last_point = e.posF()
            self.update_wet()
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

    def set_tool(self, tool_name):
        self.tool = self.tools[tool_name]

    def unset_tool(self):
        self.tool = None

    def clear(self):
        while self.scribbles:
            self.undo()

    def undo(self):
        if self.scribbles:
            undone = self.scribbles.pop()
            if not undone.rect:
                self.undo()
            else:
                self.undo_stack.append(undone)
                self.update(undone.rect)

    def redo(self):
        if self.undo_stack:
            redone = self.undo_stack.pop()
            self.scribbles.append(redone)
            self.update(redone.rect)

    def update_wet(self, seconds=1):
        self.wet_end = time.monotonic() + seconds

class Tool:
    def __init__(self):
        self.pen = QPen(
            QColor(0, 0, 0, 0),
            0,
            Qt.SolidLine,
            Qt.RoundCap,
            Qt.BevelJoin,
        )
        self.set_size(1)

    def set_size(self, size):
        self.size = size
        self.alpha = 255
        if size < 1:
            self.alpha = int(255 * size)
            self.size = 1
        self.pen.setWidth(self.size)
        color = self.pen.color()
        color.setAlpha(self.alpha)
        self.pen.setColor(color)

    def draw(self, last, now, update_rect, scribbles, wet):
        for overlay in scribbles[-1], wet:
            if overlay:
                overlay.reserve(update_rect)
                with overlay.painter_context() as painter:
                    painter.setPen(self.pen)
                    painter.setRenderHint(QPainter.Antialiasing)
                    painter.drawLine(last, now)


class Marker(Tool):
    def set_size(self, size):
        super().set_size(size * MAX_RADIUS / 10)


class Highlighter(Tool):
    def set_size(self, size):
        self.pen.setColor(QColor(255, 250, 0, 255))
        super().set_size(size * MAX_RADIUS / 2)


class Eraser(Tool):
    def set_size(self, size):
        super().set_size(size * MAX_RADIUS)
        self.pen.setColor(QColor(255, 255, 255, 255))

    def draw(self, last, now, update_rect, scribbles, wet):
        wet.reserve(update_rect)
        with wet.painter_context() as painter:
            painter.setPen(self.pen)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.drawLine(last, now)

        for overlay in scribbles:
            with overlay.painter_context() as painter:
                if painter:
                    painter.setPen(self.pen)
                    painter.setRenderHint(QPainter.Antialiasing)
                    painter.setCompositionMode(QPainter.CompositionMode_Clear)
                    painter.drawLine(last, now)


class WidgetFinder:
    def __init__(self, obj):
        self.obj = obj

    def __getattr__(self, name):
        widget = self.obj.findChild(QWidget, name)
        if widget is None:
            raise AttributeError(name)
        return widget

class ToolboxWindow(QObject):
    def __init__(self, overlay_widget, **args):
        super().__init__(**args)
        self.overlay_widget = overlay_widget
        self.window = QUiLoader().load('toolbox.ui')
        self.window.setWindowFlags(
            self.window.windowFlags()
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )
        self.window.resize(0, 0)
        tools = [Marker(), Eraser()]

        ch = WidgetFinder(self.window)

        ch.btnDisable.clicked.connect(lambda: overlay_widget.unset_tool())
        ch.btnMarker.clicked.connect(lambda: overlay_widget.set_tool('marker'))
        ch.btnHighlighter.clicked.connect(lambda: overlay_widget.set_tool('highlighter'))
        ch.btnEraser.clicked.connect(lambda: overlay_widget.set_tool('eraser'))
        ch.btnClear.clicked.connect(lambda: overlay_widget.clear())
        ch.btnUndo.clicked.connect(lambda: overlay_widget.undo())
        ch.btnRedo.clicked.connect(lambda: overlay_widget.redo())
        ch.btnClose.clicked.connect(QApplication.quit)

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
            print('enter', toolbox.window.geometry(), QCursor.pos())
            if not toolbox.overlay_widget.tool:
                return False
            self._grabbing_mouse = True
            if toolbox.window.geometry().contains(QCursor.pos()):
                return False
            w.grabMouse()
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

    toolbox = ToolboxWindow(w)
    toolbox.window.show()
    toolbox.window.move(w.geometry().topLeft())

    app._toolbox = toolbox

    sys.exit(app.exec_())
