#!/usr/bin/env python3
# read the contents of your README file
from pathlib import Path

from setuptools import setup

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="pyintesishome",
    version="2.5.0",
    description="A python3 library for running asynchronus communications with IntesisHome Smart AC Controllers",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/jnimmo/pyIntesisHome",
    author="James Nimmo",
    author_email="james@nimmo.net.nz",
    license="MIT",
    install_requires=["aiohttp>=3.7.4,<4"],
    # 3.12 rewrote asyncio.wait_for on top of asyncio.timeout. Earlier
    # versions discard a cancellation delivered while the future being
    # waited on has already completed, which the poller's shutdown path
    # would otherwise have to keep working around untested.
    python_requires=">=3.12",
    packages=["pyintesishome"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Topic :: Scientific/Engineering :: Interface Engine/Protocol Translator",
        "Topic :: Home Automation",
    ],
)
