# to build global_shortcuts
from setuptools import setup, Extension

module1 = Extension(
    'global_shortcuts',
    sources=['global_shortcuts.c'],
    libraries=['X11'],
    runtime_library_dirs=['/usr/lib64/'],
    library_dirs=['/usr/lib64/'],
)

setup (
    name='global_shortcuts',
    version='0.0',
    description='global_shortcuts',
    ext_modules=[module1],
)
