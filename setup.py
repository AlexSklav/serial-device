#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from setuptools import setup

import versioneer


setup(name='serial_device',
      version=versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      description='Simple, cross-platform interface for interacting with '
      'devices through a serial-port.',
      author='Ryan Fobel, Christian Fobel',
      author_email='ryan@fobel.net, christian@fobel.net',
      install_requires=['pandas>=0.18', 'pyserial', 'paho-mqtt-helpers'],
      url='https://github.com/wheeler-microfluidics/serial_device.git',
      license='GPLv2',
      packages=['serial_device'])
