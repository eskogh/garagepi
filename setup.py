from setuptools import find_packages, setup


setup(
    name="garagepi",
    version="0.1.0",
    description="Flask + GPIO garage door controller with MQTT (Home Assistant discovery)",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Erik Skogh",
    license="MIT",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    include_package_data=True,
    package_data={"garagepi": ["templates/*.html", "systemd/*.service"]},
    python_requires=">=3.9",
    install_requires=[
        "Flask>=3.0.0",
        "paho-mqtt>=2.0.0",
        "python-dotenv>=1.0.0",
        "RPi.GPIO; sys_platform == 'linux' and platform_machine != 'x86_64'",
    ],
    extras_require={
        "dev": [
            "pytest",
            "ruff",
            "black",
        ],
    },
    entry_points={"console_scripts": ["garagepi=garagepi.cli:main"]},
)
