#!/usr/bin/env python3
import os
import sys
import pathlib
import pytest

os.chdir(pathlib.Path.cwd() / 'test')

sys.exit(pytest.main())
