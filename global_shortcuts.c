#include <stdio.h>
#include <Python.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>

typedef struct {
    int keysym;
    unsigned int keycode;
} keymap_t;

PyObject *
watch_shortcuts(PyObject *self, PyObject *callable)
{
    Display*    dpy     = XOpenDisplay(0);
    Window      root    = DefaultRootWindow(dpy);
    XEvent      ev;

    unsigned int    modifiers       = ControlMask | ShiftMask | Mod1Mask | Mod4Mask;
    Window          grab_window     =  root;
    Bool            owner_events    = False;
    int             pointer_mode    = GrabModeAsync;
    int             keyboard_mode   = GrabModeAsync;

    keymap_t keymap[] = {
        {XK_1, 0},
        {XK_2, 0},
        {XK_3, 0},
        {XK_4, 0},
        {XK_5, 0},
        {XK_6, 0},
        {XK_M, 0},
        {XK_H, 0},
        {XK_E, 0},
        {XK_Q, 0},
        {XK_Z, 0},
        {XK_Y, 0},
        {XK_Escape, 0},
        {0, 0}
    };

    for (int i=0; keymap[i].keysym; i++) {
        unsigned int keycode = XKeysymToKeycode(dpy, keymap[i].keysym);
        keymap[i].keycode = keycode;
        XGrabKey(
            dpy, keycode, modifiers, grab_window, owner_events, pointer_mode,
            keyboard_mode
        );
    }

    while(1)
    {
        int shouldQuit = 0;
        Py_BEGIN_ALLOW_THREADS;
        XNextEvent(dpy, &ev);
        Py_END_ALLOW_THREADS;
        switch(ev.type)
        {
            case KeyPress:
                for (int i=0; keymap[i].keysym; i++) {
                    printf("Trying hot key %d...\n", i);
                    if (keymap[i].keycode == ev.xkey.keycode) {
                        printf("Hot key %d pressed!\n", i);
                        PyObject *code = PyLong_FromLong(i);
                        if (code == NULL) {
                            shouldQuit = 1;
                            break;
                        }
                        PyObject *result = PyObject_CallOneArg(callable, code);
                        Py_XDECREF(code);
                        if (result == NULL) {
                            shouldQuit = 1;
                            break;
                        }
                        Py_XDECREF(result);
                        break;
                    }
                }
                break;

            default:
                break;
        }

        if(shouldQuit)
            break;
    }

    XCloseDisplay(dpy);

    return NULL;
    Py_RETURN_NONE;
}

PyMethodDef methods[] = {
    {"watch_shortcuts", watch_shortcuts, METH_O, NULL},
    {NULL},
};

PyModuleDef mod = {
    .m_base = PyModuleDef_HEAD_INIT,
    .m_name = "global_shortcuts",
    .m_methods = methods,
};

PyObject *
PyInit_global_shortcuts() {
    return PyModuleDef_Init(&mod);
}
