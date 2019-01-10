from sanic import Sanic, response
from sanic_jinja2 import SanicJinja2
from jinja2 import PackageLoader, select_autoescape
from sanic_session import InMemorySessionInterface, RedisSessionInterface
import asyncio_redis
import asyncio
import json, logging
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
                host='localhost', port=6379, poolsize=1
            )

        return self._pool

    def close(self):
        if self._pool:
            self._pool.close()

redis = Redis()

session_interface = RedisSessionInterface(redis.get_redis_pool)
# session_interface = InMemorySessionInterface()


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
    
@app.route('/host/control')
async def control(request):
    id = request.args.get('id')
    if id not in HOST:
        return await response.file_stream('static/offline.jpg')
    ws = HOST.get(id)
    async def stream(resp):
        while True:
            try:
                frame = await ws.recv()
                logging.debug('sending a frame[%s] to web!', len(frame))
                frame = b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame.tobytes() + b'\r\n\r\n'
                resp.write(frame)
            except Exception as e:
                break
            await asyncio.sleep(0)
            if getattr(resp.transport, '_conn_lost', None) and resp.transport._conn_lost > 5:
                break
    return response.stream(stream, content_type='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/size/<id>')
async def size(request, id):
    info = HOST.get(id)
    if info is None:
        return response.json({'code': 404})
    size = info.get('size')
    return response.json({'code': 200, 'data': size})


@app.websocket('/websocket/host')
async def host(request, ws):
    line = await ws.recv()
    info = json.loads(line)
    id = info.get('login')
    size = info.get('size')
    await login(id, ws, size)
    while True:
        try:
            pong_waiter = await ws.ping()
            await pong_waiter
        except:
            break
        await asyncio.sleep(30)
    if id in HOST:
        del HOST[id]

async def login(id, ws, size):
    logging.info('login in host[%s]', id)
    await ws.send(json.dumps({'code':200}))
    HOST[id] = {'ws': ws, 'size':size}

@app.websocket('/websocket/manage')
async def manage(request, ws):
    id = request.args.get('id')
    info = HOST.get(id)
    if info is None:
        return
    h_ws = info.get('ws')
    async def pipe():
        while True:
            try:
                line = await h_ws.recv()
                if not line:
                    break
                await ws.send(line)
            except:
                break
    handler = asyncio.ensure_future(pipe())
    while True:
        try:
            line = await ws.recv()
            if not line:
                break
            await h_ws.send(line)
        except:
            break
    try:
        await h_ws.send(json.dumps({'action':'stop_monitor'}))
    except:
        pass
    finally:
        handler.cancel()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)