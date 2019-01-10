import win32serviceutil
import win32service
import win32event
import servicemanager
import logging
import pyautogui
import time
import cv2
import numpy as np
import websockets
from PIL import ImageChops, Image, ImageGrab
import json
import asyncio
import ctypes
from functools import partial
import win32api, win32con, win32gui, win32ui
import struct

logging.basicConfig(
    filename = r'C:\Windows\Temp\host.log',
    level = logging.INFO, 
    format = '%(asctime)s [NiceProxy] %(levelname)-7.7s %(message)s'
)
logger = logging.getLogger(__name__)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

ID = "1"
# SERVER_WS_URL = 'ws://127.0.0.1/websocket/host'
SERVER_WS_URL = 'ws://w.ryan-site.tk/websocket/host'
tencent = '123.207.242.135'
SERVER_WS_URL = 'ws://123.207.242.135/websocket/host'
SERVER_WS_URL = 'ws://172.19.3.241:801/websocket/host'


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

def screenshot():
    hwnd = 0 # 窗口的编号，0号表示当前活跃窗口
    # 根据窗口句柄获取窗口的设备上下文DC（Divice Context）
    hwndDC = win32gui.GetWindowDC(hwnd)
    # 根据窗口的DC获取mfcDC
    mfcDC = win32ui.CreateDCFromHandle(hwndDC)
    # mfcDC创建可兼容的DC
    saveDC = mfcDC.CreateCompatibleDC()
    # 创建bigmap准备保存图片
    saveBitMap = win32ui.CreateBitmap()
    # 获取监控器信息
    MoniterDev = win32api.EnumDisplayMonitors(None, None)
    w = MoniterDev[0][2][2]
    h = MoniterDev[0][2][3]
    # print w,h　　　#图片大小
    # 为bitmap开辟空间
    saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
    # 高度saveDC，将截图保存到saveBitmap中
    saveDC.SelectObject(saveBitMap)
    # 截取从左上角（0，0）长宽为（w，h）的图片
    saveDC.BitBlt((0, 0), (w, h), mfcDC, (0, 0), win32con.SRCCOPY)
    bmpinfo = saveBitMap.GetInfo()
    bmpstr = saveBitMap.GetBitmapBits(True)
    im = Image.frombuffer(
        'RGB',
        (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
        bmpstr, 'raw', 'BGRX', 0, 1)
    # win32gui.DeleteObject(saveBitMap.GetHandle())
    # saveDC.DeleteDC()
    # mfcDC.DeleteDC()
    # win32gui.ReleaseDC(hwnd, hwndDC)
    return im

class Client:
    def __init__(self, server_ws_url, scale=0.7, monitor_interval=0.05, ssl=False):
        self._server_ws_url = server_ws_url
        self._ssl = ssl
        self.hotkey = partial(pyautogui.hotkey, _pause=False)
        self.moveTo = partial(pyautogui.moveTo, _pause=False)
        self.mouseDown = partial(pyautogui.mouseDown, _pause=False)
        self.mouseUp = partial(pyautogui.mouseUp, _pause=False)
        self.scroll = partial(pyautogui.scroll, _pause=False)
        self.screenshot = screenshot
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
            logger.info("start monitor runner")
            while self._monitor:
                await asyncio.sleep(self.monitor_interval)
                try:
                    frame = self.screenshot()
                except Exception as e:
                    import traceback as tb
                    logger.warning('some thing wrong!')
                    logger.warning(tb.format_exc())
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
        frame = np.array(img)
        prefix = prefix = struct.pack('>2H', *pos)
        frame = cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        _,frame = cv2.imencode('.jpeg', frame)
        await self.ws.send(prefix + frame.tobytes())
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
        await self._send({'login':ID, 'size':size})
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
            while True and not self._stop:
                try:
                    await self.connect()
                    break
                except:
                    await asyncio.sleep(10)
        line = await self.ws.recv()
        if line:
            cmd = json.loads(line)
            await self._handle(cmd.get('action'), *cmd.get('args', []), **cmd.get('kw', {}))

    async def run_forever(self):
        logger.info('service run')
        while not self._stop:
            await self.run_once()
            await asyncio.sleep(0.0)

    def stop(self):
        logger.info('worker stopping')
        self._stop=True


class HelloWorldSvc (win32serviceutil.ServiceFramework):
    _svc_name_ = "RHost"
    _svc_display_name_ = "RHostService"
    
    def __init__(self,args):
        win32serviceutil.ServiceFramework.__init__(self,args)
        self._loop = asyncio.new_event_loop()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        logging.info('Stopping service ...')
        self._loop.call_soon_threadsafe(self.c.stop)
        self._loop.ensure_future(self.c.ws.close())

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_,'')
        )
        logger.info('service starting')
        self.c = Client(SERVER_WS_URL)
        try:
            self._loop.run_until_complete(self.c.run_forever())
        finally:
            self._loop.close()

if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(HelloWorldSvc)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(HelloWorldSvc)