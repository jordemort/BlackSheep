from asyncio import Queue, QueueEmpty, QueueFull
from ssl import SSLContext
from .connection import HttpConnection, SECURE_SSLCONTEXT, INSECURE_SSLCONTEXT, ConnectionClosedError
from blacksheep.exceptions import InvalidArgument


class HttpConnectionPool:

    def __init__(self, loop, scheme, host, port, ssl=None, max_size=0):
        self.loop = loop
        self.scheme = scheme
        self.host = host
        self.port = port
        self.ssl = self._ssl_option(ssl)
        self.max_size = max_size
        self._idle_connections = Queue(maxsize=max_size)

    def _ssl_option(self, ssl):
        if self.scheme == b'https':
            if ssl is None:
                return SECURE_SSLCONTEXT
            if ssl is False:
                return INSECURE_SSLCONTEXT
            if isinstance(ssl, SSLContext):
                return ssl
            raise InvalidArgument('Invalid ssl argument, expected one of: '
                                  '{None, False, True, instance of ssl.SSLContext}')
        if ssl:
            raise InvalidArgument('SSL argument specified for non-https scheme.')
        return None

    def _get_connection(self):
        # if there are no connections, let QueueEmpty exception happen
        # if all connections are closed, remove all of them and let QueueEmpty exception happen
        while True:
            connection = self._idle_connections.get_nowait()  # type: HttpConnection

            if connection.open:
                # print(f'Reusing connection {id(connection)}')
                return connection

    def try_return_connection(self, connection):
        try:
            self._idle_connections.put_nowait(connection)
        except QueueFull:
            pass

    async def get_connection(self):
        try:
            return self._get_connection()
        except QueueEmpty:
            return await self.create_connection()

    async def create_connection(self):
        # print(f'[*] creating connection for: {self.host}:{self.port}')
        transport, connection = await self.loop.create_connection(
            lambda: HttpConnection(self.loop, self),
            self.host,
            self.port,
            ssl=self.ssl)
        await connection.ready.wait()
        # NB: a newly created connection is going to be used by a request-response cycle;
        # so we don't put it inside the pool (since it's not immediately reusable for other requests)
        return connection


class HttpConnectionPools:

    def __init__(self, loop):
        self.loop = loop
        self._pools = {}

    def get_pool(self, scheme, host, port, ssl):
        assert scheme in (b'http', b'https'), 'URL schema must be http or https'
        if port is None:
            port = 80 if scheme == b'http' else 443
        
        key = (scheme, host, port)
        try:
            return self._pools[key]
        except KeyError:
            new_pool = HttpConnectionPool(self.loop, scheme, host, port, ssl)
            self._pools[key] = new_pool
            return new_pool
