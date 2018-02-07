"""LexOffice Tools: setup module

Verwendung auf eigene Gefahr
"""

# Always prefer setuptools over distutils
from setuptools import setup, find_packages
# To use a consistent encoding
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()


setup(
    name='lexofficetools',  # Required

    version='0.0.1',  # Required

    description='Tools und Daemon um mit LexOffice zu interagieren',  # Required

    long_description=long_description,  # Optional

    #url='https://github.com/pypa/sampleproject',  # Optional

    author='Henryk Plötz',  # Optional

    author_email='henryk+lexofficetools@ploetzli.ch',  # Optional

    classifiers=[  # Optional
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        'Development Status :: 3 - Alpha',

        # Indicate who your project is intended for
        'Intended Audience :: Developers',

        # Pick your license as you wish
        #'License :: OSI Approved :: MIT License',

        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],

    keywords='lexoffice belegupload email buchhaltung belege',  # Optional

    packages=find_packages(exclude=['contrib', 'docs', 'tests']),  # Required

    install_requires=[
        'requests',
        'PyYAML',
        'imapclient',
        'python-magic',
    ],  # Optional

    extras_require={},

    package_data={},

    data_files=[],  # Optional

    entry_points={  # Optional
        'console_scripts': [
            'lexofficetools=lexofficetools:main',
        ],
    },
)
