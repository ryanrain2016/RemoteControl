import pyautogui
import time
# import cv2
# import numpy as np
import websockets
from PIL import ImageChops, Image, ImageGrab
import json
import asyncio
import ctypes
import logging
from functools import partial
import win32api, win32con, win32gui
import struct
from io import BytesIO
import uuid, socket, hashlib

logging.basicConfig(level = logging.INFO, format = '%(asctime)s - %(name)s - %(filename)s[%(lineno)d] - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

def get_pc_name():
    return socket.getfqdn(socket.gethostname())

def get_mac_address(): 
    mac=uuid.UUID(int = uuid.getnode()).hex[-12:] 
    return ":".join([mac[e:e+2] for e in range(0,11,2)])

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

ID = get_hash(get_pc_name()+get_mac_address()+"qsefthuko")
# SERVER_WS_URL = 'ws://127.0.0.1/websocket/host'
SERVER_WS_URL = 'ws://w.ryan-site.tk/websocket/host'
tencent = '123.207.242.135'
SERVER_WS_URL = 'ws://123.207.242.135/websocket/host'
SERVER_WS_URL = 'ws://172.19.3.241:801/websocket/host'
SERVER_WS_URL = 'ws://172.19.3.133/websocket/host'

class LoginError(Exception):
    pass

def setWallPaper(path=""):
    reg_key = win32api.RegOpenKeyEx(win32con.HKEY_CURRENT_USER, "Control Panel\\Desktop", 0, win32con.KEY_SET_VALUE|win32con.KEY_ALL_ACCESS)
    try:
        win32gui.SystemParametersInfo(win32con.SPI_SETDESKWALLPAPER, path, win32con.SPIF_SENDWININICHANGE)
    except:pass
    finally:
        win32api.RegCloseKey(reg_key)

def getWallPaper():
    reg_key = win32api.RegOpenKeyEx(win32con.HKEY_CURRENT_USER, "Control Panel\\Desktop", 0, win32con.KEY_SET_VALUE|win32con.KEY_ALL_ACCESS)
    try:
        i = 0
        while True:
            item = win32api.RegEnumValue(reg_key, i)
            if item[0] == 'WallPaper':
                return item[1]
            i += 1
    except:pass
    finally:
        win32api.RegCloseKey(reg_key)

class Client:
    def __init__(self, server_ws_url, scale=0.7, monitor_interval=0.05, ssl=False):
        self._server_ws_url = server_ws_url
        self._ssl = ssl
        self.hotkey = partial(pyautogui.hotkey, _pause=False)
        self.moveTo = partial(pyautogui.moveTo, _pause=False)
        self.mouseDown = partial(pyautogui.mouseDown, _pause=False)
        self.mouseUp = partial(pyautogui.mouseUp, _pause=False)
        self.scroll = partial(pyautogui.scroll, _pause=False)
        self.screenshot = pyautogui.screenshot
        self.position = pyautogui.position
        self.size = pyautogui.size

        self.ws = None
        self._stop = False
        self._monitor = False
        self._monitor_handler = None
        self._wallpaper = getWallPaper()
        self.ww, self.hh = 8, 8   #表示屏幕的宽,高分成多少份计算差别
        self.scale = scale        #缩放比例
        self.monitor_interval = monitor_interval  #截屏间隔

    def keyDown(self, keyCode):
        ctypes.windll.user32.keybd_event(keyCode, 0, 0, 0)

    def keyUp(self, keyCode):
        ctypes.windll.user32.keybd_event(keyCode, 0, 2, 0) 

    def start_monitor(self):
        logger.info("starting monitor")
        setWallPaper()
        if self._monitor and self._monitor_handler is not None:
            return
        self._monitor = True
        async def runner():
            last_frame = None
            w, h = self.size()
            pos = [0,0]
            _ww, _hh = w//self.ww, h//self.hh
            boxes = [(_ww*_w, _hh*_h, _ww*_w+_ww, _hh*_h+_hh) for _w in range(self.ww) for _h in range(self.hh)]
            while self._monitor:
                await asyncio.sleep(self.monitor_interval)
                try:
                    frame = self.screenshot()
                except Exception as e:
                    import traceback as tb
                    print(tb.format_exc())
                    continue
                frame = frame.resize((int(frame.size[0] * self.scale), int(frame.size[1] * self.scale)), Image.ANTIALIAS) 
                frames = [frame.crop(box) for box in boxes]
                if last_frame is not None:
                    # diff = ImageChops.difference(frame, last_frame)
                    # rect = diff.getbbox()
                    # if rect is None:
                    #     logger.info('no change no send!')
                    #     continue
                    # pos = rect[:2]
                    # changeframe = frame.crop(rect)
                    # await self.sendimg(pos, changeframe)
                    for frame, last, box in zip(frames, last_frame, boxes):
                        diff = ImageChops.difference(frame, last)
                        rect = diff.getbbox()
                        if rect is None:
                            logger.debug('no change no send')
                            continue
                        pos = (rect[0]+box[0], rect[1]+box[1])
                        frame = frame.crop(rect)
                        await self.sendimg(pos, frame)
                else:
                    await self.sendimg(pos, frame)
                last_frame = frames

        self._monitor_handler = asyncio.ensure_future(runner())

    async def sendimg(self, pos, img):
        # frame = np.array(img)
        prefix = prefix = struct.pack('>2H', *pos)
        # frame = cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        # _,frame = cv2.imencode('.jpeg', frame)
        # await self.ws.send(prefix + frame.tobytes())
        io = BytesIO()
        img.save(io, 'jpeg')
        await self.ws.send(prefix + io.getvalue())
        logger.debug('send a frame, pos[%s]', str(pos))

    def stop_monitor(self):
        logger.info("stopping monitor")
        setWallPaper(self._wallpaper)
        if self._monitor and self._monitor_handler is not None:
            self._monitor = False
            self._monitor_handler.cancel()
            self._monitor_handler = None

    async def _send(self, obj):
        await self.ws.send(json.dumps(obj))

    async def _handle(self, action, *args, **kw):
        logging.debug('handling action[%s]， args[%s], kw[%s]', action, str(args), str(kw))
        attr = getattr(self, action, None)
        if attr is None or attr in (self.screenshot, ) or action.startswith('_'):
            return
        attr(*args, **kw)

    async def connect(self):
        ssl_context = None
        if self._ssl:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.ws = await websockets.connect(self._server_ws_url, ssl=ssl_context)
        size = self.size()
        await self._send({'login':ID, 'size':size, 'pcname': get_pc_name(), 'mac': get_mac_address()})
        line = await self.ws.recv()
        cmd = json.loads(line)
        if cmd['code']==200:
            logger.info('server connected')
            return self.ws
        await self.ws.close()
        self.ws = None
        raise LoginError

    async def run_once(self):
        if self.ws is None:
            while True:
                try:
                    await self.connect()
                    break
                except ConnectionRefusedError:
                    logger.info('Connection Refused')
                    await asyncio.sleep(5)
        line = await self.ws.recv()
        if line:
            cmd = json.loads(line)
            await self._handle(cmd.get('action'), *cmd.get('args', []), **cmd.get('kw', {}))

    async def run_forever(self):
        while not self._stop:
            try:
                await self.run_once()
            except websockets.exceptions.ConnectionClosed:
                await self.ws.close()
                self.ws = None
                self.stop_monitor()
                await asyncio.sleep(5)
            await asyncio.sleep(0.0)

    def stop(self):
        self._stop=True
        asyncio.ensure_future(self.ws.close())

if __name__ == '__main__':
    c = Client(SERVER_WS_URL)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(c.run_forever())