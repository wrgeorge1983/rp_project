from setuptools import setup

setup(
    name='rp_static',
    packages=['rp_static'],
    include_package_data=True,
    install_requires=[
        'requests',
        'click',
        'pika',
        'aio_pika',
        'pyyaml',
        'logging-tree'
    ],
    entry_points={
        'console_scripts': [
            'rp_static = rp_static.__main__:main',
            'rp_rmq = rp_static.__main__:rmq',
            'rp_mock1 = rp_static.__main__:mock1'
        ]
    }
)
