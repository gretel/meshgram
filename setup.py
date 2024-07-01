from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="meshtastic-telegram-bridge",
    version="0.1.0",
    author="Tom Hensel",
    author_email="robot@jitter.eu",
    description="A bridge between Meshtastic and Telegram for message and location sharing",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/meshtastic-telegram-bridge",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.11",
    install_requires=[
        "meshtastic",
        "python-telegram-bot",
        "envyaml",
    ],
    entry_points={
        "console_scripts": [
            "meshtastic-telegram-bridge=meshtastic_telegram_bridge:main",
        ],
    },
)