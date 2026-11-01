"""Local installation metadata; no backend source or clinical data is bundled."""
from setuptools import find_namespace_packages, setup

setup(
    name="cli-anything-kinelab",
    version="0.1.0",
    description="Read-only KineLab engineering verification and inspection harness",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    install_requires=["click>=8.0", "prompt-toolkit>=3.0"],
    python_requires=">=3.10,<3.14",
    package_data={"cli_anything.kinelab": ["README.md", "skills/SKILL.md"]},
    entry_points={"console_scripts": [
        "cli-anything-kinelab=cli_anything.kinelab.kinelab_cli:main",
    ]},
)
