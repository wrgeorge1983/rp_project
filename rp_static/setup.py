from setuptools import setup

setup(
    name='rp_static',
    packages=['rp_static'],
    include_package_data=True,
    install_requires=[
        'requests',
        'click'
    ],
    entry_points={
        'console_scripts': [
            'rp_static = rp_static.__main__:main'
        ]
    }
)
