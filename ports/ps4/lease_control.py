"""Owner-operated controls/heartbeat ONLY, never loads a PS4 payload or plugin."""
import argparse
import ftplib
import io
import ipaddress
import threading
import time

if __package__:
    from .probe_transport import read_bounded
else:
    from probe_transport import read_bounded

MODES = {'stop':0, 'walk':1, 'sit':2, 'idle':3}
REMOTE = '/data/Arfoxia'
CONTROL = 'control-v9.txt'
TEMP = 'control-v9.upload-verify'


def encode(sequence, mode):
    if type(sequence) is not int or not 1 <= sequence <= 4294967295:
        raise ValueError('Sequence out of range')
    if type(mode) is not int or mode not in MODES.values():
        raise ValueError('Unknown pet mode')
    return f'ARFOXIA9:{sequence:010d}:{mode}\n'.encode('ascii')


def decode(value):
    if (len(value) != 22 or value[:9] != b'ARFOXIA9:' or value[19:20] != b':' or
        value[-1:] != b'\n' or not value[9:19].isdigit() or value[20:21] not in (b'0',b'1',b'2',b'3')):
        raise ValueError('Invalid existing owner control file; preserve it')
    sequence,mode = int(value[9:19]),int(value[20:21])
    if encode(sequence,mode) != value: raise ValueError('Invalid control encoding')
    return sequence,mode


def write_control(host, mode, *, ftp_factory=ftplib.FTP):
    address = ipaddress.ip_address(host)
    if not address.is_private or address.is_unspecified or address.is_multicast:
        raise ValueError('An explicit private owner-console IP is required')
    if mode not in MODES: raise ValueError('Unknown pet action')
    with ftp_factory(timeout=4) as ftp:
        ftp.connect(str(address),2121)
        ftp.login()
        ftp.cwd(REMOTE)
        names = {name.rsplit('/',1)[-1] for name in ftp.nlst()}
        if TEMP in names: raise ValueError('Interrupted control write; preserve temporary file')
        previous = decode(read_bounded(ftp,CONTROL,32))[0] if CONTROL in names else 0
        value = encode(previous+1,MODES[mode])
        ftp.storbinary('STOR '+TEMP,io.BytesIO(value))
        if read_bounded(ftp,TEMP,32) != value: raise ValueError('Control byte verification failed')
        # Atomic replacement of this OWN control file only. No log/plugin writes.
        ftp.rename(TEMP,CONTROL)
        return previous+1


def demo_mode(elapsed):
    if elapsed < 20: return 'walk'
    if elapsed < 32: return 'sit'
    if elapsed < 44: return 'idle'
    if elapsed < 60: return 'walk'
    return 'stop'


def panel(host, max_seconds=300, *, demo=False):
    import tkinter as tk
    from tkinter import ttk
    window = tk.Tk()
    window.title('Arfoxia · Control de PS4 (menú)')
    window.geometry('440x235')
    window.resizable(False,False)
    mode='walk'
    manual=False
    lock=threading.Lock()
    closed=threading.Event()
    ended=threading.Event()
    buttons=[]
    messages=[]
    started=time.monotonic()
    status=tk.StringVar(value='Conectando señal de control…')
    def choose(value):
        nonlocal mode,manual
        if not ended.is_set():
            with lock: mode=value; manual=True
    ttk.Label(window,text='Solo menú de PS4 · sin juegos',font=('Segoe UI',12,'bold')).pack(pady=12)
    row=ttk.Frame(window); row.pack(pady=5)
    for label,value in [('Caminar','walk'),('Sentarse','sit'),('Quieta','idle')]:
        button=ttk.Button(row,text=label,command=lambda v=value:choose(v))
        button.pack(side='left',padx=4); buttons.append(button)
    button=ttk.Button(window,text='Retirar de PS4 / Detener',command=lambda:choose('stop'))
    button.pack(pady=10); buttons.append(button)
    ttk.Label(window,textvariable=status,wraplength=410).pack(pady=5)
    ttk.Label(window,text=f'Sesión de prueba: máximo {max_seconds//60} minutos; sin autoarranque.').pack()
    def worker():
        while True:
            elapsed=time.monotonic()-started
            with lock: selected=demo_mode(elapsed) if demo and not manual else mode
            if closed.is_set() or elapsed >= max_seconds: selected='stop'
            try:
                sequence=write_control(host,selected)
                message=f'Señal enviada: {selected} · {sequence} (no confirma dibujo)'
            except (OSError,ValueError,EOFError,ftplib.Error):
                message='Conexión perdida: la señal caducará y Arfoxia se retirará.'
                selected='stop'
            with lock: messages.append(message)
            if selected == 'stop': ended.set(); break
            closed.wait(2)
    def poll():
        with lock:
            if messages: status.set(messages[-1]); messages.clear()
        if ended.is_set():
            for button in buttons: button.configure(state='disabled')
        if not closed.is_set(): window.after(150,poll)
    def close():
        closed.set(); window.destroy() # Best-effort stop; lease expiry also protects.
    window.protocol('WM_DELETE_WINDOW',close)
    thread=threading.Thread(target=worker,daemon=True); thread.start()
    poll(); window.mainloop()
    thread.join(5) # Do not hang owner UI if FTP is lost; lease still expires.


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',required=True)
    parser.add_argument('--mode',choices=MODES,default='walk')
    parser.add_argument('--panel',action='store_true')
    parser.add_argument('--demo',action='store_true',help='Panel: walk, sit, idle, walk, stop in one minute')
    args=parser.parse_args()
    if args.panel: panel(args.host,demo=args.demo)
    else: print('Owner control sequence:',write_control(args.host,args.mode))


if __name__ == '__main__': main()
