# -*- encoding: utf-8 -*-
import re
import serial
import platform

import pandas as pd
import  serial.tools.list_ports as lsp

from time import sleep
from typing import Optional, Union, List


def _comports(pattern: Optional[str] = None) -> pd.DataFrame:
    """
    Returns
    -------
    pandas.DataFrame
        Table containing descriptor, and hardware ID of each available COM
        port, indexed by port (e.g., "COM4").
    """
    if pattern is None:
        list_comports = lsp.comports()
    else:
        list_comports = lsp.grep(pattern)
    
    columns = ['port', 'descriptor', 'hardware_id', 'manufacturer', 'vid', 'pid']
    
    info = []
    for port_info in list_comports:
        vid = port_info.vid
        if vid is not None:
            vid = f'{vid:04X}'
        pid = port_info.pid
        if pid is not None:
            pid = f'{pid:04X}'
        info.append([port_info.device, port_info.description, 
                     port_info.hwid, port_info.manufacturer, 
                     vid, pid])
    
    return pd.DataFrame(info, columns=columns).set_index('port')


def test_connection(port: str, baud_rate: Optional[int] = None) -> bool:
    """
    Test connection to a device using the specified port and baud-rate.

    If the connection is successful, return `True`.
    Otherwise, return `False`.
    """
    try:
        with serial.Serial(port=port) as ser:
            if baud_rate is not None:
                ser.baudrate = baud_rate
            return True
    except serial.SerialException as e:
        print(e)
        return False


def comports(vid_pid: Optional[Union[str, List[str]]] = None,
             include_all: Optional[bool] = False,
             skip_vid: Optional[List[str]] = None,
             skip_pid: Optional[List[str]] = None,
             skip_descriptor: Optional[List[str]] = None,
             skip_manufacturer: Optional[List[str]] = None,
             check_available: Optional[bool] = True,
             only_available: Optional[bool] = False) -> pd.DataFrame:
    """
    Parameters
    ----------
    vid_pid : str or list, optional
        One or more USB vendor/product IDs to match.

        Each USB vendor/product must be in the form ``'<vid>:<pid>'``.
        For example, ``'2341:0010'``.
    skip_vid: list, optional
        Skip ports with this USB vendor ID.
    skip_pid: list, optional
        Skip ports with this USB product ID.
    skip_descriptor: list, optional
        Skip ports with this descriptor.
    skip_manufacturer: list, optional
        Skip ports with this manufacturer.
    include_all : bool, optional
        If ``True``, include all available serial ports, but sort rows such
        that ports matching specified USB vendor/product IDs come first.

        If ``False``, only include ports that match specified USB
        vendor/product IDs.
    check_available: bool, optional
        If ``True``, check if each port is actually available by attempting to
        open a temporary connection.
    only_available: bool, optional
        If True, only includes ports that are available.

    Returns
    -------
    pandas.DataFrame
        Table containing descriptor and hardware ID of each COM port, indexed
        by port (e.g., "COM4").

    Version log
    -----------
    .. versionchanged:: 0.9
        Add: data:`check_available` keyword argument to optionally check if
        each port is actually available by attempting to open a temporary
        connection.

        Add: data:`only_available` keyword argument to only include ports that
        are actually available for connection.

        If data:`check_available` is ``True``, add an ``available`` column
        to the table indicating whether each port accepted a connection.

    """
    # Extract USB product and vendor IDs from `hwid` entries of the form:
    #
    #     FTDIBUS\VID_0403+PID_6001+A60081GEA\0000
    #     or
    #     USB VID:PID=16C0:0483 SNR=2145930
    pattern = r'(?:vid:pid=?|vid[_:]?)(?P<vid>[0-9a-f]+)(?:(?:[_&:=+]?)|(?:[_&:=+]?pid[_:]))(?P<pid>[0-9a-f]+)'
    if include_all:
        df_comports = _comports()
    else:
        df_comports = _comports(pattern)

    if skip_vid is not None:
        skip_vid = '|'.join(skip_vid)
        df_comports = df_comports.loc[~df_comports.vid.str.contains(skip_vid, flags=re.IGNORECASE, regex=True)]
    if skip_pid is not None:
        skip_pid = '|'.join(skip_pid)
        df_comports = df_comports.loc[~df_comports.pid.str.contains(skip_pid, flags=re.IGNORECASE, regex=True)]
    if skip_descriptor is not None:
        skip_descriptor = '|'.join(skip_descriptor)
        df_comports = df_comports.loc[~df_comports.descriptor.str.contains(skip_descriptor,
                                                                           flags=re.IGNORECASE, regex=True)]
    if skip_manufacturer is not None:
        skip_manufacturer = '|'.join(skip_manufacturer)
        df_comports = df_comports.loc[~df_comports.manufacturer.str.contains(skip_manufacturer,
                                                                             flags=re.IGNORECASE, regex=True)]
        
    if vid_pid is not None:
        if isinstance(vid_pid, str):
            # Single USB vendor/product ID specified.
            vid_pid = [vid_pid]

        # Mark ports that match specified USB vendor/product IDs.
        include_idx = (df_comports.vid + ':' + df_comports.pid).isin(map(str.lower, vid_pid))

        if include_all:
            # All ports should be included, but sort rows such that ports
            # matching specified USB vendor/product IDs come first.
            df_comports = df_comports.iloc[len(include_idx) - include_idx.argsort() - 1]
        else:
            # Only include ports that match specified USB vendor/product IDs.
            df_comports = df_comports.loc[include_idx]

    # Remove ports that do not have USB vendor/product IDs.
    df_comports = df_comports.dropna()

    if check_available:
        # Check each port if it accepts a connection.
        # A port may not, for example, accept a connection if the port is already open.
        available_idx = df_comports.index.map(test_connection)

        if only_available:
            df_comports = df_comports.loc[available_idx]

    return df_comports


def get_serial_ports(sort_ports: Optional[bool] = True, only_available: Optional[bool] = False) -> List[str]:
    """
    Get a list of available serial ports.

    Parameters
    ----------
    sort_ports: bool, optional
        If True, sort the list of ports alphabetically.
    only_available: bool, optional
        If True, only include ports that are available.

    Returns
    -------
    List[str]
        List of available serial port names.
    """
    ports = []

    for port_info in lsp.comports():
        port_name = port_info.device
        if platform.system() == 'Windows':
            # Include all ports on Windows
            append_port = not only_available or test_connection(port_name)
        else:
            if 'usb' in port_name.lower() or 'acm' in port_name.lower():
                append_port = not only_available or test_connection(port_name)
            else:
                append_port = False

        if append_port:
            ports.append(port_name)

    if sort_ports:
        return sorted(ports)
    else:
        return ports


class ConnectionError(Exception):
    pass


class SerialDevice:
    """
    This class provides a base interface for encapsulating interaction with a
    device connected through a serial-port.

    It provides methods to automatically resolve a port based on an
    implementation-defined connection-test, which is applied to all available
    serial-ports until a successful connection is made.

    Notes
    =====

    This class intends to be cross-platform and has been verified to work on
    Windows and Ubuntu.
    """

    def __init__(self):
        self.port = None
        # moved the test_connection function outside the class so let's make it a member here to avoid any issues
        self.test_connection = test_connection

    def get_port(self, baud_rate: int, serial_test_delay: Optional[float] = 0.1) -> str:
        """
        Using the specified baud-rate, attempt to connect to each available
        serial port.  If the `test_connection()` method returns `True` for a
        port, update the `port` attribute and return the port.

        In the case where the `test_connection()` does not return `True` for
        any of the evaluated ports, raise a `ConnectionError`.
        """
        self.port = None

        for test_port in get_serial_ports():
            if self.test_connection(test_port, baud_rate):
                self.port = test_port
                break
            sleep(serial_test_delay)

        if self.port is None:
            raise ConnectionError('Could not connect to serial device.')

        return self.port
