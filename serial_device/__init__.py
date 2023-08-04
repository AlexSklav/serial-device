"""
Copyright 2014 Christian Fobel
Copyright 2011 Ryan Fobel

This file is part of serial_device.

serial_device is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

serial_device is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with serial_device.  If not, see <http://www.gnu.org/licenses/>.
"""
from .connections import _comports, test_connection, comports, get_serial_ports, ConnectionError, SerialDevice
from ._version import get_versions

__version__ = get_versions()['version']
del get_versions
