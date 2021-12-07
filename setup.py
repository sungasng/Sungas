from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in sungas/__init__.py
from sungas import __version__ as version

setup(
	name="sungas",
	version=version,
	description="Bundled functionality for the Sungas Brand",
	author="Manqala",
	author_email="dev@manqala.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
