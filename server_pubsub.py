from sanic import Sanic, response
from sanic_jinja2 import SanicJinja2
from jinja2 import PackageLoader, select_autoescape
from sanic_session import InMemorySessionInterface, RedisSessionInterface
import asyncio_redis
import asyncio
import json, logging
import traceback as tb
logging.basicConfig(level = logging.INFO,format = '%(asctime)s - %(name)s - %(filename)s[%(lineno)d] - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

jinja = SanicJinja2(
    loader=PackageLoader('templates'),
    autoescape=select_autoescape(['html', 'xml']),
)

app = Sanic(__name__)
app.static('/static', './static')

HOST = {}

class Redis:
    _pool = None
    async def get_redis_pool(self):
        if not self._pool:
            self._pool = await asyncio_redis.Pool.create(
                host='localhost', port=6379, poolsize=10
            )

        return self._pool

    def close(self):
        if self._pool:
            self._pool.close()

redis = Redis()

# session_interface = RedisSessionInterface(redis.get_redis_pool)
session_interface = InMemorySessionInterface()


@app.listener('before_server_start')
async def server_init(app, loop):
    jinja.init_app(app)

@app.listener('before_server_stop')
async def notify_server_stopping(app, loop):
    redis.close()

@app.middleware('request')
async def add_session_to_request(request):
    await session_interface.open(request)


@app.middleware('response')
async def save_session(request, response):
    await session_interface.save(request, response)

@app.route('/')
@jinja.template('control.html')
async def index(request):
    id = request.args.get('id', '96d588f8f38a49032e096b230d6651616b92682700cac320fbf99a884d58333f')
    return locals()

@app.route('/api/size/<id>')
async def size(request, id):
    pool = await redis.get_redis_pool()
    info = await pool.get(id)
    if not info:
        return response.json({'code': 404})
    size = json.loads(info)
    return response.json({'code': 200, 'data': size})


@app.websocket('/websocket/host')
async def host(request, ws):
    line = await ws.recv()
    info = json.loads(line)
    id = info.get('login')
    size = info.get('size')
    await login(id, ws, size)
    pool = await redis.get_redis_pool()
    
    async def pipe():
        while True:
            try:
                data = await ws.recv()
                await pool.publish('monitor-%s'%id, data.decode('latin'))
            except Exception as e:
                logger.error(tb.format_exc())
                break

    handler = asyncio.ensure_future(pipe())
    subscriber = await pool.start_subscribe()
    await subscriber.subscribe(["command-%s"%id])
    while True:
        try:
            command = await subscriber.next_published()
            await ws.send(command.value)
        except Exception as e:
            logger.error(tb.format_exc())
            break
    await subscriber.unsubscribe(["command-%s"%id])
    handler.cancel()

async def login(id, ws, size):
    logging.info('login in host[%s]', id)
    await ws.send(json.dumps({'code':200}))
    pool = await redis.get_redis_pool()
    await pool.set(id, json.dumps(size))
    # HOST[id] = {'ws': ws, 'size':size}

@app.websocket('/websocket/manage')
async def manage(request, ws):
    id = request.args.get('id')
    pool = await redis.get_redis_pool()
    subscriber = await pool.start_subscribe()
    await subscriber.subscribe(["monitor-%s"%id])
    async def pipe():
        while True:
            try:
                data = await ws.recv()
                await pool.publish('command-%s'%id, data)
            except Exception as e:
                logger.error(tb.format_exc())
                break
    handler = asyncio.ensure_future(pipe())
    while True:
        try:
            monitor = await subscriber.next_published()
            await ws.send(monitor.value.encode('latin'))
        except:
            logger.error(tb.format_exc())
            break
    await subscriber.unsubscribe(["monitor-%s"%id])
    monitors = await pool.pubsub_numsub(["monitor-%s"%id])
    monitors = await monitors.asdict()
    monitors = monitors.get("monitor-%s"%id, 0)
    if monitors == 0:
        try:
            await pool.publish('command-%s'%id, '{"action":"stop_monitor"}')
        except:
            logger.error(tb.format_exc())
    logger.info("monitor remains: [%s]", str(monitors))
    handler.cancel()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)