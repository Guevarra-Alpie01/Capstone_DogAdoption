"""Project package initialization."""

import pymysql

# Django 6 requires mysqlclient>=2.2.1. When using PyMySQL as a drop-in,
# set compatibility version metadata so Django's backend check passes.
pymysql.version_info = (2, 2, 1, "final", 0)
pymysql.__version__ = "2.2.1"

# Allow Django's MySQL backend to use PyMySQL as a MySQLdb drop-in.
pymysql.install_as_MySQLdb()
