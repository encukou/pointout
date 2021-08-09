import sys
import contextlib
import time

from PySide6.QtWidgets import QApplication, QWidget, QToolButton, QSizePolicy
from PySide6.QtWidgets import QUndoView, QHBoxLayout, QVBoxLayout, QListView
from PySide6.QtWidgets import QMainWindow
from PySide6.QtGui import QPainter, QColor, QPixmap, QPen, QTabletEvent
from PySide6.QtGui import QPainterPath, QCursor, QBitmap, QIcon, QAction
from PySide6.QtGui import QUndoStack, QUndoCommand, QStandardItemModel
from PySide6.QtGui import QStandardItem, QUndoGroup
from PySide6.QtCore import Qt, QEvent, QRect, QTimer, QFile, QObject, QSize
from PySide6.QtCore import Signal, QPointF, QRectF, QSizeF, QItemSelectionModel
from PySide6.QtUiTools import QUiLoader

MAX_RADIUS = 100

COLORS = {
    'Red': (1, 0, 0),
    'Green': (0, 1, 0),
    'Blue': (0, 0, 1),
    'Yellow': (1, 1, 0),
    'Purple': (1, 0, 1),
    'Cyan': (0, 1, 1),
}

class Overlay():
    composition_mode = QPainter.CompositionMode_SourceOver
    opacity = 0.5
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
            painter.setOpacity(self.opacity)
            painter.setCompositionMode(self.composition_mode)
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


class DrawCommand(QUndoCommand):
    def __init__(self, widget, tool):
        super().__init__(f"Draw with {tool.name}")
        self.widget = widget
        self.scribbles = widget.scribbles
        self.scribble = Overlay()
        self.tool = tool

    def undo(self):
        popped = self.scribbles.pop()
        self.widget.current_wet = Overlay()
        if popped.rect:
            self.widget.update(popped.rect)
            assert popped == self.scribble

    def redo(self):
        self.scribbles.append(self.scribble)
        if self.scribble.rect:
            self.widget.update(self.scribble.rect)


class PictureItem(QStandardItem):
    def __init__(self, widget):
        super().__init__("Drawing")
        self.scribbles = []
        self.undo_stack = QUndoStack()
        widget.undo_group.addStack(self.undo_stack)


class OverlayWidget(QWidget):
    grab_updated = Signal(bool)
    can_clear_changed = Signal(bool)
    can_clear = True
    _last_cursor_pos = None
    _grabbing_mouse = False

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

        self.current_wet = Overlay()

        self.undo_group = QUndoGroup()
        self.picture_model = QStandardItemModel()
        self.selection_model = QItemSelectionModel(self.picture_model)
        self.clear()
        self.selection_model.currentChanged.connect(self.picture_switched)
        self.picture_switched()

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

        self.eraser = Eraser()
        self.tool = Marker()
        self.last_point = 0

    def picture_switched(self):
        self.undo_group.setActiveStack(self.picture.undo_stack)
        self.check_can_clear()
        self.update()

    def check_can_clear(self):
        can_clear = bool(self.scribbles)
        was_can_clear = self.can_clear
        self.can_clear = can_clear
        if can_clear != was_can_clear:
            self.can_clear_changed.emit(can_clear)

    @property
    def picture(self):
        idx = self.selection_model.currentIndex()
        return self.picture_model.itemFromIndex(idx)

    @property
    def scribbles(self):
        return self.picture.scribbles

    @property
    def undo_stack(self):
        return self.picture.undo_stack

    @property
    def tool(self):
        return self._tool
    @tool.setter
    def tool(self, new_tool):
        self._tool = new_tool
        if new_tool is None:
            self.update_grab(False)

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
        painter = QPainter(self)
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
        cmd = DrawCommand(self, self.tool)
        self.undo_stack.push(cmd)
        self.check_can_clear()

    def add_point(self, pos, *, pressure=0.5, erase=False):
        tool = self.tool
        if self.tool is None:
            return
        if erase:
            tool = self.eraser
        if not self.scribbles:
            self.start_line(pos)
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

    def clear(self):
        if self.can_clear:
            pi = PictureItem(self)
            idx = self.selection_model.currentIndex()
            if idx:
                self.picture_model.insertRow(idx.row() + 1, pi)
            else:
                self.picture_model.appendRow(pi)
            self.selection_model.setCurrentIndex(
                self.picture_model.indexFromItem(pi),
                QItemSelectionModel.ClearAndSelect,
            )

    def undo(self):
        self.undo_stack.undo()

    def redo(self):
        self.undo_stack.redo()

    def update_wet(self, seconds=1):
        self.wet_end = time.monotonic() + seconds

    def update_grab(self, grab):
        was_grabbing_mouse = self._grabbing_mouse
        if self.tool is None:
            grab = False
        if grab:
            if not self.tool:
                return False
            self._grabbing_mouse = True
            self.grabMouse()
        else:
            self.releaseMouse()
            self._grabbing_mouse = False
            if self._last_cursor_pos:
                QCursor.setPos(self._last_cursor_pos)
        self.grab_updated.emit(self._grabbing_mouse)

class Tool:
    name = 'tool'

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
    name = 'Marker'
    def set_size(self, size):
        super().set_size(size * MAX_RADIUS / 10)


class ColorMarker(Tool):
    name = 'Color Marker'
    def __init__(self, r, g, b, name=None):
        super().__init__()
        self.pen.setColor(QColor(int(r*255), int(g*255), int(b*255)))
        if name:
            self.name = f'{name} Marker'

    def set_size(self, size):
        super().set_size(size * MAX_RADIUS / 5)


class Highlighter(Tool):
    name = 'Highlighter'
    def set_size(self, size):
        self.pen.setColor(QColor(255, 250, 0, 255))
        super().set_size(size * MAX_RADIUS / 2)


class Eraser(Tool):
    name = 'Eraser'
    def set_size(self, size):
        super().set_size(size * MAX_RADIUS)
        self.pen.setColor(QColor(255, 255, 255, 255))

    def draw(self, last, now, update_rect, scribbles, wet):
        overlay = scribbles[-1]
        overlay.composition_mode = QPainter.CompositionMode_DestinationOut
        overlay.opacity = 1
        super().draw(last, now, update_rect, scribbles, wet)


class WidgetFinder:
    def __init__(self, obj):
        self.obj = obj

    def __getattr__(self, name):
        widget = self.obj.findChild(QObject, name)
        if widget is None:
            raise AttributeError(name)
        return widget

def make_tool_button(text, shortcut):
    btn = QToolButton()
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    btn.setText(text)
    btn.setShortcut(shortcut)
    btn.setCheckable(True)
    btn.setAutoExclusive(True)
    return btn

def make_toolbox_window(overlay_widget):
    window = QMainWindow()
    window.setWindowFlags(
        window.windowFlags()
        | Qt.FramelessWindowHint
        | Qt.WindowStaysOnTopHint
    )
    window.resize(0, 0)
    central = QWidget()
    window.setCentralWidget(central)
    main_layout = QVBoxLayout()
    central.setLayout(main_layout)

    def add_layout():
        layout = QHBoxLayout(window)
        main_layout.addLayout(layout)
        return layout

    def tool_setter(tool):
        def func():
            overlay_widget.tool = tool
        return func

    layout = add_layout()

    for text, shortcut, tool, activate in (
        ("&Disable", "D", None, False),
        ("&Marker", "M", Marker(), True),
        ("&Hilite", "H", Highlighter(), False),
        ("&Eraser", "E", Eraser(), False),
    ):
        btn = make_tool_button(text, shortcut)
        layout.addWidget(btn)
        if activate:
            btn.setChecked(True)
        btn.clicked.connect(tool_setter(tool))

    layout = add_layout()

    for i, (name, color) in enumerate(COLORS.items(), 1):
        tool = ColorMarker(*color, name)
        btn = make_tool_button(str(i), str(i))
        btn.setStyleSheet("background-color: rgb({}, {}, {});".format(
            *[c*255 for c in color])
        )
        layout.addWidget(btn)
        btn.setToolTip(name)
        btn.clicked.connect(tool_setter(tool))

    toolbar = window.addToolBar("Main toolbar")

    act_draw = QAction('Draw', window)
    act_draw.setCheckable(True)
    act_draw.setShortcut('Esc')
    act_draw.toggled.connect(overlay_widget.update_grab)
    overlay_widget.grab_updated.connect(act_draw.setChecked)
    toolbar.addAction(act_draw)

    def add_action(text, func, icon, shortcut=None):
        act = QAction(QIcon.fromTheme(icon), text, window)
        act.triggered.connect(func)
        if shortcut:
            act.setShortcut(shortcut)
        toolbar.addAction(act)
        return act

    for action_factory, icon, shortcut in (
        (overlay_widget.undo_group.createUndoAction, 'edit-undo-symbolic', 'Z'),
        (overlay_widget.undo_group.createRedoAction, 'edit-redo-symbolic', 'Y'),
    ):
        act = action_factory(window)
        act.setIcon(QIcon.fromTheme(icon))
        act.setShortcut(shortcut)
        toolbar.addAction(act)

    clr = add_action('Clear', overlay_widget.clear, 'document-new-symbolic', 'Q')
    overlay_widget.can_clear_changed.connect(clr.setEnabled)
    clr.setEnabled(overlay_widget.can_clear)
    toolbar.addSeparator()
    add_action('Close', sys.exit, 'process-stop-symbolic')

    layout = add_layout()
    ilv = QListView()
    ilv.setModel(overlay_widget.picture_model)
    ilv.setSelectionModel(overlay_widget.selection_model)
    layout.addWidget(ilv)
    layout.addWidget(QUndoView(overlay_widget.undo_group))

    return window

def make_overlay_widget():
    w = OverlayWidget()

    for screen in reversed(app.screens()):
        print(screen.manufacturer())
        if screen.manufacturer().startswith(('Wacom', 'Chimei')):
            geom = screen.geometry()
            w.move(geom.left(), geom.top())
            w.resize(geom.width(), geom.height())

    return w

class Application(QApplication):
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
            print('enter', toolbox.geometry(), QCursor.pos())
            if toolbox.geometry().contains(QCursor.pos()):
                return False
            overlay_widget.update_grab(True)
            return True
        elif e.type() == QEvent.TabletLeaveProximity:
            print('leave')
            return True
        elif e.type() == QEvent.TabletTrackingChange:
            print('track')
            return True
        return False


if __name__ == '__main__':
    app = Application(sys.argv)
    overlay_widget = make_overlay_widget()

    overlay_widget.showFullScreen()

    toolbox = make_toolbox_window(overlay_widget)
    toolbox.show()
    toolbox.move(overlay_widget.geometry().topLeft())

    app._toolbox = toolbox

    print(QIcon.themeSearchPaths())

    sys.exit(app.exec())
