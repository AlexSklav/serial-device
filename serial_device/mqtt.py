import json
import logging
import re

import paho_mqtt_helpers as pmh
import serial
import serial_device


logger = logging.getLogger(__name__)


# Regular expression to match the following topics the manager listens for:
#
#     serial_device/<port>/connect  # Request connection: port, baudrate, stopbit, etc.
#     serial_device/<port>/close  # Request to close connection
#     serial_device/<port>/send   # Bytes to send
CRE_MANAGER = re.compile(r'^serial_device'
                         r'/(?P<port>[^\/]+)'
                         r'/(?P<command>connect|close|send)$')

# Regular expression to match the following topics clients may listen for:
#
#     serial_device/comports  # Available serial ports
#     serial_device/<port>/status  # Status: connected, error, baudrate, stopbit, etc.
#     serial_device/<port>/received   # Bytes received
CRE_CLIENT = re.compile(r'^serial_device'
                        r'/(comports|'
                        r'(?P<port>[^\/]+)/(?P<command>status|received))$')


class SerialDeviceManager(pmh.BaseMqttReactor):
    def __init__(self, *args, **kwargs):
        super(SerialDeviceManager, self).__init__(*args, **kwargs)
        # Open devices.
        self.open_devices = {}

    def refresh_comports(self):
        # Query list of available serial ports
        comports = serial_device.comports().T.to_dict()
        comports_json = json.dumps(comports)

        # Publish list of available serial communication ports.
        self.mqtt_client.publish('serial_device/comports',
                                 payload=comports_json, retain=True)
        # Publish current status of each port.
        for port_i in comports:
            self._publish_status(port_i)

    ###########################################################################
    # MQTT client handlers
    # ====================
    def on_connect(self, client, userdata, flags, rc):
        '''
        Callback for when the client receives a ``CONNACK`` response from the
        broker.

        Parameters
        ----------
        client : paho.mqtt.client.Client
            The client instance for this callback.
        userdata : object
            The private user data as set in :class:`paho.mqtt.client.Client`
            constructor or :func:`paho.mqtt.client.Client.userdata_set`.
        flags : dict
            Response flags sent by the broker.

            The flag ``flags['session present']`` is useful for clients that
            are using clean session set to 0 only.

            If a client with clean session=0, that reconnects to a broker that
            it has previously connected to, this flag indicates whether the
            broker still has the session information for the client.

            If 1, the session still exists.
        rc : int
            The connection result.

            The value of rc indicates success or not:

              - 0: Connection successful
              - 1: Connection refused - incorrect protocol version
              - 2: Connection refused - invalid client identifier
              - 3: Connection refused - server unavailable
              - 4: Connection refused - bad username or password
              - 5: Connection refused - not authorised
              - 6-255: Currently unused.

        Notes
        -----

        Subscriptions should be defined in this method to ensure subscriptions
        will be renewed upon reconnecting after a loss of connection.
        '''
        super(SerialDeviceManager, self).on_connect(client, userdata, flags, rc)

        if rc == 0:
            self.mqtt_client.subscribe('serial_device/+/connect')
            self.mqtt_client.subscribe('serial_device/+/send')
            self.mqtt_client.subscribe('serial_device/+/close')
            self.refresh_comports()

    def on_message(self, client, userdata, msg):
        '''
        Callback for when a ``PUBLISH`` message is received from the broker.
        '''
        super(SerialDeviceManager, self).on_message(client, userdata, msg)

        match = CRE_MANAGER.match(msg.topic)
        if match is None:
            logger.info('Topic NOT matched: `%s`', msg.topic)
        else:
            logger.info('Topic matched: `%s`', msg.topic)
            # Message topic matches command.  Handle request.
            command = match.group('command')
            port = match.group('port')

            if command == 'connect':
                # serial_device/<port>/connect  # Request connection
                try:
                    request = json.loads(msg.payload)
                except ValueError, exception:
                    logger.error('Error decoding "%s (%s)" request: %s',
                                 command, port, exception)
                    return
                self._serial_connect(port, request)
            elif command == 'close':
                self._serial_close(port)

            #     serial_device/<port>/close  # Request to close connection
            #     serial_device/<port>/send   # Bytes to send

    def _publish_status(self, port):
        '''
        Publish status for specified port.

        Parameters
        ----------
        port : str
            Device name/port.
        '''
        if port not in self.open_devices:
            status = {'connected': False}
        else:
            device = self.open_devices[port]
            properties = ('port', 'baudrate', 'bytesize', 'parity', 'stopbits',
                          'timeout', 'xonxoff', 'rtscts', 'dsrdtr')
            status = {k: getattr(device, k) for k in properties}
            status['connected'] = True
        status_json = json.dumps(status)
        self.mqtt_client.publish(topic='serial_device/%s/status' % port,
                                 payload=status_json, retain=True)

    def _serial_connect(self, port, request):
        '''
        Handle connection request.

        Parameters
        ----------
        port : str
            Device name/port.
        request : dict
        '''
        #     baudrate : int
        #         Baud rate such as 9600 or 115200 etc.
        #     bytesize : str, optional
        #         Number of data bits.
        #
        #         Possible values: ``'FIVEBITS'``, ``'SIXBITS'``, ``'SEVENBITS'``,
        #         ``'EIGHTBITS'``.
        #
        #         Default: ``'EIGHTBITS'``
        #     parity : str, optional
        #         Enable parity checking.
        #
        #         Possible values: ``'PARITY_NONE'``, ``'PARITY_EVEN'``, ``'PARITY_ODD'``,
        #         ``'PARITY_MARK'``, ``'PARITY_SPACE'``.
        #
        #         Default: ``'PARITY_NONE'``
        #     stopbits : str, optional
        #         Number of stop bits.
        #
        #         Possible values: STOPBITS_ONE, STOPBITS_ONE_POINT_FIVE, STOPBITS_TWO
        #     xonxoff : bool, optional
        #         Enable software flow control.
        #
        #         Default: ``False``
        #     rtscts : bool, optional
        #         Enable hardware (RTS/CTS) flow control.
        #
        #         Default: ``False``
        #     dsrdtr : bool, optional
        #         Enable hardware (DSR/DTR) flow control.
        #
        #         Default: ``False``
        command = 'connect'
        if port in self.open_devices:
            logger.info('Already connected to: `%s`', port)
            self._publish_status(port)
            return

        # TODO Write JSON schema definition for valid connect request.
        if 'baudrate' not in request:
            logger.error('Invalid `%s` request: `baudrate` must be '
                         'specified.', command)
            return
        if 'bytesize' in request:
            try:
                bytesize = getattr(serial, request['bytesize'])
                if not bytesize in serial.Serial.BYTESIZES:
                    logger.error('`%s` request: `bytesize` `%s` not '
                                 'available on current platform.', command,
                                 request['bytesize'])
                    return
            except AttributeError, exception:
                logger.error('`%s` request: invalid `bytesize`, `%s`', command,
                             request['bytesize'])
                return
        else:
            bytesize = serial.EIGHTBITS
        if 'parity' in request:
            try:
                parity = getattr(serial, request['parity'])
                if not parity in serial.Serial.PARITIES:
                    logger.error('`%s` request: `parity` `%s` not available '
                                 'on current platform.', command,
                                 request['parity'])
                    return
            except AttributeError, exception:
                logger.error('`%s` request: invalid `parity`, `%s`', command,
                             request['parity'])
                return
        else:
            parity = serial.PARITY_NONE
        if 'stopbits' in request:
            try:
                stopbits = getattr(serial, request['stopbits'])
                if not stopbits in serial.Serial.STOPBITS:
                    logger.error('`%s` request: `stopbits` `%s` not '
                                 'available on current platform.', command,
                                 request['stopbits'])
                    return
            except AttributeError, exception:
                logger.error('`%s` request: invalid `stopbits`, `%s`', command,
                             request['stopbits'])
                return
        else:
            stopbits = serial.STOPBITS_ONE

        try:
            baudrate = int(request['baudrate'])
            xonxoff = bool(request.get('xonxoff'))
            rtscts = bool(request.get('rtscts'))
            dsrdtr = bool(request.get('dsrdtr'))
        except TypeError, exception:
            logger.error('`%s` request: %s', command, exception)
            return

        try:
            self.open_devices[port] = serial.Serial(port=port,
                                                    baudrate=baudrate,
                                                    bytesize=bytesize,
                                                    parity=parity,
                                                    stopbits=stopbits,
                                                    xonxoff=xonxoff,
                                                    rtscts=rtscts,
                                                    dsrdtr=dsrdtr)
        except Exception, exception:
            logger.error('`%s` request: %s', command, exception)
            return
        else:
            # Publish notification of connected status.
            self._publish_status(port)

    def _serial_close(self, port):
        '''
        Handle close request.

        Parameters
        ----------
        port : str
            Device name/port.
        '''
        if port in self.open_devices:
            try:
                self.open_devices[port].close()
                del self.open_devices[port]
            except Exception, exception:
                logger.error('Error closing device `%s`: %s', port, exception)
                return
            self._publish_status(port)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    reactor = SerialDeviceManager()
    reactor.start()
