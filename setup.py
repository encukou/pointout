from setuptools import setup, Extension

module1 = Extension(
    'global_shortcuts',
    sources=['global_shortcuts.c'],
    libraries=['X11'],
    runtime_library_dirs=['/usr/lib64/'],
    library_dirs=['/usr/lib64/'],
)

setup (
    name='pointout',
    version='0.1',
    description='pointout',
    ext_modules=[module1],
    python_modules=["pointout"],
    install_requires=[
        'pyside6',
    ],
    entry_points = {
        'console_scripts': [
            'pointout=pointout:main',
        ],
    }
)
