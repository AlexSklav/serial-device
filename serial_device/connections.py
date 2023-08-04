# -*- encoding: utf-8 -*-
import serial
import six.moves

import pandas as pd

import platform
from time import sleep
from serial.tools.list_ports import comports as list_comports
from typing import Optional, Union, List


def _comports() -> pd.DataFrame:
    """
    Returns
    -------
    pandas.DataFrame
        Table containing descriptor, and hardware ID of each available COM
        port, indexed by port (e.g., "COM4").
    """
    return pd.DataFrame(map(list, list_comports()),
                        columns=['port', 'descriptor', 'hardware_id']).set_index('port')


def test_connection(port: str, baud_rate: Optional[int] = None) -> bool:
    """
    Test connection to a device using the specified port and baud-rate.

    If the connection is successful, return `True`.
    Otherwise, return `False`.
    """
    try:
        with serial.Serial(port=port) as ser:
            if baud_rate is not None:
                ser.braudrate = baud_rate
            return True
    except serial.SerialException as e:
        print(e)
        return False


def comports(vid_pid: Optional[Union[str, List[str]]] = None,
             include_all: Optional[bool] = False,
             check_available: Optional[bool] = True,
             only_available: Optional[bool] = False) -> pd.DataFrame:
    """
    Parameters
    ----------
    vid_pid : str or list, optional
        One or more USB vendor/product IDs to match.

        Each USB vendor/product must be in the form ``'<vid>:<pid>'``.
        For example, ``'2341:0010'``.
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
    df_comports = _comports()

    # Extract USB product and vendor IDs from `hwid` entries of the form:
    #
    #     FTDIBUS\VID_0403+PID_6001+A60081GEA\0000
    #     or
    #     USB VID:PID=16C0:0483 SNR=2145930
    pattern = r'(?:vid:pid=?|vid[_:]?)(?P<vid>[0-9a-f]+)(?:(?:[_&:=+]?)|(?:[_&:=+]?pid[_:]))(?P<pid>[0-9a-f]+)'
    df_comports = df_comports.hardware_id.str.lower().str.extract(pattern, expand=True)

    if vid_pid is not None:
        if isinstance(vid_pid, six.string_types):
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

    if check_available or only_available:
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

    for port_info in list_comports():
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


class SerialDevice(object):
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
