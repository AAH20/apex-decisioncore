from setuptools import setup, find_packages

setup(
    name="apex-decisioncore",
    version="1.0.0",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "decisioncore = apex_decisioncore.cli:main",
        ],
    },
)
