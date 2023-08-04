import queue
import logging
import platform
import threading

import time
from typing import Optional, Union

import serial
import serial.threaded

from .connections import get_serial_ports
from .or_event import OrEvent

logger = logging.getLogger(__name__)

# Flag to indicate whether queues should be polled.
# XXX Note that polling performance may vary by platform.
POLL_QUEUES = (platform.system() == 'Windows')


def request(device: serial.Serial, response_queue: queue.Queue, payload: bytes,
            timeout_s: Optional[float] = None, poll: Optional[bool] = POLL_QUEUES):
    """
    Send payload to a serial device and wait for response.

    Parameters
    ----------
    device : serial.Serial
        Serial instance.
    response_queue : queue.Queue
        Queue to wait for response on.
    payload: str or bytes
        Payload to send.
    timeout_s: float, optional
        Maximum time to wait (in seconds) for response.

        By default, block until response is ready.
    poll: bool, optional
        If ``True``, poll response queue in a busy loop until response is
        ready (or timeout occurs).

        Polling is much more processor intensive, but (at least on Windows)
        results in faster response processing.  On Windows, polling is
        enabled by default.
    """
    device.write(payload)
    if not poll:
        # Polling disabled. Use blocking `Queue.get()` method with timeout to wait for response.
        try:
            return response_queue.get(timeout=timeout_s)
        except queue.Empty:
            raise queue.Empty('No response received.')

    # Polling enabled. Wait for a response with a timeout.
    start_time = time.time()
    while time.time() - start_time < timeout_s:
        if not response_queue.empty():
            return response_queue.get()

    raise queue.Empty('No response received within the timeout period.')


class EventProtocol(serial.threaded.Protocol):
    def __init__(self):
        self.transport = None
        self.connected = threading.Event()
        self.disconnected = threading.Event()
        self.port = None

    def connection_made(self, transport) -> None:
        """Called when the reader thread is started"""
        super().connection_made(transport)
        self.port = transport.serial.port
        logger.debug(f'connection_made: `{self.port}` `{transport}`')
        self.transport = transport
        self.connected.set()
        self.disconnected.clear()

    # def data_received(self, data: bytes) -> None:
    #     """Called with snippets received from the serial port"""
    #     raise NotImplementedError

    def connection_lost(self, exception: Exception) -> None:
        """
        Called when the serial port is closed or the reader loop terminated
        otherwise.
        """
        super().connection_lost(exception)
        if isinstance(exception, Exception):
            logger.debug(f'Connection to port `{self.port}` lost: {exception}')
        else:
            logger.debug(f'Connection to port `{self.port}` closed')
        self.connected.clear()
        self.disconnected.set()


class KeepAliveReader(threading.Thread):
    """
    Keep a serial connection alive (as much as possible).

    Parameters
    ----------
    protocol_class : serial.threaded.Protocol
        The protocol class for handling the serial connection.
    comport : str
        Name of COM port to connect to.

    **kwargs
    default_timeout_s: float, optional
        Default time to wait for serial operation (e.g., connect).
        By default, block (i.e., no time out).
    other
        Keyword arguments passed to ``serial_for_url`` function, e.g.,``baudrate``, etc.
    """

    def __init__(self, protocol_class: serial.threaded.Protocol, comport: str, **kwargs: dict):
        super().__init__()
        self.daemon = True
        self.protocol_class = protocol_class
        self.comport = comport
        self.kwargs = kwargs
        self.protocol = None
        self.default_timeout_s = kwargs.get('default_timeout_s', None)

        # Event to indicate serial connection has been established.
        self.connected = threading.Event()
        # Event to request a break from the run loop.
        self.close_request = threading.Event()
        # Event to indicate the thread has been closed.
        self.closed = threading.Event()
        # Event to indicate an exception has occurred.
        self.error = threading.Event()
        # Event to indicate that the thread has connected to the specified port **at least once**.
        self.has_connected = threading.Event()

    @property
    def alive(self) -> bool:
        return not self.closed.is_set()

    def run(self) -> None:
        # Verify requested serial port is available.
        try:
            available_ports = get_serial_ports(sort_ports=False, only_available=True)
            if self.comport not in available_ports:
                raise NameError(f'Port `{self.comport}` not available.'
                                f'  Available ports: {", ".join(available_ports)}')
        except NameError as exception:
            self.error.exception = exception
            self.error.set()
            self.closed.set()
            return

        while True:
            # Wait for the requested serial port to become available.
            while self.comport not in get_serial_ports(sort_ports=False, only_available=True):
                # Assume serial port was disconnected temporarily.  Wait and
                # periodically check again.
                self.close_request.wait(2)
                if self.close_request.is_set():
                    # No connection is open, so nothing to close.  Just quit.
                    self.closed.set()
                    return
            try:
                # Try to open a serial device and monitor connection status.
                logger.debug(f'Open `{self.comport}` and monitor connection status')
                device = serial.serial_for_url(self.comport, **self.kwargs)
            except serial.SerialException as exception:
                self.error.exception = exception
                self.error.set()
                self.closed.set()
                return
            except Exception as exception:
                self.error.exception = exception
                self.error.set()
                self.closed.set()
                return
            else:
                with serial.threaded.ReaderThread(device, self.protocol_class) as protocol:
                    self.protocol = protocol

                    connected_event = OrEvent(protocol.connected, self.close_request)
                    disconnected_event = OrEvent(protocol.disconnected, self.close_request)

                    # Wait for connection.
                    connected_event.wait(None if self.has_connected.is_set() else self.default_timeout_s)
                    if self.close_request.is_set():
                        # Quit run loop.  Serial connection will be closed by
                        # `ReaderThread` context manager.
                        self.closed.set()
                        return

                    self.connected.set()
                    self.has_connected.set()
                    # Wait for disconnection.
                    disconnected_event.wait()

                    if self.close_request.is_set():
                        # Quit run loop.
                        self.closed.set()
                        return

                    self.connected.clear()
                    # Loop to try to reconnect to the serial device.

    def write(self, data: Union[str, bytes], timeout_s: Optional[float] = None) -> None:

        """
        Write to serial port.

        Waits for serial connection to be established before writing.

        Parameters
        ----------
        data: str or bytes
            Data to write to serial port.
        timeout_s: float, optional
            Maximum number of seconds to wait for serial connection to be
            established.

            By default, block until serial connection is ready.
        """
        self.connected.wait(timeout_s)
        if self.protocol:
            self.protocol.transport.write(data)

    def request(self, response_queue: queue.Queue, payload: bytes, timeout_s: Optional[float] = None,
                poll: Optional[bool] = POLL_QUEUES) -> None:
        """
        Send

        Parameters
        ----------
        response_queue: queue.Queue
            Queue to wait for response on.
        payload: str or bytes
            Payload to send.
        timeout_s: float, optional
            Maximum time to wait (in seconds) for response.

            By default, block until response is ready.
        poll: bool, optional
            If ``True``, poll response queue in a busy loop until response is
            ready (or timeout occurs).

            Polling is much more processor intensive, but (at least on Windows)
            results in faster response processing.  On Windows, polling is
            enabled by default.
        """
        self.connected.wait(timeout_s)
        return request(self, response_queue=response_queue, payload=payload, timeout_s=timeout_s, poll=poll)

    def close(self) -> None:
        self.close_request.set()

    # - -  context manager, returns protocol

    def __enter__(self) -> 'KeepAliveReader':
        """
        Enter context handler. May raise RuntimeError in case the connection
        could not be created.
        """
        self.start()
        # Wait for protocol to connect.
        event = OrEvent(self.connected, self.closed)
        event.wait(self.default_timeout_s)
        if not self.connected.is_set():
            raise RuntimeError('Connection could not be established.')
        return self

    def __exit__(self, *args) -> None:
        """Leave context: close port"""
        self.close()
        self.closed.wait()
