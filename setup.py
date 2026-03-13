"""
Setup script for GCC Evolution

Installation:
    pip install -e .

Publishing to PyPI:
    python setup.py sdist bdist_wheel
    twine upload dist/*
"""

from setuptools import setup, find_packages
from pathlib import Path

# 读取 README
readme_path = Path(__file__).parent / "README.md"
long_description = ""
if readme_path.exists():
    with open(readme_path, encoding="utf-8") as f:
        long_description = f.read()

setup(
    name="gcc-evolution",
    version="5.405",

    description="GCC v5.405 - Self-Evolution Engine + Smart Handoff",
    long_description=long_description,
    long_description_content_type="text/markdown",

    author="GCC Contributors",
    author_email="support@gcc-evo.dev",
    url="https://github.com/yourusername/gcc-evolution",
    project_urls={
        "GitHub": "https://github.com/yourusername/gcc-evolution",
        "Documentation": "https://gcc-evo.dev/docs",
        "Issues": "https://github.com/yourusername/gcc-evolution/issues",
    },

    license="MIT",

    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Financial and Insurance Industry",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Office/Business :: Financial :: Trading",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],

    packages=find_packages(
        where=".",
        include=["gcc_evolution*", ".GCC*"],
        exclude=["tests", "docs", "examples", "state", "logs"]
    ),

    include_package_data=True,

    python_requires=">=3.8",

    install_requires=[
        "numpy>=1.20.0",
        "pandas>=1.3.0",
        "requests>=2.26.0",
        "click>=8.0.0",
        "pyyaml>=5.4.0",
        "jsonlines>=3.0.0",
    ],

    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-cov>=2.12",
            "black>=21.0",
            "flake8>=3.9",
            "mypy>=0.910",
        ],
        "docs": [
            "sphinx>=4.0",
            "sphinx-rtd-theme>=1.0",
        ],
    },

    entry_points={
        "console_scripts": [
            "gcc-evolution=gcc_evolution.cli:main",
            "gcc-evo=gcc_evolution.cli:main",
        ],
    },

    keywords=[
        "trading",
        "evolution",
        "AI",
        "machine-learning",
        "decision-making",
        "intelligent",
        "framework",
    ],
)

