import sys
import contextlib
import time

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QPainter, QColor, QPixmap, QPen, QTabletEvent
from PySide6.QtGui import QPainterPath, QCursor, QBitmap, QIcon
from PySide6.QtCore import Qt, QEvent, QRect, QTimer, QFile, QObject, QSize
from PySide6.QtCore import Signal, QPointF, QRectF, QSizeF
from PySide6.QtUiTools import QUiLoader

MAX_RADIUS = 100


class Overlay():
    def __init__(self, topleft=None, pixmap=None):
        self.pixmap = pixmap
        if topleft and pixmap:
            self.rect = QRect(
                topleft.x(), topleft.y(),
                pixmap.width(), pixmap.height()
            )
        else:
            self.rect = None

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
            'red': ColorMarker(1, 0, 0),
            'green': ColorMarker(0, 1, 0),
            'blue': ColorMarker(0, 0, 1),
            'yellow': ColorMarker(1, 1, 0),
            'purple': ColorMarker(1, 0, 1),
            'cyan': ColorMarker(0, 1, 1),
        }
        self.tool = self.tools['marker']
        self.last_point = 0

    def anim_update(self):
        if self.current_wet.rect is not None:
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
                scribble.paint(painter)
        if canvas:
            canvas.paint(painter)
        painter.setOpacity(1)
        if self.current_wet:
            self.current_wet.paint(painter)
        painter.end()

    def tabletEvent(self, e):
        if e.type() == QEvent.TabletPress:
            self.start_line(e.posF())
        if e.type() in (QEvent.TabletMove, QEvent.TabletRelease):
            self.add_point(
                pos=e.posF(),
                pressure=e.pressure(),
                erase=e.pointerType() == QTabletEvent.Eraser,
            )
        e.accept()

    def mousePressEvent(self, e):
        self.start_line(e.localPos())

    def mouseMoveEvent(self, e):
        self.add_point(e.localPos())

    def start_line(self, pos):
        self.last_point = pos
        self.scribbles.append(Overlay())

    def add_point(self, pos, *, pressure=0.5, erase=False):
        tool = self.tool
        if self.tool is None:
            return
        if erase:
            tool = self.tools['eraser']
        if not self.scribbles:
            self.scribbles.append(Overlay())
        if self.last_point:
            tool.set_size(pressure)
            update_rect = QRect(self.last_point.toPoint(), pos.toPoint())
            update_rect = update_rect.normalized().adjusted(
                -tool.size-1, -tool.size-1, tool.size+1, tool.size+1,
            )
            tool.draw(
                self.last_point, pos,
                update_rect,
                self.scribbles, self.current_wet
            )
            self.update(update_rect)
        self.last_point = pos
        self.update_wet()

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
                self.current_wet = Overlay()
                #self.update_wet()

    def redo(self):
        if self.undo_stack:
            redone = self.undo_stack.pop()
            self.scribbles.append(redone)
            self.update(redone.rect)
            #self.current_wet.add(redone)
            #self.update_wet()

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


class ColorMarker(Tool):
    def __init__(self, r, g, b):
        super().__init__()
        self.pen.setColor(QColor(int(r*255), int(g*255), int(b*255)))

    def set_size(self, size):
        super().set_size(size * MAX_RADIUS / 5)


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
        widget = self.obj.findChild(QObject, name)
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

        ch = WidgetFinder(self.window)

        ch.btnDisable.clicked.connect(overlay_widget.unset_tool)
        ch.btnMarker.clicked.connect(lambda: overlay_widget.set_tool('marker'))
        ch.btnHighlighter.clicked.connect(lambda: overlay_widget.set_tool('highlighter'))
        ch.btnEraser.clicked.connect(lambda: overlay_widget.set_tool('eraser'))

        ch.btnRed.clicked.connect(lambda: overlay_widget.set_tool('red'))
        ch.btnGreen.clicked.connect(lambda: overlay_widget.set_tool('green'))
        ch.btnBlue.clicked.connect(lambda: overlay_widget.set_tool('blue'))
        ch.btnYellow.clicked.connect(lambda: overlay_widget.set_tool('yellow'))
        ch.btnPurple.clicked.connect(lambda: overlay_widget.set_tool('purple'))
        ch.btnCyan.clicked.connect(lambda: overlay_widget.set_tool('cyan'))

        ch.actClear.triggered.connect(overlay_widget.clear)
        ch.actUndo.triggered.connect(overlay_widget.undo)
        ch.actRedo.triggered.connect(overlay_widget.redo)
        ch.actClose.triggered.connect(sys.exit)
        ch.actDrawing.toggled.connect(app.update_grab)

        app.grab_updated.connect(ch.actDrawing.setChecked)

class Application(QApplication):
    grab_updated = Signal(bool)

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
            if toolbox.window.geometry().contains(QCursor.pos()):
                return False
            self.update_grab(True)
            return True
        elif e.type() == QEvent.TabletLeaveProximity:
            print('leave')
            return True
        elif e.type() == QEvent.TabletTrackingChange:
            print('track')
            return True
        return False

    def update_grab(self, grab):
        if grab:
            if not toolbox.overlay_widget.tool:
                return False
            self._grabbing_mouse = True
            w.grabMouse()
        else:
            w.releaseMouse()
            self._grabbing_mouse = False
            QCursor.setPos(self._last_cursor_pos)
        self.grab_updated.emit(self._grabbing_mouse)


if __name__ == '__main__':
    app = Application(sys.argv)
    w = OverlayWidget()

    for screen in app.screens():
        print(screen.manufacturer())
        if screen.manufacturer().startswith('Wacom'):
            geom = screen.geometry()
            w.move(geom.left(), geom.top())
            w.resize(geom.width(), geom.height())
            break
        if screen.manufacturer().startswith('Chimei Innolux Corporation'):
            geom = screen.geometry()
            w.move(geom.left(), geom.top())
            w.resize(geom.width(), geom.height())
            break

    w.showFullScreen()

    toolbox = ToolboxWindow(w)
    toolbox.window.show()
    toolbox.window.move(w.geometry().topLeft())

    app._toolbox = toolbox

    print(QIcon.themeSearchPaths())

    sys.exit(app.exec())
