from setuptools import setup, find_packages
import os
try: # for pip >= 10
    from pip._internal.req import parse_requirements
except ImportError: # for pip <= 9.0.3
    from pip.req import parse_requirements

def dirname(fname):
    return os.path.join(os.path.dirname(__file__), fname)

def read(fname):
    return open(dirname(fname)).read()

install_reqs = parse_requirements(dirname('requirements.txt'), session=False)

try:
    reqs = [str(ir.req) for ir in install_reqs]
except:
    reqs = [str(ir.requirement) for ir in install_reqs]

__version__ = "0.0.1"

packages = find_packages()
setup(
    name = 'autopt',
    version = __version__,
    packages = packages,
    include_package_data = True,
    py_modules = ['autopt.__init__', 'autopt.utils'],
    url = 'https://github.com/Vahram99/AutOpt',
    license = "GNU General Public License v3.0",
    author = read('AUTHORS.txt').replace('\n', ', ').replace('-', ''),
    author_email = 'vahram.babadjanyan@gmail.com',
    description = 'Automated hyperparameter optimization',
    long_description = read('README.md'),
    keywords = "machine-learning automated hyperparameter optimization",
    install_requires = reqs
) 
