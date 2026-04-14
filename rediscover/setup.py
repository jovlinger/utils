from setuptools import setup, find_packages

setup(
    name="rediscover",
    version="0.1.0",
    packages=find_packages(exclude=["tests*", "e2e*"]),
    install_requires=["redis>=4.6", "click>=8.0"],
    entry_points={"console_scripts": ["rediscover=rediscover.cli:cli"]},
)
