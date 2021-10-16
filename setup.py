#!/usr/bin/env python3
from setuptools import setup

setup(
    name="pyintesishome",
    version="1.8.1",
    description="A python3 library for running asynchronus communications with IntesisHome Smart AC Controllers",
    url="https://github.com/jnimmo/pyIntesisHome",
    author="James Nimmo",
    author_email="james@nimmo.net.nz",
    license="MIT",
    install_requires=["aiohttp>=3.7.4,<4"],
    packages=["pyintesishome"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Topic :: Scientific/Engineering :: Interface Engine/Protocol Translator",
    ],
)
