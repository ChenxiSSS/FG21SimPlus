# Copyright (c) 2016 Weitian LI <liweitianux@live.com>
# MIT license

"""
Communicate with the "fg21sim" simulation program through the Web UI using
the WebSocket_ protocol, which provides full-duplex communication channels
over a single TCP connection.

.. _WebSocket: https://en.wikipedia.org/wiki/WebSocket


References
----------
- Tornado WebSocket:
  http://www.tornadoweb.org/en/stable/websocket.html
- Can I Use: WebSocket:
  http://caniuse.com/#feat=websockets
"""

import logging

import tornado.websocket
from tornado.escape import json_decode, json_encode
from tornado.options import options

from ..utils import get_host_ip, ip_in_network


logger = logging.getLogger(__name__)


class WSHandler(tornado.websocket.WebSocketHandler):
    """
    WebSocket for bi-directional communication between the Web UI and
    the server, which can deal with the configurations and execute the
    simulation task.

    Generally, WebSocket send and receive data as *string*.  Therefore,
    the more complex data are stringified as JSON string before sending,
    which will be parsed after receive.

    Each message (as a JSON object or Python dictionary) has a ``type``
    field which will be used to determine the following action to take.

    Attributes
    ----------
    from_localhost : bool
        Set to ``True`` if the access is from the localhost,
        otherwise ``False``.
    configs : `~ConfigManager`
        A ``ConfigManager`` instance, for configuration manipulations when
        communicating with the Web UI.
    """
    from_localhost = None

    def check_origin(self, origin):
        """
        Check the origin of the WebSocket connection to determine whether
        the access is allowed.

        Attributes
        ----------
        from_localhost : bool
            Set to ``True`` if the access is from the "localhost" (i.e.,
            127.0.0.1), otherwise ``False``.
        """
        self.from_localhost = False
        logger.info("WebSocket: origin: {0}".format(origin))
        ip = get_host_ip(url=origin)
        network = options.hosts_allowed
        if ip == "127.0.0.1":
            self.from_localhost = True
            allow = True
            logger.info("WebSocket: origin is 'localhost'")
        elif network.upper() == "ANY":
            # Any hosts are allowed
            allow = True
            logger.warning("WebSocket: ANY hosts are allowed")
        elif ip_in_network(ip, network):
            allow = True
            logger.info("WebSocket: client from allowed network: %s" % network)
        else:
            allow = False
            logger.error("WebSocket: " +
                         "client is NOT in the allowed network: %s" % network)
        return allow

    def open(self):
        """Invoked when a new WebSocket is opened by the client."""
        # Add to the set of current connected clients
        self.application.ws_clients.add(self)
        logger.info("Added new opened WebSocket client: {0}".format(self))
        self.configs = self.application.configmanager
        # Push current configurations to the client
        self._push_configs()

    def on_close(self):
        """Invoked when a new WebSocket is closed by the client."""
        # Remove from the set of current connected clients
        self.application.ws_clients.remove(self)
        logger.warning("Removed closed WebSocket client: {0}".format(self))

    # FIXME/XXX:
    # * How to be non-blocking ??
    # NOTE: WebSocket.on_message: may NOT be a coroutine at the moment (v4.3)
    # References:
    # [1] https://stackoverflow.com/a/35543856/4856091
    # [2] https://stackoverflow.com/a/33724486/4856091
    def on_message(self, message):
        """
        Handle incoming messages and dispatch task according to the
        message type.

        NOTE
        ----
        The received message (parsed to a Python dictionary) has a ``type``
        item which will be used to determine the following action to take.

        Currently supported message types are:
        ``configs``:
            Request or set the configurations
        ``console``:
            Control the simulation tasks, or request logging messages
        ``results``:
            Request the simulation results

        The sent message also has a ``type`` item of same value, which the
        client can be used to figure out the proper actions.
        There is a ``success`` item which indicates the status of the
        requested operation, and an ``error`` recording the error message
        if ``success=False``.
        """
        logger.debug("WebSocket: received message: {0}".format(message))
        msg = json_decode(message)
        try:
            msg_type = msg["type"]
        except (KeyError, TypeError):
            logger.warning("WebSocket: skip invalid message")
            response = {"success": False,
                        "type": None,
                        "error": "type is missing"}
        else:
            if msg_type == "results":
                # Request the simulation results
                response = self._handle_results(msg)
            else:
                # Message of unknown type
                logger.warning("WebSocket: " +
                               "unknown message type: {0}".format(msg_type))
                response = {"success": False,
                            "type": msg_type,
                            "error": "unknown message type %s" % msg_type}
        #
        msg_response = json_encode(response)
        self.write_message(msg_response)

    def broadcast(self, message):
        """Broadcast/push the given message to all connected clients."""
        for ws in self.application.ws_clients:
            ws.write_message(message)

    def _push_configs(self):
        """
        Get the current configurations as well as the validation status,
        then push to the client to updates the configurations form.
        """
        data = self.configs.dump(flatten=True)
        data["userconfig"] = self.configs.userconfig
        __, errors = self.configs.check_all(raise_exception=False)
        msg = {"success": True,
               "type": "configs",
               "action": "push",
               "data": data,
               "errors": errors}
        message = json_encode(msg)
        logger.debug("Message of current configurations: {0}".format(message))
        self.write_message(message)
        logger.info("WebSocket: Pushed current configurations data " +
                    "with validation errors to the client")

    def _handle_results(self, msg):
        # Got a message of supported types
        msg_type = msg["type"]
        logger.info("WebSocket: " +
                    "handle message of type: {0}".format(msg_type))
        response = {"success": True, "type": msg_type}
        return response