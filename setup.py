#!/usr/bin/env python
"""
gcc-evo â€” AI Self-Evolution Engine

Setup configuration for PyPI distribution.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Pin release version for this source package.
# Do not infer from external files to avoid accidental parse errors.
version = "5.400"

# Read long description from README
readme_file = Path(__file__).parent / "README.md"
long_description = ""
if readme_file.exists():
    with open(readme_file, encoding="utf-8") as f:
        long_description = f.read()

setup(
    name="gcc-evo",
    version=version,
    author="baodexiang",
    author_email="baodexiang@hotmail.com",
    url="https://github.com/baodexiang/gcc-evo",
    project_urls={
        "Documentation": "https://github.com/baodexiang/gcc-evo",
        "Source Code": "https://github.com/baodexiang/gcc-evo",
        "Bug Tracker": "https://github.com/baodexiang/gcc-evo/issues",
        "Changelog": "https://github.com/baodexiang/gcc-evo/blob/main/opensource/CHANGELOG.md",
    },

    description="AI Self-Evolution Engine â€” Persistent memory + continuous learning for LLM",
    long_description=long_description,
    long_description_content_type="text/markdown",

    license="BUSL-1.1",

    keywords=[
        "ai",
        "llm",
        "memory",
        "evolution",
        "retrieval",
        "distillation",
        "self-improvement",
        "prompt",
        "gpt",
        "claude",
    ],

    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: Other/Proprietary License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],

    python_requires=">=3.9",

    packages=find_packages(
        include=["gcc_evolution", "gcc_evolution.*", "gcc", "gcc.*"],
        exclude=["tests", "docs", ".github", "examples", "*.tests", "*.tests.*"],
    ),
    package_data={
        "gcc_evolution": ["dashboard/*.html"],
    },
    include_package_data=True,

    install_requires=[
        "click>=8.0.0",           # CLI framework
        "pyyaml>=6.0",            # YAML config
        "requests>=2.28.0",       # HTTP client
        "python-dotenv>=0.20.0",  # Environment variables
        "tqdm>=4.64.0",           # Progress bars
    ],

    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=22.0.0",
            "isort>=5.11.0",
            "flake8>=5.0.0",
            "mypy>=0.990",
            "pylint>=2.15.0",
            "bandit>=1.7.0",
            "safety>=2.3.0",
        ],
        "docs": [
            "sphinx>=5.0.0",
            "sphinx-rtd-theme>=1.0.0",
            "sphinx-autodoc-typehints>=1.19.0",
        ],
        "local-llm": [
            "ollama>=0.1.0",
            "sentence-transformers>=2.2.0",
        ],
    },

    entry_points={
        "console_scripts": [
            "gcc-evo=gcc_evolution.cli:main",
        ],
    },

    zip_safe=False,
)



