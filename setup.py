#!/usr/bin/env python3
# read the contents of your README file
from pathlib import Path

from setuptools import setup

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="pyintesishome",
    version="1.8.4",
    description="A python3 library for running asynchronus communications with IntesisHome Smart AC Controllers",
    long_description=long_description,
    long_description_content_type="text/markdown",
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
