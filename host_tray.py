import os  
import sys   
import win32gui_struct  
import pyautogui
import time
import websockets
from PIL import ImageChops, Image, ImageGrab
import json
import asyncio
import ctypes
import logging
from functools import partial
import win32api, win32con, win32gui
import struct
import uuid, socket, hashlib
from threading import Thread
from io import BytesIO
try:  
    import winxpgui as win32gui  
except ImportError:  
    import win32gui  

logging.basicConfig(level = logging.INFO, 
    format = '%(asctime)s - %(name)s - %(filename)s[%(lineno)d] - %(levelname)s - %(message)s',
    # filename = r'C:\Windows\Temp\host_tray.log',
    )
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

SERVER_WS_URL = 'ws://w.ryan-site.tk/websocket/host'
tencent = '123.207.242.135'
SERVER_WS_URL = 'ws://123.207.242.135/websocket/host'
SERVER_WS_URL = 'ws://172.19.3.241:801/websocket/host'
SERVER_WS_URL = 'ws://172.19.3.133:800/websocket/host'
# SERVER_WS_URL = 'wss://rdp.ryan-site.tk/websocket/host'

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
        self._close_handler = None

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
        prefix = prefix = struct.pack('>2H', *pos)
        try:
            io = BytesIO()
            img.save(io, 'jpeg')
            await self.ws.send(prefix + io.getvalue())
        except Exception as e:
            logger.error(e)
            raise
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
        self.ws = await websockets.connect(self._server_ws_url, ssl=self._ssl)
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
            while True and not self._stop:
                try:
                    await self.connect()
                    break
                except Exception as e: # ConnectionRefusedError:
                    logger.info('connect faild [%s], retry in 5 senconds.',e)
                    await asyncio.sleep(5)
        try:
            line = await self.ws.recv()
        except: # websockets.exceptions.ConnectionClosed:
            return
        if line:
            cmd = json.loads(line)
            await self._handle(cmd.get('action'), *cmd.get('args', []), **cmd.get('kw', {}))

    async def run_forever(self):
        while not self._stop:
            try:
                await self.run_once()
            except websockets.exceptions.ConnectionClosed:
                logger.info('ConnectionClosed')
                await self.ws.close()
                self.ws = None
                self.stop_monitor()
                await asyncio.sleep(5)
            await asyncio.sleep(0.0)

    def stop(self):
        self.stop_monitor()
        self._stop=True
        if self.ws:
            self._close_handler = asyncio.ensure_future(self.ws.close())

    async def wait_stop(self):
        if self._close_handler is not None:
            await self._close_handler
            self._close_handler = None

class SysTrayIcon:
    QUIT = 'QUIT'  
    SPECIAL_ACTIONS = [QUIT]  
      
    FIRST_ID = 1023  
      
    def __init__(self,  
                 icon,  
                 hover_text,  
                 menu_options,  
                 on_quit=None,  
                 default_menu_index=None,  
                 window_class_name=None,):  
          
        self.icon = icon  
        self.hover_text = hover_text  
        self.on_quit = on_quit  
          
        menu_options = menu_options + (('退出', None, self.QUIT),)  
        self._next_action_id = self.FIRST_ID  
        self.menu_actions_by_id = set()  
        self.menu_options = self._add_ids_to_menu_options(list(menu_options))  
        self.menu_actions_by_id = dict(self.menu_actions_by_id)  
        del self._next_action_id  
          
          
        self.default_menu_index = (default_menu_index or 0)  
        self.window_class_name = window_class_name or "SysTrayIconPy"  
          
        message_map = {win32gui.RegisterWindowMessage("TaskbarCreated"): self.restart,  
                       win32con.WM_DESTROY: self.destroy,  
                       win32con.WM_COMMAND: self.command,  
                       win32con.WM_USER+20 : self.notify,}  
        # Register the Window class.  
        window_class = win32gui.WNDCLASS()  
        hinst = window_class.hInstance = win32gui.GetModuleHandle(None)  
        window_class.lpszClassName = self.window_class_name  
        window_class.style = win32con.CS_VREDRAW | win32con.CS_HREDRAW;  
        window_class.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)  
        window_class.hbrBackground = win32con.COLOR_WINDOW  
        window_class.lpfnWndProc = message_map # could also specify a wndproc.  
        classAtom = win32gui.RegisterClass(window_class)  
        # Create the Window.  
        style = win32con.WS_OVERLAPPED | win32con.WS_SYSMENU  
        self.hwnd = win32gui.CreateWindow(classAtom,  
                                          self.window_class_name,  
                                          style,  
                                          0,  
                                          0,  
                                          win32con.CW_USEDEFAULT,  
                                          win32con.CW_USEDEFAULT,  
                                          0,  
                                          0,  
                                          hinst,  
                                          None)  
        win32gui.UpdateWindow(self.hwnd)  
        self.notify_id = None  
        self.refresh_icon()
        self._start_worker()
        win32gui.PumpMessages() 

    def _start_worker(self):
        self._thread = Thread(target=self._worker)
        self._thread.setDaemon(True)
        self._thread.start()

    def _worker(self):
        self._loop = asyncio.new_event_loop()
        self._host_client = Client(SERVER_WS_URL, ssl=None)
        self._loop.run_until_complete(self._host_client.run_forever())
        self._loop.run_until_complete(self._host_client.wait_stop())
        self._loop.close()

    def _stop(self):
        if self._thread is None:
            return
        self._loop.call_soon_threadsafe(self._host_client.stop)
        self._thread.join()
        self._thread = None
        logger.info('worker stopped')
        self._loop = None
        self._host_client = None
  
    def _add_ids_to_menu_options(self, menu_options):  
        result = []
        for menu_option in menu_options:  
            option_text, option_icon, option_action = menu_option  
            if callable(option_action) or option_action in self.SPECIAL_ACTIONS:  
                self.menu_actions_by_id.add((self._next_action_id, option_action))  
                result.append(menu_option + (self._next_action_id,))  
            elif non_string_iterable(option_action):  
                result.append((option_text,
                               option_icon,
                               self._add_ids_to_menu_options(option_action),  
                               self._next_action_id))  
            else:  
                print('Unknown item', option_text, option_icon, option_action)
            self._next_action_id += 1  
        return result
          
    def refresh_icon(self):  
        # Try and find a custom icon  
        hinst = win32gui.GetModuleHandle(None)  
        if os.path.isfile(self.icon):  
            icon_flags = win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE  
            hicon = win32gui.LoadImage(hinst,  
                                       self.icon,  
                                       win32con.IMAGE_ICON,  
                                       0,  
                                       0,  
                                       icon_flags)  
        else:  
            print("Can't find icon file - using default.")
            hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)  
  
        if self.notify_id: message = win32gui.NIM_MODIFY  
        else: message = win32gui.NIM_ADD  
        self.notify_id = (self.hwnd,  
                          0,  
                          win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,  
                          win32con.WM_USER+20,  
                          hicon,  
                          self.hover_text)  
        win32gui.Shell_NotifyIcon(message, self.notify_id)  
  
    def restart(self, hwnd, msg, wparam, lparam):  
        self.refresh_icon()  
  
    def destroy(self, hwnd, msg, wparam, lparam):  
        if self.on_quit: self.on_quit(self)  
        nid = (self.hwnd, 0)  
        win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, nid)  
        win32gui.PostQuitMessage(0) # Terminate the app.  
  
    def notify(self, hwnd, msg, wparam, lparam):  
        if lparam==win32con.WM_LBUTTONDBLCLK:  
            self.execute_menu_option(self.default_menu_index + self.FIRST_ID)  
        elif lparam==win32con.WM_RBUTTONUP:  
            self.show_menu()  
        elif lparam==win32con.WM_LBUTTONUP:  
            pass  
        return True  
          
    def show_menu(self):  
        menu = win32gui.CreatePopupMenu()  
        self.create_menu(menu, self.menu_options)  
        #win32gui.SetMenuDefaultItem(menu, 1000, 0)  
          
        pos = win32gui.GetCursorPos()  
        # See http://msdn.microsoft.com/library/default.asp?url=/library/en-us/winui/menus_0hdi.asp  
        win32gui.SetForegroundWindow(self.hwnd)  
        win32gui.TrackPopupMenu(menu,  
                                win32con.TPM_LEFTALIGN,  
                                pos[0],  
                                pos[1],  
                                0,  
                                self.hwnd,  
                                None)  
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)  
      
    def create_menu(self, menu, menu_options):  
        for option_text, option_icon, option_action, option_id in menu_options[::-1]:  
            if option_icon:  
                option_icon = self.prep_menu_icon(option_icon)  
              
            if option_id in self.menu_actions_by_id:                  
                item, extras = win32gui_struct.PackMENUITEMINFO(text=option_text,  
                                                                hbmpItem=option_icon,  
                                                                wID=option_id)  
                win32gui.InsertMenuItem(menu, 0, 1, item)  
            else:  
                submenu = win32gui.CreatePopupMenu()  
                self.create_menu(submenu, option_action)  
                item, extras = win32gui_struct.PackMENUITEMINFO(text=option_text,  
                                                                hbmpItem=option_icon,  
                                                                hSubMenu=submenu)  
                win32gui.InsertMenuItem(menu, 0, 1, item)  
  
    def prep_menu_icon(self, icon):  
        ico_x = win32api.GetSystemMetrics(win32con.SM_CXSMICON)  
        ico_y = win32api.GetSystemMetrics(win32con.SM_CYSMICON)  
        hicon = win32gui.LoadImage(0, icon, win32con.IMAGE_ICON, ico_x, ico_y, win32con.LR_LOADFROMFILE)  
  
        hdcBitmap = win32gui.CreateCompatibleDC(0)  
        hdcScreen = win32gui.GetDC(0)  
        hbm = win32gui.CreateCompatibleBitmap(hdcScreen, ico_x, ico_y)  
        hbmOld = win32gui.SelectObject(hdcBitmap, hbm)  
        brush = win32gui.GetSysColorBrush(win32con.COLOR_MENU)  
        win32gui.FillRect(hdcBitmap, (0, 0, 16, 16), brush)  
        win32gui.DrawIconEx(hdcBitmap, 0, 0, hicon, ico_x, ico_y, 0, 0, win32con.DI_NORMAL)  
        win32gui.SelectObject(hdcBitmap, hbmOld)  
        win32gui.DeleteDC(hdcBitmap)  
        return hbm  
  
    def command(self, hwnd, msg, wparam, lparam):
        id = win32gui.LOWORD(wparam)
        self.execute_menu_option(id)
          
    def execute_menu_option(self, id):
        menu_action = self.menu_actions_by_id[id]
        if menu_action == self.QUIT:
            win32gui.DestroyWindow(self.hwnd)
        else:  
            menu_action(self)  
              
def non_string_iterable(obj):  
    try:  
        iter(obj)  
    except TypeError:  
        return False  
    else:  
        return not isinstance(obj, basestring)
      

if __name__ == '__main__':  
    import itertools, glob, sys, os
    if getattr( sys, 'frozen', False ):
        path = sys._MEIPASS
    else:
        path = os.path.abspath('.')
    icons = os.path.join(path, 'remotecontrol.ico') 
    hover_text = "远程控制"  
    def stop(obj):
        obj._stop()

    def start(obj):
        if obj._thread is not None:
            return
        obj._start_worker()

    menu_options = (('停止', icons, stop),  
                    ('启动', icons, start),
                   )  
    def bye(sysTrayIcon): print('退出')
      
    SysTrayIcon(icons, hover_text, menu_options, on_quit=bye)