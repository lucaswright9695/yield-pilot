"""Setup configuration for Yield Pilot."""

from setuptools import setup, find_packages

setup(
    name="yield-pilot",
    version="0.1.0",
    description="Multi-chain yield optimizer with rebalancing engine",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Yield Pilot Contributors",
    python_requires=">=3.9",
    packages=find_packages(),
    install_requires=[],
    extras_require={
        "dev": ["pytest>=7.0.0"],
    },
    entry_points={
        "console_scripts": [
            "yield-pilot=src.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
